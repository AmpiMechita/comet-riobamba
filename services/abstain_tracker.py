# -*- coding: utf-8 -*-
"""
Abstain tracker: vigilancia de la tasa de abstencion diaria.

El ABSTAIN es salida legitima (el agente no debe inventar mecanismos que no
puede fundamentar), pero una tasa alta sostenida es senal de que el targeting
esta mandando temas fuera del alcance real del agente, no de que el modelo
falle. Alerta al superar ~30% de los intentos en un dia (UTC), una sola vez
por dia (no spamea).

Uso: llamar record_abstain(abstained) en cada intento de generacion (Phase A
y Phase B). Persistencia por dia en data/abstain_rate_today.json.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("services.abstain_tracker")

ABSTAIN_RATE_PATH = Path("data/abstain_rate_today.json")
ABSTAIN_ALERT_THRESHOLD = 0.30


def _load_today() -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    if ABSTAIN_RATE_PATH.exists():
        try:
            data = json.loads(ABSTAIN_RATE_PATH.read_text(encoding="utf-8"))
            if data.get("date") == today and isinstance(data.get("abstained"), int):
                return data
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    return {"date": today, "abstained": 0, "attempts": 0, "alerted": False}


def _save_today(data: dict) -> None:
    try:
        ABSTAIN_RATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = ABSTAIN_RATE_PATH.with_name(ABSTAIN_RATE_PATH.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, ABSTAIN_RATE_PATH)
    except OSError as e:
        logger.warning("abstain_tracker: no se pudo persistir tasa diaria: %s", e)


def record_abstain(abstained: bool) -> Optional[float]:
    """Registra un intento de generacion (y si fue abstencion).

    Devuelve la tasa del dia si esta supera el umbral (alerta), None si no.
    La alerta se loguea una sola vez por dia.
    """
    try:
        data = _load_today()
        data["attempts"] += 1
        if abstained:
            data["abstained"] += 1
        _save_today(data)
        rate = data["abstained"] / data["attempts"] if data["attempts"] else 0.0
        if rate > ABSTAIN_ALERT_THRESHOLD and not data.get("alerted"):
            data["alerted"] = True
            _save_today(data)
            logger.warning(
                "Abstain rate %.0f%% (%s/%s) — el targeting puede estar mandando "
                "temas fuera del alcance real del agente",
                rate * 100, data["abstained"], data["attempts"],
            )
            return rate
        return None
    except Exception as e:
        logger.debug("abstain_tracker: record failed: %s", e)
        return None
