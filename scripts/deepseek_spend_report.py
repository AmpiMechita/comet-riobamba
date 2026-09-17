#!/usr/bin/env python3
"""Reporte de spend DeepSeek - consulta estatus actual y alertas proactivas.

Muestra el gasto diario actual, el límite configurado, el remainder y el nivel
de alerta (low/medium/high/none) basado en los umbrales definidos en .env.

Uso:
    python scripts/deepseek_spend_report.py

Salida de ejemplo:
    === DeepSeek Spend Status ===
    Daily spend: $0.125000
    Daily limit: $0.500000
    Remaining: $0.375000
    Alert level: low
    Last reset: 2026-08-26
    Cycles since reset: 0
    Alerts triggered: low

    Opcional: usarse como script de monitoreo en CI/operator dashboards.
"""

import sys
from pathlib import Path

# Asegurar que el path del proyecto esté en sys.path
import os
project_root = Path(r"C:\comet-riobamba-v31")
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from services.model_cascade import get_spend_status


def main():
    status = get_spend_status()

    print("=== DeepSeek Spend Status ===")
    print(f"Daily spend: ${status['daily_spend_usd']:.6f}")
    print(f"Daily limit: ${status['daily_spend_limit_usd']:.6f}")
    print(f"Remaining: ${status['remaining_usd']:.6f}")
    print(f"Alert level: {status['alert_level']}")
    if status["alerts_triggered"]:
        print(f"Alerts triggered: {', '.join(status['alerts_triggered'])}")
    else:
        print("Alerts triggered: none")
    print(f"Last reset: {status['last_reset_date']}")
    print(f"Cycles since reset: {status['cycles_since_reset']}")

    # Return code based on alert level for CI/automation
    if status["alert_level"] == "high":
        print("\n⚠️  HIGH ALERT: Spend approaching daily limit!")
        sys.exit(1)
    elif status["alert_level"] == "medium":
        print("\n⚠️  MEDIUM ALERT: Spend at 80% of daily limit")
        sys.exit(0)
    elif status["alert_level"] == "low":
        print("\nℹ️  LOW ALERT: Spend at 50% of daily limit")
        sys.exit(0)
    else:
        print("\n✅  OK: Spend within normal limits")
        sys.exit(0)


if __name__ == "__main__":
    main()