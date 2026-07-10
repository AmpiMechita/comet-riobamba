import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SocialMetricsLogger:
    def __init__(self, path: str = "data/social_metrics.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log_event(
        self,
        event_type: str,
        success: bool,
        source_phase: str,
        target_kind: Optional[str] = None,
        interaction_kind: Optional[str] = None,
        root_post_id: Optional[str] = None,
        target_post_id: Optional[str] = None,
        parent_comment_id: Optional[str] = None,
        submolt: Optional[str] = None,
        content_preview: Optional[str] = None,
        error: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        event = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "success": bool(success),
            "source_phase": source_phase,
            "target_kind": target_kind,
            "interaction_kind": interaction_kind,
            "root_post_id": root_post_id,
            "target_post_id": target_post_id,
            "parent_comment_id": parent_comment_id,
            "submolt": submolt,
            "content_preview": (content_preview or "")[:280],
            "error": error,
        }

        if extra:
            event["extra"] = extra

        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"No se pudo registrar social metric: {e}")
