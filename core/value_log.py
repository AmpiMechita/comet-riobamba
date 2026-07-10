import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("core.value_log")

VALUE_LOG_PATH = Path("data/value_log.jsonl")


def _ensure_file():
    VALUE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not VALUE_LOG_PATH.exists():
        VALUE_LOG_PATH.write_text("", encoding="utf-8")
        logger.debug("Value log creado: %s", VALUE_LOG_PATH)


def log_value_event(event: Dict[str, Any]) -> None:
    _ensure_file()
    required = ["id", "timestamp", "post_id", "comment_id", "clasificacion_valor"]
    for key in required:
        if key not in event:
            logger.warning("ValueLog: falta campo obligatorio '%s', se omite evento", key)
            return
    try:
        with VALUE_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        logger.info(
            "ValueLog: registrado evento de valor %s en post %s, comment %s (clasificacion=%s)",
            event.get("clasificacion_valor"),
            event.get("post_id"),
            event.get("comment_id"),
            event.get("clasificacion_valor"),
        )
    except Exception as e:
        logger.error("ValueLog: error escribiendo evento: %s", e)


def get_value_events_since(date_from: datetime) -> List[Dict[str, Any]]:
    _ensure_file()
    events: List[Dict[str, Any]] = []
    try:
        with VALUE_LOG_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    ts_str = event.get("timestamp", "")
                    if ts_str:
                        event_ts = datetime.fromisoformat(ts_str)
                        if event_ts >= date_from:
                            events.append(event)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.error("ValueLog: error leyendo %s: %s", VALUE_LOG_PATH, e)
        return []
    return events
