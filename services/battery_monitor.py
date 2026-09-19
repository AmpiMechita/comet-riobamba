# -*- coding: utf-8 -*-
"""Monitor de bateria (thread daemon).

Polling cada 30s. Lee WMI Win32_Battery.
- AC desconectado (BatteryStatus=1) -> add_reason("battery", ...)
- AC conectado (BatteryStatus=2) -> remove_reason("battery")
- Bateria <=15% -> add_reason("battery", "battery low")

Disenado para hardware con autonomia minima (~5 min). No fuerza kill.
"""
import json
import logging
import subprocess
import threading
import time
from typing import Dict, Optional

from services.pause_controller import add_reason, remove_reason

logger = logging.getLogger("services.battery_monitor")

POLL_INTERVAL_SECONDS = 30
BATTERY_LOW_PCT = 15
BATTERY_RESUME_PCT = 25


def _read_battery_state() -> Optional[Dict]:
    ps_cmd = (
        "Get-CimInstance -ClassName Win32_Battery | "
        "Select-Object EstimatedChargeRemaining, BatteryStatus | "
        "ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        data = json.loads(result.stdout.strip())
        if isinstance(data, list):
            data = data[0] if data else None
        return data
    except Exception as e:
        logger.debug("battery_monitor: error leyendo WMI: %s", e)
        return None


def _monitor_loop() -> None:
    logger.info("battery_monitor: iniciado (poll=%ss, low=%s%%, resume=%s%%)",
                POLL_INTERVAL_SECONDS, BATTERY_LOW_PCT, BATTERY_RESUME_PCT)
    while True:
        try:
            state = _read_battery_state()
            if state is None:
                # Desktop o sin bateria
                pass
            else:
                status = state.get("BatteryStatus")
                charge = state.get("EstimatedChargeRemaining")
                # 1 = descargando, 2 = AC conectado
                if status == 1:
                    add_reason("battery", f"AC desconectado ({charge}%)")
                elif status == 2 and charge is not None:
                    charge_int = int(charge)
                    if charge_int <= BATTERY_LOW_PCT:
                        add_reason("battery", f"bateria {charge_int}%")
                    elif charge_int >= BATTERY_RESUME_PCT:
                        # AC conectado Y carga suficiente -> reanudar
                        remove_reason("battery")
                    # Si esta entre LOW y RESUME, mantener estado actual
        except Exception as e:
            logger.warning("battery_monitor: error en ciclo: %s", e)
        time.sleep(POLL_INTERVAL_SECONDS)


def start_battery_monitor() -> threading.Thread:
    """Arranca el monitor como thread daemon."""
    t = threading.Thread(target=_monitor_loop, name="battery-monitor", daemon=True)
    t.start()
    return t

