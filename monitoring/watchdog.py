# -*- coding: utf-8 -*-
"""
Watchdog COMET-RIOBAMBA — monitor en tiempo real (18/08/2026).

Proceso continuo de fondo (lanza run-watchdog.ps1). Cada
WATCHDOG_INTERVAL_SECONDS (default 60) verifica:

  1. Agente vivo       → auto-reinicio graceful (run-prod.ps1) si cayó
                         sin stop.flag (cooldown 30 min, máx 2/hora)
  2. Circuitos LLM     → data/cascade_telemetry.jsonl: 3+ fallos/10 min = OPEN
  3. Errores de log    → ERROR/CRITICAL en ventana 1h
  4. Modo degradado    → data/degraded_mode_state.json
  5. Saldos            → DeepSeek + OpenRouter (cada 15 min)
  6. Telegram          → fallos de envío → reintento del outbox
  7. Inactividad       → 0 comments en 12h y 0 posts en 48h

Estado inspeccionable: monitoring/watchdog-state.json
Alertas: monitoring/alerts.jsonl (compartido con health-check.ps1 → un
único cooldown, sin duplicados). Envíos a Telegram registrados en
monitoring/telegram-sent.log y monitoring/telegram-ledger.jsonl.

Uso:
  python monitoring/watchdog.py          # loop continuo
  python monitoring/watchdog.py --once   # una sola pasada (verificación)
"""
import html
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    requests = None  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "logs" / "watchdog.log"
STATE_FILE = ROOT / "monitoring" / "watchdog-state.json"
ALERTS_FILE = ROOT / "monitoring" / "alerts.jsonl"
TG_SENT_FILE = ROOT / "monitoring" / "telegram-sent.log"
LEDGER_FILE = ROOT / "monitoring" / "telegram-ledger.jsonl"
LOCK_FILE = ROOT / ".watchdog.lock"

AGENT_LOCK_FILE = ROOT / ".agent.lock"
HEALTH_FILE = ROOT / "data" / "state" / "health.json"
STOP_FLAG = ROOT / "data" / "stop.flag"
TELEMETRY_FILE = ROOT / "data" / "cascade_telemetry.jsonl"
AGENT_LOG = ROOT / "logs" / "agent.log"
DEGRADED_FILE = ROOT / "data" / "degraded_mode_state.json"
METRICS_DIR = ROOT / "data" / "metrics"
OUTBOX_FILE = ROOT / "data" / "telegram_outbox.json"

# ── Umbrales (ajustables por env, con defaults seguros) ──────────────
INTERVAL_SECONDS = int(os.getenv("WATCHDOG_INTERVAL_SECONDS", "60"))
HEALTH_STALE_RESTART_S = int(os.getenv("WATCHDOG_HEALTH_STALE_S", "600"))
HEALTH_STUCK_RESTART_S = int(os.getenv("WATCHDOG_HEALTH_STUCK_S", "7200"))
HEALTH_FROZEN_WARN_S = int(os.getenv("WATCHDOG_FROZEN_WARN_S", "900"))
CIRCUIT_WINDOW_S = int(os.getenv("WATCHDOG_CIRCUIT_WINDOW_S", "600"))
CIRCUIT_FAIL_THRESHOLD = int(os.getenv("WATCHDOG_CIRCUIT_FAILS", "3"))
ERROR_WINDOW_S = 3600
ERROR_THRESHOLD = int(os.getenv("WATCHDOG_ERRORS_1H", "10"))
BALANCE_INTERVAL_S = 15 * 60
BALANCE_LOW_USD = float(os.getenv("WATCHDOG_BALANCE_LOW_USD", "1.0"))
RESTART_COOLDOWN_S = 30 * 60
MAX_RESTARTS_1H = 2
INACTIVITY_COMMENTS_H = 12
INACTIVITY_POSTS_H = 48
OUTBOX_MAX = 50

# Cooldown por tipo de alerta (minutos)
ALERT_COOLDOWNS = {
    "watchdog-restart": 30,
    "watchdog-agent-down": 30,
    "watchdog-circuit-open": 30,
    "watchdog-circuit-recovered": 360,
    "watchdog-degraded": 360,
    "watchdog-log-errors": 60,
    "watchdog-saldo-bajo": 360,
    "watchdog-telegram-fail": 30,
    "watchdog-telegram-recovered": 360,
    "watchdog-inactivity": 720,
}

logger = logging.getLogger("watchdog")


# ═══════════════════════════════════════════════════════════════════
# Utilidades puras (testeables)
# ═══════════════════════════════════════════════════════════════════

def parse_iso(ts_str: Optional[str]) -> Optional[float]:
    """ISO 8601 (con o sin tz) → epoch. None si no se puede parsear."""
    if not ts_str:
        return None
    s = ts_str.strip()
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        pass
    try:
        # Fracciones de microsegundo demasiado largas (ej. .4060388)
        import re
        s2 = re.sub(r"\.(\d{6})\d+", r".\1", s)
        return datetime.fromisoformat(s2).timestamp()
    except ValueError:
        return None


def parse_telemetry(tail_lines: List[str], window_s: float,
                    now: float) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Cuenta fallos/éxitos por proveedor en la ventana. Devuelve (fails, oks)."""
    fails: Dict[str, int] = {}
    oks: Dict[str, int] = {}
    cutoff = now - window_s
    for line in tail_lines:
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        ts = parse_iso(ev.get("ts") or ev.get("timestamp"))
        if ts is None or ts < cutoff:
            continue
        name = ev.get("provider") or ev.get("tier") or "unknown"
        ok = ev.get("success") in (True, "ok", "success", 1, "1")
        if ok:
            oks[name] = oks.get(name, 0) + 1
        else:
            fails[name] = fails.get(name, 0) + 1
    return fails, oks


def count_error_lines(lines: List[str], window_s: float, now: float) -> int:
    """Cuenta líneas 'ERROR |' / 'CRITICAL |' del log en la ventana (ts local)."""
    cutoff = now - window_s
    count = 0
    for line in lines:
        if " ERROR " not in line and " CRITICAL " not in line:
            continue
        try:
            ts = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            ts = now  # línea sin ts parseable → cuenta como reciente
        if ts >= cutoff:
            count += 1
    return count


def check_cooldown(entries: List[dict], alert_type: str,
                   cooldown_minutes: float, now: float) -> bool:
    """True si el cooldown ha expirado (o no hay entradas previas del tipo)."""
    last_ts = None
    for e in entries:
        if e.get("type") != alert_type:
            continue
        ts = parse_iso(e.get("ts"))
        if ts is not None and (last_ts is None or ts > last_ts):
            last_ts = ts
    if last_ts is None:
        return True
    return (now - last_ts) >= cooldown_minutes * 60


def pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # existe, aunque no tengamos permiso de señal
    except OSError:
        pass
    try:  # fallback Windows: tasklist
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, timeout=10,
        )
        text = out.stdout.decode("utf-8", errors="replace")
        return f"{pid}" in text
    except Exception:
        return True  # ambigüo → no reiniciar un agente que podría vivir


def agent_status(lock_file: Path, health_file: Path, stop_file: Path,
                 now: float) -> dict:
    """Estado del agente: alive, health_fresh_s, lock_pid, stopped, cycle_no."""
    stopped = stop_file.exists()
    lock_pid = None
    if lock_file.exists():
        try:
            pid_s = lock_file.read_text(encoding="utf-8").strip().splitlines()
            if pid_s and pid_s[0].isdigit():
                lock_pid = int(pid_s[0])
        except Exception:
            pass
    health_fresh_s = None
    cycle_no = None
    last_error = None
    if health_file.exists():
        try:
            health_fresh_s = now - health_file.stat().st_mtime
            health = json.loads(health_file.read_text(encoding="utf-8"))
            cycle_no = health.get("cycle")
            last_error = health.get("last_error")
        except Exception:
            health_fresh_s = None
    lock_alive = pid_alive(lock_pid)
    if health_fresh_s is not None and health_fresh_s < 600:
        alive = True  # ciclo reciente → el agente vive (fallback CIM-proof)
    else:
        alive = lock_alive and health_fresh_s is not None and health_fresh_s < 3600
    return {
        "alive": alive,
        "stopped": stopped,
        "lock_pid": lock_pid,
        "lock_alive": lock_alive,
        "health_fresh_s": health_fresh_s,
        "cycle_no": cycle_no,
        "last_error": last_error,
    }


def decide_restart(status: dict, last_restart_ts: Optional[float],
                   restarts_1h: int, now: float) -> bool:
    """Auto-reinicio gobernado por el lock-PID (fuente de verdad).

    Fix 18/08/2026: antes se reiniciaba por staleness de health.json (>10 min),
    pero los ciclos duran ~8 min y a veces más (waits de publicación 45s,
    retries 429, ingesta EPO) → falsos reinicios de un agente sano (alertas
    "Auto-reinicio" sin efecto real). El lock lo escribe el agente al arrancar
    y solo se limpia al salir el proceso: su PID vivo = agente vivo.
    """
    if status.get("stopped"):
        return False
    lock_alive = bool(status.get("lock_alive"))
    fresh = status.get("health_fresh_s")
    if lock_alive:
        # Agente corriendo: reiniciar solo si está congelado de verdad (2h+)
        return fresh is not None and fresh > HEALTH_STUCK_RESTART_S
    if fresh is not None and fresh < HEALTH_STALE_RESTART_S:
        return False  # gracia post-arranque (10 min): el lock aún pudo no escribirse
    if last_restart_ts and (now - last_restart_ts) < RESTART_COOLDOWN_S:
        return False
    if restarts_1h >= MAX_RESTARTS_1H:
        return False
    return True


def inactivity_flag(today_metrics: Optional[dict], yesterday_metrics: Optional[dict],
                    hours_since_midnight: float) -> bool:
    """0 comments en >=12h y 0 posts en >=48h → inactividad real."""
    if hours_since_midnight < INACTIVITY_COMMENTS_H:
        return False
    today_c = (today_metrics or {}).get("comments_published", 0)
    today_p = (today_metrics or {}).get("posts_published", 0)
    yest_p = (yesterday_metrics or {}).get("posts_published", 0)
    if today_metrics is None and hours_since_midnight < 24:
        return False  # sin métricas de hoy aún → no alarmar
    return today_c == 0 and (today_p + yest_p) == 0


# ═══════════════════════════════════════════════════════════════════
# Utilidades de I/O
# ═══════════════════════════════════════════════════════════════════

def load_env(root: Path) -> dict:
    """Carga .env en os.environ (solo vars no vacías) y devuelve el dict."""
    env: Dict[str, str] = {}
    env_file = root / ".env"
    if not env_file.exists():
        return env
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and v:
            env[k] = v
            os.environ.setdefault(k, v)
    return env


def read_tail(path: Path, max_lines: int = 2000) -> List[str]:
    try:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return f.readlines()[-max_lines:]
    except Exception:
        return []


def read_alerts(limit: int = 500) -> List[dict]:
    entries = []
    for line in read_tail(ALERTS_FILE, limit):
        try:
            entries.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return entries


def write_alert(entry: dict) -> None:
    try:
        ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with ALERTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("watchdog: alerts.jsonl write failed: %s", e)


def record_tg_sent(text: str) -> None:
    try:
        with TG_SENT_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().astimezone().isoformat()} | {text[:200]}\n")
    except Exception:
        pass
    try:
        with LEDGER_FILE.open("a", encoding="utf-8") as f:
            entry = {
                "ts": time.time(),
                "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "method": "sendMessage",
                "ok": True,
                "text": text[:300],
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def send_tg(token: str, chat: str, text: str) -> bool:
    if not token or not chat or requests is None:
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
            url, json={"chat_id": chat, "text": text,
                       "parse_mode": "HTML", "disable_notification": False},
            timeout=20,
        )
        ok = resp.status_code == 200 and resp.json().get("ok", False)
        if ok:
            record_tg_sent(text)
        else:
            logger.error("watchdog: telegram send failed: HTTP %s %s",
                         resp.status_code, resp.text[:200])
        return ok
    except Exception as e:
        logger.error("watchdog: telegram send error: %s", e)
        return False


def check_balances(env: dict) -> dict:
    """Saldos DeepSeek y OpenRouter. None si no se pudo consultar."""
    result = {"deepseek": None, "openrouter": None, "checked_at": None}
    # DeepSeek (reutiliza services/deepseek_balance)
    try:
        sys.path.insert(0, str(ROOT))
        from services.deepseek_balance import check_deepseek_balance  # noqa
        result["deepseek"] = check_deepseek_balance()
    except Exception as e:
        logger.warning("watchdog: deepseek balance failed: %s", e)
    # OpenRouter: /api/v1/credits → total_credits - total_usage
    key = env.get("MODEL_TIER_OPENROUTER_API_KEY", "")
    if key and requests is not None:
        try:
            resp = requests.get(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
            data = resp.json().get("data", {})
            tc = data.get("total_credits")
            tu = data.get("total_usage")
            if tc is not None and tu is not None:
                result["openrouter"] = float(tc) - float(tu)
        except Exception as e:
            logger.warning("watchdog: openrouter balance failed: %s", e)
    result["checked_at"] = time.time()
    return result


def read_metrics(date_str: str) -> Optional[dict]:
    p = METRICS_DIR / f"{date_str}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def retry_tg_outbox(token: str, chat: str) -> int:
    """Reintenta los envíos pendientes de data/telegram_outbox.json."""
    try:
        if not OUTBOX_FILE.exists():
            return 0
        entries = json.loads(OUTBOX_FILE.read_text(encoding="utf-8"))
        if not entries:
            return 0
    except Exception:
        return 0
    remaining, sent = [], 0
    for entry in entries:
        payload = entry.get("payload", {})
        payload["chat_id"] = chat
        if send_tg(token, chat, str(payload.get("text", ""))):
            sent += 1
        else:
            remaining.append(entry)
    try:
        OUTBOX_FILE.write_text(
            json.dumps(remaining[-OUTBOX_MAX:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("watchdog: outbox persist failed: %s", e)
    return sent


# ═══════════════════════════════════════════════════════════════════
# Tick principal
# ═══════════════════════════════════════════════════════════════════

def run_checks(env: dict, state: dict, now: float) -> Tuple[List[dict], dict]:
    """Ejecuta todas las verificaciones. Devuelve (alertas, reporte)."""
    alerts: List[dict] = []
    report: dict = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S")}

    # ── 1. Agente vivo / auto-reinicio ──────────────────────────────
    status = agent_status(AGENT_LOCK_FILE, HEALTH_FILE, STOP_FLAG, now)
    report["agent"] = {
        "alive": status["alive"],
        "stopped": status["stopped"],
        "lock_pid": status["lock_pid"],
        "lock_alive": status["lock_alive"],
        "health_fresh_s": status["health_fresh_s"],
        "cycle_no": status["cycle_no"],
        "last_error": status["last_error"],
    }
    if not status["alive"] and not status["stopped"]:
        fresh = status["health_fresh_s"]
        if fresh is not None and fresh > HEALTH_FROZEN_WARN_S:
            alerts.append({
                "type": "watchdog-agent-down",
                "severity": "critical",
                "summary": (f"Agente sin latido: health.json con "
                            f"{int(fresh // 60)} min de antigüedad"),
                "tg": ("🚨 *Agente sin latido*: health.json sin actualizar hace "
                       f"{int(fresh // 60)} min. Intentando reinicio..."),
            })
    if decide_restart(status, state.get("last_restart_ts"),
                      state.get("restarts_1h", 0), now):
        logger.warning("watchdog: agente caído → auto-reinicio (run-prod.ps1)")
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(ROOT / "run-prod.ps1")],
                cwd=str(ROOT), creationflags=flags,
            )
            state["last_restart_ts"] = now
            state["restarts_1h"] = state.get("restarts_1h", 0) + 1
            alerts.append({
                "type": "watchdog-restart",
                "severity": "critical",
                "summary": "Auto-reinicio del agente ejecutado (run-prod.ps1)",
                "tg": ("🔄 *Auto-reinicio COMET*: el agente estaba caído y se "
                       "relanzó automáticamente. Verificando en el próximo tick."),
            })
        except Exception as e:
            alerts.append({
                "type": "watchdog-agent-down",
                "severity": "critical",
                "summary": f"Auto-reinicio FALLÓ: {e}",
                "tg": (f"🚨 *Auto-reinicio FALLÓ*: {html.escape(str(e))}. "
                       "Requiere intervención manual."),
            })

    # ── 2. Circuitos LLM ────────────────────────────────────────────
    fails, oks = parse_telemetry(read_tail(TELEMETRY_FILE, 200),
                                 CIRCUIT_WINDOW_S, now)
    report["circuits"] = {"fails": fails, "oks": oks}
    prev_open = set(state.get("circuits_open", []))
    now_open = {name for name, n in fails.items() if n >= CIRCUIT_FAIL_THRESHOLD}
    report["circuits_open"] = sorted(now_open)
    for name in sorted(now_open - prev_open):
        alerts.append({
            "type": "watchdog-circuit-open",
            "severity": "warning",
            "summary": f"Circuito abierto: {name} ({fails[name]} fallos/{CIRCUIT_WINDOW_S//60} min)",
            "tg": (f"⚠️ *Circuito abierto*: proveedor {name} con "
                   f"{fails[name]} fallos en {CIRCUIT_WINDOW_S//60} min. "
                   "La cascada ya lo esquiva; se avisará al recuperarse."),
        })
    for name in sorted(prev_open - now_open):
        if oks.get(name, 0) >= 1:
            alerts.append({
                "type": "watchdog-circuit-recovered",
                "severity": "info",
                "summary": f"Proveedor {name} restaurado",
                "tg": f"✅ *Proveedor {name} restaurado*: vuelve a responder con éxito.",
            })

    # ── 3. Errores de log ───────────────────────────────────────────
    err_count = count_error_lines(read_tail(AGENT_LOG), ERROR_WINDOW_S, now)
    report["errors_1h"] = err_count
    if err_count > ERROR_THRESHOLD:
        alerts.append({
            "type": "watchdog-log-errors",
            "severity": "warning",
            "summary": f"{err_count} ERROR/CRITICAL en la última hora",
            "tg": f"⚠️ *Errores*: {err_count} ERROR/CRITICAL en el log (1h).",
        })

    # ── 4. Modo degradado ───────────────────────────────────────────
    degraded = False
    try:
        if DEGRADED_FILE.exists():
            degraded = bool(json.loads(DEGRADED_FILE.read_text(encoding="utf-8"))
                            .get("is_degraded"))
    except Exception:
        pass
    report["degraded"] = degraded
    if degraded:
        alerts.append({
            "type": "watchdog-degraded",
            "severity": "warning",
            "summary": "Cascada LLM en modo degradado",
            "tg": ("⚠️ *Modo degradado*: la cascada LLM se declaró degradada. "
                   "Revisar data/degraded_mode_state.json y saldos."),
        })

    # ── 5. Saldos (cada 15 min; alerta solo en transición a bajo) ──
    last_balance = state.get("balances_checked_at", 0.0)
    if now - last_balance >= BALANCE_INTERVAL_S:
        balances = check_balances(env)
        state["balances"] = balances
        state["balances_checked_at"] = now
        low = []
        for name in ("deepseek", "openrouter"):
            b = balances.get(name)
            if b is None:
                continue
            if b < BALANCE_LOW_USD:
                low.append(f"{name}: ${b:.2f}")
        was_low = state.get("saldo_low", False)
        now_low = len(low) > 0
        state["saldo_low"] = now_low
        if now_low and not was_low:
            alerts.append({
                "type": "watchdog-saldo-bajo",
                "severity": "warning",
                "summary": "Saldo bajo: " + ", ".join(low),
                "tg": (f"💰 *Saldo bajo*: {'; '.join(low)}. "
                       "Considerar recarga antes de que el proveedor falle."),
            })
    report["balances"] = state.get("balances", {})

    # ── 6. Telegram: fallos → reintento del outbox ──────────────────
    tg_fail = sum(1 for line in read_tail(AGENT_LOG, 2000)
                  if ("Telegram send" in line or "Telegram API returned ok=false" in line))
    report["telegram_failures_1h"] = tg_fail
    if tg_fail > 0:
        sent = retry_tg_outbox(env.get("TELEGRAM_BOT_TOKEN", ""),
                               env.get("TELEGRAM_CHAT_ID", ""))
        report["outbox_retried"] = sent
        if sent > 0:
            alerts.append({
                "type": "watchdog-telegram-recovered",
                "severity": "info",
                "summary": f"Telegram restaurado: {sent} envíos pendientes entregados",
                "tg": f"✅ *Telegram restaurado*: {sent} mensajes pendientes entregados.",
            })
        else:
            alerts.append({
                "type": "watchdog-telegram-fail",
                "severity": "warning",
                "summary": f"{tg_fail} fallos de envío Telegram (1h); outbox pendiente",
                "tg": ("⚠️ *Telegram con fallos*: los envíos fallidos quedan en "
                       "cola y se reintentarán automáticamente."),
            })

    # ── 7. Inactividad de publicación ───────────────────────────────
    now_dt = datetime.now()
    midnight = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    hours_midnight = (now_dt - midnight).total_seconds() / 3600.0
    today = now_dt.strftime("%Y-%m-%d")
    yesterday = (now_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    tm = read_metrics(today)
    ym = read_metrics(yesterday)
    inactive = inactivity_flag(tm, ym, hours_midnight)
    report["inactivity"] = inactive
    if inactive:
        alerts.append({
            "type": "watchdog-inactivity",
            "severity": "warning",
            "summary": "Sin comments en 12h y sin posts en 48h",
            "tg": ("📭 *Inactividad de publicación*: 0 comentarios en 12h y "
                   "0 posts en 48h. Sugerencia: revisar feed, cola own-post y "
                   "piso de relevancia (AGENT_MIN_REPLY_VALUE_SCORE)."),
        })

    # ── Últimos envíos al móvil (para inspección del asistente) ─────
    ledger_tail = [json.loads(l) for l in read_tail(LEDGER_FILE, 300)
                   if l.strip()]
    report["last_telegram_sent"] = [e.get("text", "")[:200]
                                    for e in ledger_tail[-3:]]
    report["alerts_today"] = sum(
        1 for e in read_alerts(500)
        if (e.get("ts") or "").startswith(datetime.now().strftime("%Y-%m-%d")))
    return alerts, report


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
        ],
    )
    env = load_env(ROOT)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat = env.get("TELEGRAM_CHAT_ID", "")

    # ── Single instance (race-free: O_CREAT|O_EXCL) ────────────────
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
    except FileExistsError:
        existing = _read_lock_pid()
        if existing and pid_alive(existing):
            logger.warning("watchdog: ya hay otra instancia (PID %s); salgo.", existing)
            return 1
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")  # lock huérfano

    # ── Estado persistido entre reinicios del watchdog ──────────────
    state: dict = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    state.setdefault("restarts_1h", 0)
    state.setdefault("circuits_open", [])
    if "restarts" in state:
        state.setdefault("last_restart_ts", state["restarts"].get("last_ts"))
    last_restart = state.get("last_restart_ts")
    if last_restart and (time.time() - float(last_restart)) > 3600:
        state["restarts_1h"] = 0

    once = "--once" in sys.argv
    logger.info("watchdog iniciado (intervalo=%ss, %s)",
                INTERVAL_SECONDS, "modo único" if once else "loop")

    try:
        _run_loop(env, state, once, token, chat, first=True)
    except KeyboardInterrupt:
        logger.info("watchdog detenido por el operador")
    except Exception:
        logger.exception("watchdog: fallo no controlado (se registrará el traceback)")
    finally:
        try:
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass
    return 0


def _run_loop(env: dict, state: dict, once: bool,
              token: str, chat: str, first: bool) -> None:
    while True:
        now = time.time()
        alerts, report = run_checks(env, state, now)
        state["circuits_open"] = report.get("circuits_open", [])
        if "last_restart_ts" in state:
            state["restarts"] = {"last_ts": state["last_restart_ts"]}
        state["ts"] = report["ts"]
        try:
            STATE_FILE.write_text(json.dumps(state, ensure_ascii=False,
                                             indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("watchdog: state write failed: %s", e)

        # ── Alertas: cooldown compartido con health-check ───────
        all_alerts = read_alerts(500)
        for a in alerts:
            cooldown_min = ALERT_COOLDOWNS.get(a["type"], 60)
            a["ts"] = datetime.now().astimezone().isoformat()
            write_alert({k: v for k, v in a.items() if k != "tg"})
            if check_cooldown(all_alerts, a["type"], cooldown_min, now):
                if a.get("tg") and not (a["severity"] == "info" and first):
                    send_tg(token, chat, f"[ALERTA COMET] {a['tg']}")

        if first:
            # El mensaje de inicio solo se envía una vez cada 6h (los
            # relanzamientos no deben spamear al operador).
            startup = {"type": "watchdog-startup", "severity": "info",
                       "summary": "Watchdog iniciado"}
            startup["ts"] = datetime.now().astimezone().isoformat()
            if check_cooldown(all_alerts, "watchdog-startup", 360, now):
                write_alert(startup)
                send_tg(token, chat,
                        "🛡️ <b>Watchdog COMET activo</b>\n"
                        "Monitoreo en tiempo real: agente, proveedores LLM, "
                        "saldos, errores y Telegram. Alertas con cooldown.")
                logger.info("watchdog: mensaje de inicio enviado")
            first = False

        logger.info("watchdog tick OK: agente=%s ciclos=%s circuitos=%s",
                    report["agent"]["alive"], report["agent"]["cycle_no"],
                    ",".join(report.get("circuits_open", [])))
        if once:
            break
        time.sleep(INTERVAL_SECONDS)


def _read_lock_pid() -> Optional[int]:
    try:
        if LOCK_FILE.exists():
            pid_s = LOCK_FILE.read_text(encoding="utf-8").strip()
            if pid_s.isdigit():
                return int(pid_s)
    except Exception:
        pass
    return None


if __name__ == "__main__":
    sys.exit(main())
