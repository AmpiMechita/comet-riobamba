# -*- coding: utf-8 -*-
"""Tests del subsistema de pausa y balance rechecker.

Regresion P-131 (2026-09-30 p134): deadlock balance_guard.
El agente se pausaba por balance y nunca ejecutaba check_and_trigger
porque el pause-check hacia `continue` antes del post-ciclo. Fix:
(a) Capa 1: check_and_trigger() antes del pause-check en agent.py.
(b) Capa 2: recheckers registrables + thread daemon en pause_controller.
"""
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ?? Capa 2: recheckers registrables en pause_controller ??????

def test_register_rechecker_clears_reason_when_true():
    """Un rechecker que devuelve True debe limpiar su razon."""
    import services.pause_controller as pc
    pc.add_reason("balance", "test")
    assert pc.is_paused() is True
    pc.register_rechecker("balance", lambda: True)
    pc.run_recheckers()
    assert "balance" not in pc.get_reasons()
    assert pc.is_paused() is False

def test_register_rechecker_keeps_reason_when_false():
    """Un rechecker que devuelve False NO debe limpiar su razon."""
    import services.pause_controller as pc
    pc.add_reason("balance", "test")
    pc.register_rechecker("balance", lambda: False)
    pc.run_recheckers()
    assert "balance" in pc.get_reasons()

def test_run_recheckers_skips_inactive_reasons():
    """Rechecker de una razon NO activa no debe ejecutarse."""
    import services.pause_controller as pc
    calls = []
    pc.register_rechecker("balance", lambda: calls.append(1) or False)
    pc.run_recheckers()  # sin razon activa
    assert calls == []


# ?? Capa 1: invariante de orden en agent.py ??????????????????

def test_agent_loop_calls_balance_guard_before_pause_check():
    """El re-verificador DEBE correr antes del pause-check.

    Regresion P-131: si check_and_trigger() va despues del
    `if pause_ctl.is_paused(): continue`, el agente pausado por
    balance nunca llega a ejecutarlo -> deadlock.
    """
    src = (Path(__file__).parent.parent / "core" / "agent.py").read_text(encoding="utf-8")
    i_guard = src.find("check_and_trigger()")
    i_pause = src.find("pause_ctl.is_paused()")
    assert i_guard != -1, "check_and_trigger() no encontrado en agent.py"
    assert i_pause != -1, "pause_ctl.is_paused() no encontrado en agent.py"
    assert i_guard < i_pause, (
        f"check_and_trigger() (off={i_guard}) debe aparecer ANTES "
        f"que pause_ctl.is_paused() (off={i_pause}) en agent.py"
    )

# ?? Integracion: balance_guard registra su rechecker ??????????

def test_balance_guard_registers_rechecker_on_import():
    """Al importar balance_guard, debe registrar rechecker de balance."""
    import services.pause_controller as pc
    import services.balance_guard as bg
    importlib.reload(bg)
    # Forzar registro (por si fue antes de crear _recheckers)
    assert "balance" in pc._recheckers, (
        "balance_guard no registro rechecker para balance"
    )
