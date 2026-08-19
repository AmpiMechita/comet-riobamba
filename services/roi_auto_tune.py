# -*- coding: utf-8 -*-
"""Auto-tuning semanal de umbrales de Phase B basado en retorno real (ledger).

Cierra el loop de auto-mejora: en lugar de solo medir el retorno por canal
(scripts/comment_roi_report.py), este modulo calcula y aplica ajustes ACOTADOS
de los umbrales a partir de los upvotes reales del ledger
(data/comment_votes.jsonl).

Palancas ajustables (siempre con guardrails, nunca al vuelo):
  - feed_budget_pct : % del presupuesto diario para posts ajenos (feed) vs
                      posts propios. Si el canal feed (watchlist/historial)
                      produce retorno, se sube (acotado); si no, se baja.
  - min_value       : piso de valor para la cola de posts propios. Si los
                      comentarios de score bajo nunca ganan upvotes, se sube
                      el piso (acotado) para filtrar carga.

Guardrails (obligatorios):
  - Muestra minima por canal (MIN_REASON_SAMPLE) antes de calcular: evita
    ajustar por ruido estadistico.
  - Paso acotado (STEP_*) y clamps de piso/techo: nunca salta a un extremo.
  - Solo ajusta si el retorno difiere por un ratio minimo (ROI_RATIO_THRESHOLD).
  - Respeto a config explicita: si .env define el valor, el tuning NO lo pisa
    (las funciones get_* devuelven el .env por encima del tuning).

Cadencia: semanal (ROI_TUNE_CADENCE_DAYS, default 7). La ultima corrida se
persiste en data/roi_tuning.json.

Uso: python -m services.roi_auto_tune [--apply] [--force]
  - sin flags : analiza y muestra la recomendacion (dry-run, no escribe).
  - --apply    : persiste el ajuste (sujeto a cadencia).
  - --force    : ignora la cadencia.
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("services.roi_auto_tune")

# ── Rutas (sobrescribibles en tests via parametros path=...) ───────
_VOTES_PATH = Path("data/comment_votes.jsonl")
_TUNING_PATH = Path("data/roi_tuning.json")
_HISTORY_PATH = Path("data/roi_tuning_history.jsonl")

# ── Guardrails ─────────────────────────────────────────────────────
_TUNING_CADENCE_DAYS = int(os.getenv("ROI_TUNE_CADENCE_DAYS", "7"))
MIN_REASON_SAMPLE = int(os.getenv("ROI_TUNE_MIN_SAMPLE", "5"))
ROI_RATIO_THRESHOLD = float(os.getenv("ROI_TUNE_RATIO", "1.5"))
_STEP_FEED_PCT = float(os.getenv("ROI_TUNE_STEP_FEED", "5"))
_FEED_PCT_FLOOR = float(os.getenv("ROI_TUNE_FEED_FLOOR", "10"))
_FEED_PCT_CEIL = float(os.getenv("ROI_TUNE_FEED_CEIL", "50"))
_STEP_MIN_VALUE = float(os.getenv("ROI_TUNE_STEP_MIN_VALUE", "0.1"))
_MIN_VALUE_FLOOR = float(os.getenv("ROI_TUNE_MIN_VALUE_FLOOR", "0.0"))
_MIN_VALUE_CEIL = float(os.getenv("ROI_TUNE_MIN_VALUE_CEIL", "0.5"))

# Canales que corresponden a replies en posts ajenos (feed reactivo).
_FEED_REASONS = ("watchlist", "historial")


def _load_votes(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Lee el ledger de votos por comentario. Devuelve solo los que ya tienen
    upvotes refrescado (upvotes is not None)."""
    path = path or _VOTES_PATH
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if isinstance(rec, dict) and rec.get("upvotes") is not None:
                records.append(rec)
    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning("roi_auto_tune: no se pudo leer %s: %s", path, e)
    return records


def analyze_roi(path: Optional[Path] = None) -> Dict[str, Any]:
    """Retorno (upvotes/comentario) por canal y por rango de score.

    Devuelve {'reasons': {...}, 'scores': {...}, 'total_checked': int} donde
    cada entrada es {'n': int, 'upvotes': int, 'roi': float}."""
    records = _load_votes(path)
    out: Dict[str, Any] = {"reasons": {}, "scores": {}, "total_checked": len(records)}
    if not records:
        return out

    by_reason: Dict[str, List[Dict]] = {}
    by_score: Dict[str, List[Dict]] = {}
    for r in records:
        reason = r.get("reason") or "valor"
        by_reason.setdefault(reason, []).append(r)
        s = float(r.get("value_score") or 0.0)
        bucket = "<=0.3" if s <= 0.3 else "0.31-0.5" if s <= 0.5 else "0.51-0.7" if s <= 0.7 else ">0.7"
        by_score.setdefault(bucket, []).append(r)

    for reason, items in by_reason.items():
        n = len(items)
        up = sum(int(i.get("upvotes") or 0) for i in items)
        out["reasons"][reason] = {"n": n, "upvotes": up, "roi": up / n if n else 0.0}
    for bucket, items in by_score.items():
        n = len(items)
        up = sum(int(i.get("upvotes") or 0) for i in items)
        out["scores"][bucket] = {"n": n, "upvotes": up, "roi": up / n if n else 0.0}
    return out


def _env_float(name: str, default: float) -> float:
    """Lee una var de entorno como float; cadena vacia o invalida => default."""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _current_settings() -> Dict[str, float]:
    """Config actual: feed_budget_pct + min_value (desde .env o default)."""
    feed = _env_float("AGENT_FEED_BUDGET_PCT", 15.0)
    min_value = _env_float("AGENT_MIN_REPLY_VALUE_SCORE", 0.0)
    return {"feed_budget_pct": feed, "min_value": min_value}


def recommend_tuning(roi: Dict[str, Any],
                     current: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Recomendaciones acotadas. Devuelve {'changes': [...], 'proposed': {...}}."""
    current = current or _current_settings()
    changes: List[Dict[str, str]] = []
    proposed = {
        "feed_budget_pct": current["feed_budget_pct"],
        "min_value": current["min_value"],
    }

    # ── 1. feed_budget_pct: canal feed vs posts propios ───────────
    reasons = roi.get("reasons", {})
    feed_n = sum(v["n"] for k, v in reasons.items() if k in _FEED_REASONS)
    own_n = sum(v["n"] for k, v in reasons.items() if k not in _FEED_REASONS)
    if feed_n >= MIN_REASON_SAMPLE and own_n >= MIN_REASON_SAMPLE:
        feed_up = sum(v["upvotes"] for k, v in reasons.items() if k in _FEED_REASONS)
        own_up = sum(v["upvotes"] for k, v in reasons.items() if k not in _FEED_REASONS)
        feed_roi = feed_up / feed_n
        own_roi = own_up / own_n
        if feed_roi > own_roi * ROI_RATIO_THRESHOLD:
            new_val = min(current["feed_budget_pct"] + _STEP_FEED_PCT, _FEED_PCT_CEIL)
            proposed["feed_budget_pct"] = new_val
            changes.append({
                "param": "feed_budget_pct", "from": f"{current['feed_budget_pct']:.0f}%",
                "to": f"{new_val:.0f}%",
                "why": f"feed roi={feed_roi:.2f} > own roi={own_roi:.2f} (x{ROI_RATIO_THRESHOLD:.1f})",
            })
        elif own_roi > feed_roi * ROI_RATIO_THRESHOLD:
            new_val = max(current["feed_budget_pct"] - _STEP_FEED_PCT, _FEED_PCT_FLOOR)
            proposed["feed_budget_pct"] = new_val
            changes.append({
                "param": "feed_budget_pct", "from": f"{current['feed_budget_pct']:.0f}%",
                "to": f"{new_val:.0f}%",
                "why": f"own roi={own_roi:.2f} > feed roi={feed_roi:.2f} (x{ROI_RATIO_THRESHOLD:.1f})",
            })

    # ── 2. min_value: score bajo sin retorno sube el piso ─────────
    low = roi.get("scores", {}).get("<=0.3")
    if low and low["n"] >= MIN_REASON_SAMPLE and low["roi"] == 0.0:
        new_val = min(current["min_value"] + _STEP_MIN_VALUE, _MIN_VALUE_CEIL)
        if new_val != current["min_value"]:
            proposed["min_value"] = new_val
            changes.append({
                "param": "min_value", "from": f"{current['min_value']:.2f}",
                "to": f"{new_val:.2f}",
                "why": f"score <=0.3 n={low['n']} upvotes=0",
            })

    return {"changes": changes, "proposed": proposed}


def _load_tuning(path: Optional[Path] = None) -> Dict[str, Any]:
    path = path or _TUNING_PATH
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning("roi_auto_tune: no se pudo leer %s: %s", path, e)
        return {}


def _save_tuning(data: Dict[str, Any], path: Optional[Path] = None) -> None:
    path = path or _TUNING_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("roi_auto_tune: no se pudo escribir %s: %s", path, e)


def _append_history(entry: Dict[str, Any], path: Optional[Path] = None) -> None:
    path = path or _HISTORY_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning("roi_auto_tune: no se pudo escribir historial %s: %s", path, e)


def should_run(tuning: Optional[Dict[str, Any]] = None, now=None) -> bool:
    """True si toca correr (cadencia semanal vencida) o nunca se corrio."""
    tuning = tuning if tuning is not None else _load_tuning()
    last = tuning.get("last_run")
    if not last:
        return True
    now = now or datetime.now(timezone.utc)
    try:
        last_dt = datetime.fromisoformat(str(last))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        return (now - last_dt).total_seconds() >= _TUNING_CADENCE_DAYS * 86400
    except ValueError:
        return True


def apply_tuning(*, force: bool = False, path: Optional[Path] = None,
                 history_path: Optional[Path] = None,
                 votes_path: Optional[Path] = None,
                 dry_run: bool = False) -> Dict[str, Any]:
    """Corre el auto-tune. Salvo force/dry_run, persiste el ajuste (si procede)."""
    tuning = _load_tuning(path)
    if not force and not dry_run and not should_run(tuning):
        return {"ran": False, "reason": "cadence_not_due", "changes": []}

    roi = analyze_roi(votes_path)
    rec = recommend_tuning(roi)
    result: Dict[str, Any] = {
        "ran": True,
        "changes": rec["changes"],
        "recommendation": {"roi": roi, "proposed": rec["proposed"]},
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    if dry_run:
        result["dry_run"] = True
        return result

    tuning["last_run"] = result["ts"]
    if rec["changes"]:
        tuning["applied"] = rec["proposed"]
        tuning["last_changes"] = rec["changes"]
    _save_tuning(tuning, path)
    _append_history({
        "ts": result["ts"],
        "changes": rec["changes"],
        "proposed": rec["proposed"],
    }, history_path)
    result["applied"] = rec["proposed"] if rec["changes"] else None
    return result


def get_feed_budget_pct(default_pct: float = 15.0, path: Optional[Path] = None) -> float:
    """Valor efectivo para Phase B. El .env explicito manda; si no hay .env,
    usa el tuning aplicado; si no hay tuning, el default."""
    env = _env_float("AGENT_FEED_BUDGET_PCT", None) if os.getenv("AGENT_FEED_BUDGET_PCT") else None
    if env is not None:
        return env
    tuning = _load_tuning(path)
    applied = tuning.get("applied") or {}
    return float(applied.get("feed_budget_pct", default_pct))


def get_min_value(default_min: float = 0.0, path: Optional[Path] = None) -> float:
    """Valor efectivo del piso de valor. El .env explicito manda."""
    if os.getenv("AGENT_MIN_REPLY_VALUE_SCORE"):
        return _env_float("AGENT_MIN_REPLY_VALUE_SCORE", default_min)
    tuning = _load_tuning(path)
    applied = tuning.get("applied") or {}
    return float(applied.get("min_value", default_min))


# ── Canal con ROI medido (gate de critica) ─────────────────────────
# La critica (writer + critic) se dispara para watchlist SIEMPRE y, de forma
# data-driven, para cualquier canal cuyo retorno real (upvotes/comentario)
# supere un umbral con muestra suficiente. Asi el override pasa de regla
# estatica a decision basada en datos.
CRITIQUE_CHANNEL_ROI_MIN = float(os.getenv("CRITIQUE_CHANNEL_ROI_MIN", "0.2"))


def get_channel_roi(reason: str, min_sample: int = MIN_REASON_SAMPLE,
                    path: Optional[Path] = None) -> Optional[float]:
    """ROI (upvotes/comentario) de un canal, o None si muestra insuficiente."""
    roi = analyze_roi(path)
    rec = roi.get("reasons", {}).get(reason)
    if not rec or rec["n"] < min_sample:
        return None
    return float(rec["roi"])


def channels_with_roi(min_sample: int = MIN_REASON_SAMPLE,
                      min_roi: float = CRITIQUE_CHANNEL_ROI_MIN,
                      path: Optional[Path] = None) -> Dict[str, float]:
    """Dict {canal: roi} para canales con ROI medido >= min_roi y muestra."""
    roi = analyze_roi(path)
    out: Dict[str, float] = {}
    for reason, rec in roi.get("reasons", {}).items():
        if rec["n"] >= min_sample and rec["roi"] >= min_roi:
            out[reason] = float(rec["roi"])
    return out


def _print_report(rec: Dict[str, Any], roi: Dict[str, Any]) -> None:
    print(f"comentarios con retorno: {roi.get('total_checked', 0)}")
    reasons = roi.get("reasons", {})
    for r in ("watchlist", "historial", "primera_interaccion", "valor"):
        m = reasons.get(r)
        if m:
            print(f"  {r:20s} n={m['n']:3d} upvotes={m['upvotes']:2d} roi={m['roi']:.2f}")
    print("\n== AJUSTES PROPUESTOS ==")
    if not rec["changes"]:
        print("  (ninguno: la muestra o el ratio no justifican ajuste)")
    for c in rec["changes"]:
        print(f"  {c['param']:16s} {c['from']} -> {c['to']}  ({c['why']})")


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)  # para reflejar la config real de .env
    except Exception:
        pass
    apply = "--apply" in argv
    force = "--force" in argv
    roi = analyze_roi()
    rec = recommend_tuning(roi)
    _print_report(rec, roi)
    if apply:
        res = apply_tuning(force=force)
        if not res.get("ran"):
            print("\n(cadencia semanal no vencida; usa --force para forzar)")
        elif res.get("changes"):
            print(f"\nAplicado: {res.get('applied')}")
        else:
            print("\nSin cambios aplicados (no procedia).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())