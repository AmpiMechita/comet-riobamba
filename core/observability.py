from __future__ import annotations

import json
import logging
from datetime import datetime, UTC
from typing import Any, Dict, Optional

logger = logging.getLogger("observability")

EVENT_TYPES = frozenset({
    "cycle_start",
    "cycle_end",
    "phase_a_publish_attempt",
    "phase_a_publish_success",
    "phase_a_publish_skip",
    "phase_b_scan_start",
    "phase_b_reply_attempt",
    "phase_b_reply_success",
    "phase_b_reply_skip",
    "value_log_saved",
    "value_review_run",
    "state_reset_daily",
    "state_saved",
})


def _do_send_event(event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    record = {
        "event": event_type,
        "timestamp": datetime.now(UTC).isoformat() + "Z",
    }
    if payload:
        record["payload"] = payload
    logger.info("EVENT %s | %s", event_type, json.dumps(payload or {}, default=str, ensure_ascii=False))

    from core.metrics import ingest_event as _ingest
    _ingest(event_type, payload)


def send_event(event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    try:
        _do_send_event(event_type, payload)
    except Exception as e:
        logger.error("Observability: error sending event %s: %s", event_type, e, exc_info=True)
