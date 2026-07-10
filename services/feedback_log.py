from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

FEEDBACK_LOG_PATH = Path("data/feedback_log.jsonl")


@dataclass
class FeedbackMetrics:
    comments_count: int
    replies_depth_max: int
    unique_commenters: int


@dataclass
class FeedbackQuality:
    sentiment: str  # \"positive\" | \"neutral\" | \"negative\"
    has_deep_thread: bool


@dataclass
class FeedbackRecord:
    post_id: str
    created_at: str
    topic: str
    phase: str
    metrics: FeedbackMetrics
    quality: FeedbackQuality

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = asdict(self)
        return d


def append_feedback_record(record: FeedbackRecord) -> None:
    FEEDBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record.to_dict(), ensure_ascii=False)
    with FEEDBACK_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_post_feedback(
    *,
    post_id: str,
    topic: str,
    phase: str,
    comments_count: int,
    replies_depth_max: int,
    unique_commenters: int,
    sentiment: str,
    has_deep_thread: bool,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    record = FeedbackRecord(
        post_id=post_id,
        created_at=now,
        topic=topic,
        phase=phase,
        metrics=FeedbackMetrics(
            comments_count=comments_count,
            replies_depth_max=replies_depth_max,
            unique_commenters=unique_commenters,
        ),
        quality=FeedbackQuality(
            sentiment=sentiment,
            has_deep_thread=has_deep_thread,
        ),
    )
    append_feedback_record(record)
