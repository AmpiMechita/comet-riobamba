# -*- coding: utf-8 -*-
"""Quality Governor v0 — gobernador de calidad-por-dolar (observador).

Invention brief (23/08/2026): asignar modelo por tarea segun ROI MEDIDO,
no por intuicion. v0 no enruta nada: observa, detecta modos de fallo
caros y persiste la tabla que el router v1 usara para decidir.

Fuentes (esquemas reales verificados):
  - data/dual_scores.jsonl      {timestamp, phase, type, engagement,
                                 research_value, composite, text_preview}
  - data/cascade_telemetry.jsonl {ts, caller, provider, tier, latency_ms,
                                 success, input_tokens, output_tokens, cost_usd}

Salidas:
  - compute_governor_report()  -> dict agregado por ventana temporal
  - format_governor_line()     -> 1 linea para el cycle summary
  - data/governor_roi.json     -> ultimo reporte (insumo del router v1)

Detecciones v0:
  - Fuga de razonamiento en texto publicado (patron real visto el 23/08:
    una reply publicada empezaba 'Here's a thinking process:' y saco
    composite 0.21).
  - Costo 24h por tier/caller vs calidad media por fase: la base del ROI.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("services.quality_governor")

_DUAL_SCORES_PATH = Path("data/dual_scores.jsonl")
_TELEMETRY_PATH = Path("data/cascade_telemetry.jsonl")
_ROI_STATE_PATH = Path("data/governor_roi.json")

_LOW_QUALITY_COMPOSITE = 0.5

# Patrones conservadores de fuga de razonamiento (calibrados con el caso
# real del 23/08; evitar falsos positivos con prosa legitima tipo 'analyze').
_LEAK_PATTERNS = (
    re.compile(r"here'?s a thinking process", re.IGNORECASE),
    re.compile(r"<think>", re.IGNORECASE),
    re.compile(r"\*\*analyze the request\*\*", re.IGNORECASE),
    re.compile(r"^as an ai (language )?model", re.IGNORECASE),
)


def _parse_ts(raw: Any):
    if not raw:
        return None
    try:
        ts = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _read_jsonl(path: Path, window_hours: float) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    out: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            ts = _parse_ts(rec.get("timestamp") or rec.get("ts"))
            if ts is None or ts < cutoff:
                continue
            rec["_dt"] = ts
            out.append(rec)
    except OSError as e:
        logger.debug("QualityGovernor: no se pudo leer %s: %s", path.name, e)
    return out


def compute_governor_report(window_hours: float = 24.0) -> Dict[str, Any]:
    """Agrega calidad (dual_scores) y costo (telemetria) de la ventana."""
    scores = _read_jsonl(_DUAL_SCORES_PATH, window_hours)
    telemetry = _read_jsonl(_TELEMETRY_PATH, window_hours)

    # ── Calidad por fase ──────────────────────────────────────────
    quality_by_phase: Dict[str, Dict[str, Any]] = {}
    leaks: List[Dict[str, str]] = []
    for rec in scores:
        phase = str(rec.get("phase") or "?").lower()
        comp = rec.get("composite")
        try:
            comp_f = float(comp)
        except (TypeError, ValueError):
            comp_f = None
        bucket = quality_by_phase.setdefault(
            phase,
            {"n": 0, "composite_sum": 0.0, "low_quality": 0},
        )
        bucket["n"] += 1
        if comp_f is not None:
            bucket["composite_sum"] += comp_f
            if comp_f < _LOW_QUALITY_COMPOSITE:
                bucket["low_quality"] += 1
        preview = str(rec.get("text_preview") or "")
        if any(p.search(preview[:400]) for p in _LEAK_PATTERNS):
            leaks.append({
                "phase": phase,
                "ts": rec.get("timestamp", ""),
                "preview": preview[:120],
            })

    for phase, bucket in quality_by_phase.items():
        n = bucket.pop("n")
        total = bucket.pop("composite_sum")
        bucket["avg_composite"] = round(total / n, 3) if n else None
        bucket["n"] = n
        bucket["leaks"] = sum(1 for lk in leaks if lk["phase"] == phase)

    # ── Costo/uso por tier y caller ───────────────────────────────
    cost_by_tier: Dict[str, Dict[str, Any]] = {}
    for rec in telemetry:
        tier = str(rec.get("tier") or "?")
        bucket = cost_by_tier.setdefault(
            tier, {"calls": 0, "ok": 0, "in": 0, "out": 0, "cost_usd": 0.0}
        )
        bucket["calls"] += 1
        if rec.get("success"):
            bucket["ok"] += 1
            bucket["in"] += int(rec.get("input_tokens") or 0)
            bucket["out"] += int(rec.get("output_tokens") or 0)
            try:
                bucket["cost_usd"] += float(rec.get("cost_usd") or 0.0)
            except (TypeError, ValueError):
                pass
    for bucket in cost_by_tier.values():
        bucket["cost_usd"] = round(bucket["cost_usd"], 4)

    # ── Flags ROI accionables ─────────────────────────────────────
    roi_flags: List[str] = []
    for tier, bucket in sorted(cost_by_tier.items(), key=lambda kv: -kv[1]["cost_usd"]):
        if bucket["cost_usd"] > 0 and bucket["ok"] == 0:
            roi_flags.append(f"gasto ${bucket['cost_usd']:.4f} en '{tier}' sin exitos: revisar routing")
    for phase, bucket in quality_by_phase.items():
        if bucket["n"] >= 3 and bucket["low_quality"] / bucket["n"] > 0.5:
            roi_flags.append(
                f"fase {phase}: {bucket['low_quality']}/{bucket['n']} respuestas "
                f"bajo composite {_LOW_QUALITY_COMPOSITE} — subir calidad del generador"
            )
    if leaks:
        roi_flags.append(f"{len(leaks)} fuga(s) de razonamiento publicadas: activar/podar prompt o modelo")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": window_hours,
        "quality_by_phase": quality_by_phase,
        "cost_by_tier": cost_by_tier,
        "leaks": leaks[:5],
        "roi_flags": roi_flags,
    }
    _persist(report)
    return report


def format_governor_line(report: Dict[str, Any]) -> str:
    """Una linea compacta para el cycle summary."""
    parts = []
    for phase in ("a", "b"):
        b = report["quality_by_phase"].get(phase)
        if b and b.get("avg_composite") is not None:
            parts.append(f"{phase}:Q{b['avg_composite']:.2f}(n={b['n']})")
    total_cost = sum(b["cost_usd"] for b in report["cost_by_tier"].values())
    parts.append(f"cost24h=${total_cost:.4f}")
    if report["leaks"]:
        parts.append(f"LEAKS={len(report['leaks'])}")
    flags = len(report["roi_flags"])
    if flags:
        parts.append(f"flags={flags}")
    return "Governor[{}] {}".format(
        f"{report['window_hours']:.0f}h", " ".join(parts) or "sin datos"
    )


def _persist(report: Dict[str, Any]) -> None:
    try:
        _ROI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ROI_STATE_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        logger.debug("QualityGovernor: persistencia fallida: %s", e)


def get_roi_state() -> Dict[str, Any]:
    """Ultimo reporte persistido (insumo futuro del router v1)."""
    try:
        if _ROI_STATE_PATH.exists():
            return json.loads(_ROI_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {}
