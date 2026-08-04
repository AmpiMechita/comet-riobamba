# -*- coding: utf-8 -*-
"""
Auto-applier for structured self-improvement proposals (config-only).

Solo se autoaplican parámetros de la ALLOWLIST, con bounds seguros, clamp,
cooldown anti-loop y log auditable. La aplicación es doble:

1. Muta `behavior_cfg` en memoria (efecto inmediato en lecturas .get()).
2. Persiste un overlay en data/auto_applied_config.json que config.py mergea
   al arranque (efecto permanente entre reinicios).

Nunca toca código fuente: si el LLM propone algo fuera de la allowlist, la
propuesta se registra como 'rejected' y se deja para revisión humana.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("services.proposal_applier")

BASE_DIR = Path(__file__).resolve().parent.parent
OVERLAY_PATH = BASE_DIR / "data" / "auto_applied_config.json"
APPLY_LOG_PATH = BASE_DIR / "data" / "proposal_apply_log.jsonl"

from config.auto_appliable import ALLOWLIST

# Cooldown por parametro: no reaplicar cambios al mismo parametro antes de
# N segundos (evita loops de oscilacion entre valores).
COOLDOWN_SECONDS = int(os.getenv("AGENT_PROPOSAL_COOLDOWN_SECONDS", 86400))
# Cambio minimo relativo para considerar la aplicacion (evita churn inutil).
MIN_DELTA_FRACTION = 0.1


def load_overlay() -> Dict[str, Any]:
    """Lee el overlay persistido (param -> valor aplicado)."""
    if not OVERLAY_PATH.exists():
        return {}
    try:
        return json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("ProposalApplier: overlay corrupto (%s), reseteando", e)
        return {}


def _save_overlay(overlay: Dict[str, Any]) -> None:
    OVERLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERLAY_PATH.write_text(
        json.dumps(overlay, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _append_apply_log(entry: Dict[str, Any]) -> None:
    APPLY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(str(APPLY_LOG_PATH), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _read_apply_log() -> list:
    if not APPLY_LOG_PATH.exists():
        return []
    entries = []
    for line in APPLY_LOG_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line.strip()))
            except (json.JSONDecodeError, ValueError):
                continue
    return entries


def _last_change_time(param: str) -> Optional[float]:
    for e in reversed(_read_apply_log()):
        if e.get("param") == param and e.get("status") == "applied":
            return e.get("ts")
    return None


def _clamp(value: Any, lo: int, hi: int, default: int) -> Optional[int]:
    try:
        val = int(value)
    except (ValueError, TypeError):
        return None
    return max(lo, min(hi, val))


def apply_structured_proposal(proposal: Dict[str, Any], behavior_cfg: Dict) -> Dict:
    """Intenta autoaplicar una propuesta estructurada {param, suggested, reason}.

    Devuelve el resultado:
      {"status": "applied"|"rejected"|"skipped_cooldown"|"skipped_noop",
       "param": ..., "previous": ..., "applied": ..., "reason": ...}
    """
    param = str(proposal.get("param", "")).strip()
    suggested = proposal.get("suggested")
    reason = str(proposal.get("reason", ""))[:200]

    if param not in ALLOWLIST:
        result = {"status": "rejected", "param": param, "reason": "param_not_in_allowlist"}
        _append_apply_log({**result, "ts": time.time(), "suggested": suggested,
                           "detail": reason})
        logger.warning("ProposalApplier: rechazada '%s' (no en allowlist): %s",
                       param, reason)
        return result

    lo, hi, default = ALLOWLIST[param]
    new_val = _clamp(suggested, lo, hi, default)
    if new_val is None:
        result = {"status": "rejected", "param": param,
                  "reason": "invalid_suggested_value"}
        _append_apply_log({**result, "ts": time.time(), "suggested": suggested})
        return result

    current = behavior_cfg.get(param, default)

    # Anti-loop: cooldown por parametro
    last = _last_change_time(param)
    if last and (time.time() - last) < COOLDOWN_SECONDS:
        remaining_h = (COOLDOWN_SECONDS - (time.time() - last)) / 3600
        result = {"status": "skipped_cooldown", "param": param,
                  "previous": current, "applied": current,
                  "reason": f"cooldown {remaining_h:.1f}h restante"}
        logger.info("ProposalApplier: skip %s (cooldown, %s)", param, result["reason"])
        return result

    # No-op si el cambio es irrelevante
    if current and abs(new_val - current) / abs(current) < MIN_DELTA_FRACTION \
            and new_val != current:
        result = {"status": "skipped_noop", "param": param,
                  "previous": current, "applied": current,
                  "reason": "delta por debajo del minimo"}
        return result

    # Aplicar: memoria + overlay persistente
    overlay = load_overlay()
    behavior_cfg[param] = new_val
    overlay[param] = new_val
    _save_overlay(overlay)

    result = {
        "status": "applied",
        "param": param,
        "previous": current,
        "applied": new_val,
        "reason": reason,
        "ts": time.time(),
    }
    _append_apply_log(result)
    logger.info("ProposalApplier: APLICADA %s=%s (era %s) — %s",
                param, new_val, current, reason)
    return result


def merge_overlay_into(behavior_cfg: Dict) -> Dict:
    """Mergea el overlay persistido al arranque (config.py). Clamp + skip invalidos."""
    overlay = load_overlay()
    for param, value in overlay.items():
        if param not in ALLOWLIST:
            continue
        lo, hi, default = ALLOWLIST[param]
        val = _clamp(value, lo, hi, default)
        if val is not None:
            behavior_cfg[param] = val
            logger.info("ProposalApplier: overlay aplicado en arranque %s=%s", param, val)
    return behavior_cfg
