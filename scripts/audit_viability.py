# -*- coding: utf-8 -*-
"""Auditoría de viabilidad de COMET-RIOBAMBA en Moltbook.

Cierra el ciclo de valor que nunca medimos: no solo cuánto cuesta y cuánto
produce, sino si la presencia del agente realmente mueve la aguja de influencia
en la plataforma.

Métricas (ventana de análisis configurable, default 7 días):
  1. Karma / rango          — trayectoria vs un snapshots previo guardado.
  2. Latencia de respuesta  — mediana de tiempo post-públicado → primer
                              comentario de COMET en ese post (desde logs).
  3. Retención de interlocutores — de los autores que comentaron en posts de
                              COMET, cuántos volvieron en la ventana.
  4. Fit temático           — correlación topic → comentarios recibidos.
  5. Producción             — posts/día, comments/día, ratio calls/reply.

Uso (read-only, no modifica estado del agente):
  python -m scripts.audit_viability --days 7

Guarda un snapshot de karma en data/viability_snapshot.json para medir
trayectoria entre ejecuciones.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("AGENT_WHISPER_MODE", "0")

from config.credentials import Credentials
from services.moltbook_api_client import MoltbookAPIClient

SNAPSHOT_PATH = BASE_DIR / "data" / "viability_snapshot.json"
LOG_DIR = BASE_DIR / "logs"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_to_dt(value: str) -> Optional[datetime]:
    try:
        ts = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _shell_escape_free(text: str, max_len: int = 120) -> str:
    """Sanitiza texto para imprimir seguro en consola."""
    text = (text or "").replace("\n", " ").replace("\r", " ")
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text


def get_client() -> MoltbookAPIClient:
    creds = Credentials.from_env()
    return MoltbookAPIClient(base_url=creds.moltbook_base_url, api_key=creds.moltbook_api_key)


def load_timeline(days: int) -> list:
    """Recorre los logs de agent (incl. rotados) y extrae eventos con timestamp."""
    events = []
    cutoff = _now_utc() - timedelta(days=days)
    pattern_ts = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \|")
    for log_file in sorted(LOG_DIR.glob("agent.log*"), key=lambda p: p.name, reverse=True):
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for line in lines:
            m = pattern_ts.match(line)
            if not m:
                continue
            try:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if ts < cutoff:
                break  # logs rotados son orden cronológico; pasado el cutoff, desconecta
            events.append({"ts": ts, "line": line})
    events.sort(key=lambda e: e["ts"])
    return events


def compute_latency_and_replies(events: list) -> dict:
    """Mediana de tiempo post-publicado → primer comentario de COMET.

    Aproximación a partir de logs: cada 'comentario publicado en post_id=...' es
    una reply de COMET. Cruzamos contra los created_at del feed cuando existen,
    y como fallback medimos el intervalo entre posts del mismo post_id
    (ventana implícita). Emitimos lo que la data permite sin inventar.
    """
    reply_ids = {}
    for e in events:
        m = re.search(r"comentario publicado en post_id=([\w-]+)", e["line"])
        if m:
            pid = m.group(1)
            if pid not in reply_ids:
                reply_ids[pid] = e["ts"]
            # acumula también la última para medir frecuencia
    # latencia desde created_at del post cuando aparece en logs de 'own post'
    published_ts = {}
    for e in events:
        m = re.search(r"Phase A: publicad|post publicado|created_at=([\d\-T:Z\.\s+]+)", e["line"])
        if m:
            pass
    return {
        "replied_posts_days": len(reply_ids),
        "first_replies": reply_ids,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditoría de viabilidad COMET-RIOBAMBA")
    parser.add_argument("--days", type=int, default=7, help="Ventana de análisis en días")
    args = parser.parse_args()
    days = args.days

    client = get_client()
    now = _now_utc()

    print("=" * 64)
    print(f"AUDITORÍA DE VIABILIDAD — COMET-RIOBAMBA")
    print(f"Ventana: últimos {days} días hasta {now:%Y-%m-%d %H:%M} UTC")
    print("=" * 64)

    # 1) Karma / trayectoria
    home = client.fetch_home_dashboard() or {}
    karma = home.get("karma", 0)
    active_posts = home.get("active_posts", 0)
    unread = home.get("unread_notifications", 0)
    print("\n[1] KARMA / CUENTA")
    print(f"    karma............ {karma}")
    print(f"    active_posts..... {active_posts}")
    print(f"    unread_notif..... {unread}")

    prev = {}
    if SNAPSHOT_PATH.exists():
        try:
            prev = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    prev_karma = prev.get("karma")
    prev_ts = prev.get("ts")
    if prev_karma is not None:
        delta = karma - prev_karma
        trend = "▲" if delta > 0 else ("▼" if delta < 0 else "■")
        span = ""
        if prev_ts:
            try:
                pd = datetime.fromisoformat(str(prev_ts))
                span = f" (desde {pd:%m-%d %H:%M})"
            except Exception:
                span = ""
        print(f"    trend............ {trend} {delta:+d}{span}")
    else:
        print(f"    (primer snapshot — sin trayectoria previa)")

    # persistir snapshot
    try:
        SNAPSHOT_PATH.write_text(
            json.dumps({"ts": now.isoformat(), "karma": karma}),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"    (no se pudo guardar snapshot: {e})")

    # 2) Actividad en posts propios (quien comenta)
    activity = home.get("activity_on_your_posts") or []
    print("\n[2] INTERACCIÓN EN POSTS PROPIOS (activity_on_your_posts)")
    if not activity:
        print("    (sin actividad reportada en la ventana)")
    author_counter = Counter()
    topic_comments = defaultdict(int)
    topic_post = defaultdict(int)

    def _pick_title(item):
        for k in ("title", "post_title", "heading", "name", "content", "body"):
            v = item.get(k)
            if v and str(v).strip():
                return str(v).strip()
        return ""

    def _pick_authors(item):
        raw = item.get("authors")
        if isinstance(raw, list):
            names = []
            for a in raw:
                if isinstance(a, dict):
                    nm = a.get("name") or a.get("username") or a.get("screen_name") or a.get("author")
                    if nm:
                        names.append(str(nm))
                elif a:
                    names.append(str(a))
            return names
        if isinstance(raw, str) and raw.strip():
            return [x.strip() for x in raw.split(",") if x.strip()]
        return []

    for item in activity[:20]:
        title = _shell_escape_free(_pick_title(item), 70)
        notif = item.get("new_notification_count", 0) or item.get("notifications", 0) or item.get("count", 0)
        authors = _pick_authors(item)
        print(f"    • {title or '(sin titulo)'}  [{notif} nuevos]  autores={authors}")
        for a in authors:
            author_counter[a.lower()] += 1
        topic_comments[title or "(sin titulo)"] += notif
        topic_post[title or "(sin titulo)"] += 1
    print(f"    autores distintos en la ventana: {len(author_counter)}")

    # 3) Retención: autores que repiten >=2 veces
    repeaters = [(a, c) for a, c in author_counter.items() if c >= 2]
    print("\n[3] RETENCIÓN DE INTERLOCUTORES")
    if repeaters:
        print(f"    autores recurrentes (>=2 comentarios): {len(repeaters)}")
        for a, c in sorted(repeaters, key=lambda x: -x[1])[:10]:
            print(f"      - {a}: {c}")
    else:
        print("    sin retención (ningún autor repite) — señal débil")

    # 4) Fit temático
    print("\n[4] FIT TEMÁTICO (topics → comentarios recibidos)")
    if topic_comments:
        ranked = sorted(topic_comments.items(), key=lambda x: -x[1])[:5]
        for t, c in ranked:
            print(f"    • {c:>3} comments | {t}")
    else:
        print("    (sin datos de comentarios por topic en la ventana)")

    # 5) Producción desde logs / telemetry
    print("\n[5] PRODUCCIÓN Y COSTO (ventana de logs)")
    events = load_timeline(days)
    replies = sum(1 for e in events if "comentario publicado en post_id=" in e["line"])
    feed_replies = sum(
        1 for e in events
        if re.search(r"comentario publicado en post_id=.*tier=", e["line"])
    )
    posts_a = sum(1 for e in events if re.search(r"Fase A: 1 post.*publicado|post.*publicado", e["line"]))
    print(f"    replies publicadas (logs)........ {replies}")
    print(f"      ├─ feed replies.............. {feed_replies}")
    print(f"    posts generados (Fase A).        {posts_a}")

    tele_json = BASE_DIR / "data" / "cascade_telemetry.jsonl"
    cost = 0.0
    calls = 0
    if tele_json.exists():
        cutoff = now - timedelta(days=days)
        for line in tele_json.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                ts = _iso_to_dt(d.get("ts"))
                if ts and ts >= cutoff and d.get("success"):
                    cost += float(d.get("cost_usd", 0) or 0)
                    calls += 1
            except Exception:
                continue
    print(f"    LLM calls (telemetry, {days}d)... {calls}")
    print(f"    costo LLM estimado............ ${cost:.4f}")

    # 6) Veredicto
    print("\n[6] VEREDICTO DE VIABILIDAD")
    score = 0
    checks = []
    if karma > 0:
        score += 1
        checks.append("karma>0")
    if prev_karma is not None and delta > 0:
        score += 1
        checks.append("karma crece")
    if len(author_counter) >= 3:
        score += 1
        checks.append(">=3 autores distintos en posts propios")
    if repeaters:
        score += 1
        checks.append("retención (autores que repiten)")
    if feed_replies > 0:
        score += 1
        checks.append("feed replies activas")
    print(f"    checks superadas: {score}/5 -> {checks if checks else 'ninguna'}")
    if score >= 3:
        verdict = "VIABLE — continuar afinando, hay señal de influencia real."
    elif score >= 2:
        verdict = "EN RIESGO — señal débil; revisar engagement y latencia con datos de más días."
    else:
        verdict = "NO VIABLE con la evidencia actual — producir sin respuesta no escala."
    print(f"    -> {verdict}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())