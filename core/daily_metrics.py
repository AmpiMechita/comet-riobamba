# -*- coding: utf-8 -*-
"""
Métricas diarias para COMET-RIOBAMBA.

Define el esquema de métricas por día, un agregador que se alimenta
de send_event(), y persistencia a data/metrics/YYYY-MM-DD.json.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("core.metrics")

METRICS_DIR = Path("data/metrics")


class DailyMetrics:
    """Métricas agregadas para un día calendario."""

    def __init__(self, date_str: Optional[str] = None):
        self.date: str = date_str or datetime.now().date().isoformat()
        self.cycle_count: int = 0
        self.posts_published: int = 0
        self.posts_skipped_daily_limit: int = 0
        self.comments_published: int = 0
        self.comments_skipped_daily_limit: int = 0
        self.comments_skipped_per_cycle_limit: int = 0
        self.comments_skipped_per_post_limit: int = 0
        self.comments_skipped_low_relevance: int = 0
        self.comments_near_duplicate_skipped: int = 0
        self.comment_outbox_retried: int = 0
        self.phase_c_runs: int = 0
        self.outbox_posts_retried: int = 0
        self.errors_total: int = 0
        self.consecutive_failures: int = 0
        self.last_cycle_duration_sum_s: float = 0.0
        self.last_cycle_duration_count: int = 0

    @property
    def last_cycle_duration_avg_s(self) -> float:
        if self.last_cycle_duration_count == 0:
            return 0.0
        return round(self.last_cycle_duration_sum_s / self.last_cycle_duration_count, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "cycle_count": self.cycle_count,
            "posts_published": self.posts_published,
            "posts_skipped_daily_limit": self.posts_skipped_daily_limit,
            "comments_published": self.comments_published,
            "comments_skipped_daily_limit": self.comments_skipped_daily_limit,
            "comments_skipped_per_cycle_limit": self.comments_skipped_per_cycle_limit,
            "comments_skipped_per_post_limit": self.comments_skipped_per_post_limit,
            "comments_skipped_low_relevance": self.comments_skipped_low_relevance,
            "comments_near_duplicate_skipped": self.comments_near_duplicate_skipped,
            "comment_outbox_retried": self.comment_outbox_retried,
            "phase_c_runs": self.phase_c_runs,
            "outbox_posts_retried": self.outbox_posts_retried,
            "errors_total": self.errors_total,
            "consecutive_failures": self.consecutive_failures,
            "last_cycle_duration_sum_s": self.last_cycle_duration_sum_s,
            "last_cycle_duration_count": self.last_cycle_duration_count,
            "last_cycle_duration_avg_s": self.last_cycle_duration_avg_s,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DailyMetrics:
        m = cls(date_str=data.get("date", datetime.now().date().isoformat()))
        m.cycle_count = int(data.get("cycle_count", 0))
        m.posts_published = int(data.get("posts_published", 0))
        m.posts_skipped_daily_limit = int(data.get("posts_skipped_daily_limit", 0))
        m.comments_published = int(data.get("comments_published", 0))
        m.comments_skipped_daily_limit = int(data.get("comments_skipped_daily_limit", 0))
        m.comments_skipped_per_cycle_limit = int(data.get("comments_skipped_per_cycle_limit", 0))
        m.comments_skipped_per_post_limit = int(data.get("comments_skipped_per_post_limit", 0))
        m.comments_skipped_low_relevance = int(data.get("comments_skipped_low_relevance", 0))
        m.comments_near_duplicate_skipped = int(data.get("comments_near_duplicate_skipped", 0))
        m.comment_outbox_retried = int(data.get("comment_outbox_retried", 0))
        m.phase_c_runs = int(data.get("phase_c_runs", 0))
        m.outbox_posts_retried = int(data.get("outbox_posts_retried", 0))
        m.errors_total = int(data.get("errors_total", 0))
        m.consecutive_failures = int(data.get("consecutive_failures", 0))
        m.last_cycle_duration_sum_s = float(data.get("last_cycle_duration_sum_s", 0))
        m.last_cycle_duration_count = int(data.get("last_cycle_duration_count", 0))
        # Fallback for old format that only stored last_cycle_duration_avg_s
        if m.last_cycle_duration_sum_s == 0 and m.last_cycle_duration_count == 0:
            old_avg = float(data.get("last_cycle_duration_avg_s", 0))
            if old_avg > 0:
                m.last_cycle_duration_sum_s = old_avg
                m.last_cycle_duration_count = 1
        return m

    def merge_event(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        payload = payload or {}
        if event_type == "cycle_start":
            self.cycle_count += 1
        elif event_type == "cycle_end":
            dur = payload.get("duration", 0)
            if isinstance(dur, (int, float)):
                self.last_cycle_duration_sum_s += float(dur)
                self.last_cycle_duration_count += 1
            if payload.get("error"):
                self.errors_total += 1
        elif event_type == "phase_a_publish_success":
            self.posts_published += int(payload.get("count", 0))
        elif event_type == "phase_a_publish_skip":
            reason = payload.get("reason", "")
            if "daily_limit" in reason:
                self.posts_skipped_daily_limit += 1
        elif event_type == "phase_b_reply_success":
            self.comments_published += int(payload.get("count", 1))
        elif event_type == "phase_b_reply_skip":
            reason = payload.get("reason", "")
            if "daily_limit" in reason or "max_feed" in reason:
                self.comments_skipped_daily_limit += 1
            elif "per_cycle_limit" in reason:
                self.comments_skipped_per_cycle_limit += 1
            elif "per_post_limit" in reason or "limit_reached" in reason:
                self.comments_skipped_per_post_limit += 1
            else:
                self.comments_skipped_low_relevance += 1
        elif event_type == "phase_b_duplicate_skip":
            self.comments_near_duplicate_skipped += 1
        elif event_type == "phase_c_analytics_run":
            self.phase_c_runs += 1
        elif event_type == "outbox_post_published":
            self.outbox_posts_retried += 1
        elif event_type == "outbox_comment_published":
            self.comment_outbox_retried += 1
        elif event_type == "state_reset_daily":
            self.consecutive_failures = int(payload.get("consecutive_failures", 0))


def file_path_for_date(date_str: str) -> Path:
    return METRICS_DIR / f"{date_str}.json"


def load_metrics(date_str: str) -> DailyMetrics:
    path = file_path_for_date(date_str)
    if not path.exists():
        return DailyMetrics(date_str=date_str)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return DailyMetrics.from_dict(data)
    except Exception as e:
        logger.warning("Metrics: error loading %s: %s", path, e)
        return DailyMetrics(date_str=date_str)


def save_metrics(metrics: DailyMetrics) -> None:
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    path = file_path_for_date(metrics.date)
    path.write_text(
        json.dumps(metrics.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── Global aggregator ──────────────────────────────────────────

_current_metrics: Optional[DailyMetrics] = None


def get_current_metrics() -> DailyMetrics:
    global _current_metrics
    today = datetime.now().date().isoformat()
    if _current_metrics is None or _current_metrics.date != today:
        _current_metrics = load_metrics(today)
    return _current_metrics


def ingest_event(event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """Entry point: call this from send_event() or agent code."""
    metrics = get_current_metrics()
    metrics.merge_event(event_type, payload)
    save_metrics(metrics)
