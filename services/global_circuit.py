# -*- coding: utf-8 -*-
"""
COMET-RIOBAMBA v4.3 - Circuit breaker global + intervalo dinámico

Wrapper delgado sobre CircuitBreaker canónico (utils/resilience.py)
con persistencia SQLite para state global del agente.

Módulo funcional (no clase) para mantener API actual:
    should_skip_cycle()
    register_cycle_result()
    get_current_interval()
    manual_reset()
    get_debug_state()
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from services.persistence import get_flag, set_flag
from utils.resilience import CircuitBreaker, SQLiteCircuitPersistence

logger = logging.getLogger("services.global_circuit")

# Umbrales del circuito global
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_RECOVERY_TIMEOUT_SECONDS = 15 * 60
DEFAULT_SUCCESS_THRESHOLD = 2

# Intervalo dinámico
DEFAULT_MIN_INTERVAL_SECONDS = 30 * 60
DEFAULT_MAX_INTERVAL_SECONDS = 8 * 60 * 60
INTERVAL_STEP_FACTOR = 1.5

# Instancia singleton del breaker global
_breaker: Optional[CircuitBreaker] = None


def _get_breaker() -> CircuitBreaker:
    global _breaker
    if _breaker is None:
        _breaker = CircuitBreaker(
            name="global_circuit",
            failure_threshold=DEFAULT_FAILURE_THRESHOLD,
            recovery_timeout=DEFAULT_RECOVERY_TIMEOUT_SECONDS,
            success_threshold=DEFAULT_SUCCESS_THRESHOLD,
            persistence=SQLiteCircuitPersistence(),
        )
    return _breaker


# ============================================================
# API pública — Circuit breaker global
# ============================================================


def should_skip_cycle(
    recovery_timeout_seconds: int = DEFAULT_RECOVERY_TIMEOUT_SECONDS,
) -> Tuple[bool, Optional[str]]:
    """
    Indica si el ciclo debería omitirse por estar el circuito global abierto.
    """
    breaker = _get_breaker()
    if breaker.can_execute():
        return False, None

    stats = breaker.get_stats()
    return True, stats.get("last_error") or "global_circuit_open"


def register_cycle_result(
    *,
    error: Optional[str],
    had_activity: bool,
    base_interval_seconds: int,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    success_threshold: int = DEFAULT_SUCCESS_THRESHOLD,
    min_interval_seconds: Optional[int] = None,
    max_interval_seconds: Optional[int] = None,
) -> int:
    """
    Registra el resultado de un ciclo y actualiza:
    - Estado del circuit breaker global (open/closed) via CircuitBreaker canónico.
    - Intervalo de ciclo dinámico (backoff 1.5x).

    Un ciclo sin actividad (had_activity=False) cuenta como "bad cycle"
    para el backoff incluso si no hubo excepción.  Esto evita que
    fallos internos de Phase A (Ollama caído, etc.) pasen desapercibidos.
    """
    breaker = _get_breaker()

    if error:
        breaker.record_failure()
    else:
        breaker.record_success()

    # --- Intervalo dinámico ---
    ctl = _load_cycle_control()
    cur_interval = ctl["current_interval_seconds"] or base_interval_seconds

    # El mínimo nunca puede ser menor que base_interval_seconds
    min_i = (
        int(min_interval_seconds)
        if min_interval_seconds is not None
        else base_interval_seconds
    )
    max_i = (
        int(max_interval_seconds)
        if max_interval_seconds is not None
        else max(base_interval_seconds, DEFAULT_MAX_INTERVAL_SECONDS)
    )

    # Track consecutivos sin actividad (incluye errores y fases A/B vacías)
    consecutive_bad = ctl.get("consecutive_bad_cycles", 0)
    had_positive_outcome = error is None and had_activity

    if had_positive_outcome:
        consecutive_bad = 0
    else:
        consecutive_bad += 1

    trigger_backoff = error is not None or consecutive_bad >= 2

    if trigger_backoff:
        new_interval = int(min(cur_interval * INTERVAL_STEP_FACTOR, max_i))
        reason = "error en ciclo" if error else f"ciclo sin actividad ({consecutive_bad} consecutivos)"
        logger.warning(
            "GlobalCircuit: %s -> aumentando intervalo de %ds a %ds.",
            reason, cur_interval, new_interval,
        )
    else:
        if cur_interval > base_interval_seconds:
            new_interval = int(max(cur_interval / INTERVAL_STEP_FACTOR, base_interval_seconds))
            logger.info(
                "GlobalCircuit: ciclo exitoso -> reduciendo intervalo de %ds a %ds.",
                cur_interval, new_interval,
            )
        else:
            new_interval = base_interval_seconds

    ctl["current_interval_seconds"] = new_interval
    ctl["min_interval_seconds"] = min_i
    ctl["max_interval_seconds"] = max_i
    ctl["consecutive_bad_cycles"] = consecutive_bad
    _save_cycle_control(ctl)

    return new_interval


# ============================================================
# Intervalo dinámico (cycle_control)
# ============================================================


def _load_cycle_control() -> Dict[str, Any]:
    flag = get_flag("cycle_control") or {}
    return {
        "current_interval_seconds": int(flag.get("current_interval_seconds", 0)),
        "min_interval_seconds": int(flag.get("min_interval_seconds", 0)),
        "max_interval_seconds": int(flag.get("max_interval_seconds", 0)),
    }


def _save_cycle_control(state: Dict[str, Any]) -> None:
    set_flag("cycle_control", state)


def get_current_interval(default_interval_seconds: int) -> int:
    """
    Devuelve el intervalo de ciclo actual usando el valor persistido
    en cycle_control, con límites mínimo/máximo.

    El mínimo nunca puede ser menor que default_interval_seconds.
    """
    ctl = _load_cycle_control()
    if ctl["current_interval_seconds"] <= 0:
        ctl["current_interval_seconds"] = int(default_interval_seconds)

    # El mínimo respeta el intervalo base configurado
    min_i = ctl["min_interval_seconds"] or default_interval_seconds
    max_i = ctl["max_interval_seconds"] or max(
        default_interval_seconds, DEFAULT_MAX_INTERVAL_SECONDS
    )

    val = ctl["current_interval_seconds"]
    val = max(min_i, min(val, max_i))

    ctl["current_interval_seconds"] = val
    ctl["min_interval_seconds"] = min_i
    ctl["max_interval_seconds"] = max_i
    _save_cycle_control(ctl)

    return val


# ============================================================
# Helpers administrativos
# ============================================================


def manual_reset(reason: str = "manual_reset") -> None:
    """Reset manual del circuito."""
    _get_breaker().reset()
    logger.info("GlobalCircuit: reset manual realizado. Motivo: %s", reason)


def get_debug_state() -> Dict[str, Any]:
    """Snapshot combinado del circuito global y control de ciclo."""
    breaker = _get_breaker()
    gc = breaker.get_stats()
    cc = _load_cycle_control()
    return {
        "global_circuit": gc,
        "cycle_control": cc,
    }
