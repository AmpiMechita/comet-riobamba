# -*- coding: utf-8 -*-
"""Pause controller: estado de pausa del agente.

Razones posibles: "battery", "balance".
El agente se pausa cuando hay >=1 razon. Se reanuda cuando todas se limpian.

Persistencia: data/pause.flag (JSON).
Disenado para sobrevivir reinicios (si el proceso muere y vuelve a arrancar,
lee el flag y se mantiene pausado hasta que se cumplan las condiciones).
"""
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict

logger = logging.getLogger("services.pause_controller")

PAUSE_FILE = Path("data/pause.flag")
_lock = threading.Lock()
_recheckers = {}


def _read_state() -> Dict:
    if not PAUSE_FILE.exists():
        return {"reasons": {}, "since": None}
    try:
        data = json.loads(PAUSE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"reasons": {}, "since": None}
        data.setdefault("reasons", {})
        data.setdefault("since", None)
        return data
    except Exception as e:
        logger.warning("pause_controller: error leyendo pause.flag: %s", e)
        return {"reasons": {}, "since": None}


def _write_state(state: Dict) -> None:
    """Escritura atomica."""
    try:
        PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PAUSE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(PAUSE_FILE)
    except Exception as e:
        logger.warning("pause_controller: error escribiendo pause.flag: %s", e)


def add_reason(reason: str, detail: str = "") -> None:
    """Anade una razon de pausa. Si es la primera, registra el timestamp."""
    with _lock:
        state = _read_state()
        if reason not in state["reasons"]:
            state["reasons"][reason] = {
                "detail": detail,
                "since": datetime.now(timezone.utc).isoformat(),
            }
            if state["since"] is None:
                state["since"] = state["reasons"][reason]["since"]
            _write_state(state)
            logger.warning("pause_controller: PAUSA anadida - %s (%s)", reason, detail)
        else:
            if state["reasons"][reason].get("detail") != detail:
                state["reasons"][reason]["detail"] = detail
                _write_state(state)


def remove_reason(reason: str) -> None:
    """Quita una razon. Si quedan 0, limpia el flag."""
    with _lock:
        state = _read_state()
        if reason in state["reasons"]:
            del state["reasons"][reason]
            if not state["reasons"]:
                state["since"] = None
                _write_state(state)
                try:
                    PAUSE_FILE.unlink()
                except FileNotFoundError:
                    pass
                logger.info("pause_controller: REANUDADO - todas las razones limpias")
            else:
                _write_state(state)
                logger.info("pause_controller: razon '%s' limpiada. Quedan: %s",
                            reason, list(state["reasons"].keys()))


def is_paused() -> bool:
    """True si hay >=1 razon activa."""
    state = _read_state()
    return bool(state["reasons"])


def get_reasons() -> Dict[str, Dict]:
    """Retorna dict {reason: {detail, since}}."""
    return _read_state()["reasons"]


def get_pause_since() -> str:
    """Retorna timestamp ISO de la primera pausa, o None."""
    return _read_state().get("since")


def register_rechecker(reason: str, fn: Callable[[], bool]) -> None:
    """Registra un re-verificador para una razon de pausa.

    fn() debe devolver True si la condicion externa YA NO aplica
    (=> la razon debe limpiarse). Se invoca desde run_recheckers(),
    que corre en el outer loop del agente y en un thread daemon.
    Idempotente: re-registrar sobrescribe.
    """
    _recheckers[reason] = fn


def run_recheckers() -> None:
    """Ejecuta el rechecker de cada razon ACTIVA. Limpia la razon si True.

    No hace nada para razones sin rechecker (battery lo hace via su
    propio thread).
    """
    for reason in list(get_reasons().keys()):
        fn = _recheckers.get(reason)
        if fn is None:
            continue
        try:
            if fn():
                remove_reason(reason)
        except Exception as e:
            logger.warning("pause_controller: rechecker %s fallo: %s", reason, e)


def _rechecker_loop(poll_seconds: int = 60) -> None:
    """Thread daemon: corre run_recheckers() cada poll_seconds."""
    logger.info("pause_controller: rechecker thread iniciado (poll=%ss)", poll_seconds)
    while True:
        try:
            run_recheckers()
        except Exception as e:
            logger.warning("pause_controller: error en rechecker loop: %s", e)
        time.sleep(poll_seconds)


def start_pause_rechecker_thread() -> threading.Thread:
    """Arranca el thread daemon de recheckers (idempotente-ish)."""
    t = threading.Thread(target=_rechecker_loop, name="pause-rechecker", daemon=True)
    t.start()
    return t
