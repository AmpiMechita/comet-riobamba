# -*- coding: utf-8 -*-
"""Balance guard: pausa si saldo DeepSeek <= threshold.

Llamar al final de cada ciclo. Reutiliza check_deepseek_balance().
"""
import logging

from services.deepseek_balance import check_deepseek_balance
from services.pause_controller import add_reason, remove_reason

logger = logging.getLogger("services.balance_guard")

BALANCE_THRESHOLD_USD = 0.05


def check_and_trigger() -> None:
    """Llamar post-ciclo. Anade/quita razon 'balance' segun saldo."""
    balance = check_deepseek_balance()
    if balance is None:
        # No se pudo obtener -> no cambiar estado (fail-safe: si estaba
        # pausado por balance, no se reanuda sin confirmar; si no estaba
        # pausado, no se pausa por error de red)
        logger.debug("balance_guard: no se pudo obtener saldo, sin cambios")
        return

    if balance <= BALANCE_THRESHOLD_USD:
        add_reason("balance", f"${balance:.4f} <= ${BALANCE_THRESHOLD_USD}")
    else:
        remove_reason("balance")