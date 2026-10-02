# -*- coding: utf-8 -*-
"""
Pruebas para la capa de métricas diarias (core/metrics.py).
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.update({"DASHSCOPE_API_KEY": "sk-test", "MOLTBOOK_API_KEY": "sk-test"})

logging.basicConfig(level=logging.INFO, format="%(levelname)s|%(name)s|%(message)s")

import core.daily_metrics as daily_metrics
from core.daily_metrics import (
    DailyMetrics,
    load_metrics,
    save_metrics,
    get_current_metrics,
    ingest_event,
)


# ── Tests ────────────────────────────────────────────────────────

def test_daily_metrics_init_with_zeros():
    m = DailyMetrics(date_str="2026-06-09")
    d = m.to_dict()
    assert d["date"] == "2026-06-09"
    assert d["cycle_count"] == 0
    assert d["posts_published"] == 0
    assert d["posts_skipped_daily_limit"] == 0
    assert d["comments_published"] == 0
    assert d["errors_total"] == 0
    assert d["last_cycle_duration_avg_s"] == 0.0


def test_daily_metrics_no_date_defaults_to_today():
    m = DailyMetrics()
    assert m.date == datetime.now().date().isoformat()


def test_daily_metrics_merge_events():
    m = DailyMetrics(date_str="2026-06-09")

    m.merge_event("cycle_start")
    m.merge_event("cycle_start")
    m.merge_event("cycle_end", {"duration": 100.0})
    m.merge_event("phase_a_publish_success", {"count": 1})
    m.merge_event("phase_a_publish_skip", {"reason": "daily_limit_reached"})
    m.merge_event("phase_b_reply_success", {"count": 3})
    m.merge_event("phase_b_reply_skip", {"reason": "daily_limit_reached"})
    m.merge_event("phase_b_reply_skip", {"reason": "per_cycle_limit_reached"})
    m.merge_event("phase_b_reply_skip", {"reason": "per_post_limit_reached"})
    m.merge_event("phase_b_reply_skip", {"reason": "reply_skipped_low_relevance"})
    m.merge_event("phase_b_duplicate_skip")
    m.merge_event("phase_c_analytics_run")
    m.merge_event("outbox_post_published")
    m.merge_event("outbox_comment_published")
    m.merge_event("cycle_end", {"duration": 50.0, "error": "timeout"})

    d = m.to_dict()
    assert d["cycle_count"] == 2
    assert d["posts_published"] == 1
    assert d["posts_skipped_daily_limit"] == 1
    assert d["comments_published"] == 3
    assert d["comments_skipped_daily_limit"] == 1
    assert d["comments_skipped_per_cycle_limit"] == 1
    assert d["comments_skipped_per_post_limit"] == 1
    assert d["comments_skipped_low_relevance"] == 1
    assert d["comments_near_duplicate_skipped"] == 1
    assert d["phase_c_runs"] == 1
    assert d["outbox_posts_retried"] == 1
    assert d["comment_outbox_retried"] == 1
    assert d["errors_total"] == 1  # cycle_end with error
    assert d["last_cycle_duration_avg_s"] == 75.0  # (100 + 50) / 2


def test_serialization_round_trip():
    m1 = DailyMetrics(date_str="2026-06-09")
    m1.cycle_count = 5
    m1.posts_published = 2
    save_metrics(m1)

    m2 = load_metrics("2026-06-09")
    assert m2.date == "2026-06-09"
    assert m2.cycle_count == 5
    assert m2.posts_published == 2


def test_load_metrics_nonexistent_date():
    m = load_metrics("2099-01-01")
    assert m.date == "2099-01-01"
    assert m.cycle_count == 0


def test_ingest_event_updates_and_persists():
    ingest_event("cycle_start")
    ingest_event("phase_a_publish_success", {"count": 1})
    ingest_event("cycle_end", {"duration": 30.0})

    current = get_current_metrics()
    assert current.cycle_count == 1
    assert current.posts_published == 1

    # Verificar que persiste a disco
    today = datetime.now().date().isoformat()
    path = daily_metrics.METRICS_DIR / f"{today}.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["cycle_count"] == 1
    assert data["posts_published"] == 1
    assert data["last_cycle_duration_avg_s"] == 30.0


def test_ingest_event_with_error():
    ingest_event("cycle_end", {"duration": 10.0, "error": "timeout"})
    current = get_current_metrics()
    assert current.errors_total == 1


def test_avg_duration_no_cycles():
    m = DailyMetrics(date_str="2026-06-09")
    assert m.last_cycle_duration_avg_s == 0.0


# ── Expanded metrics tests ──────────────────────────────────────

def test_from_dict_handles_new_format_with_sum_count():
    """from_dict should restore sum and count correctly."""
    data: Dict[str, Any] = {
        "date": "2026-06-09",
        "cycle_count": 3,
        "posts_published": 1,
        "comments_published": 2,
        "last_cycle_duration_sum_s": 200.0,
        "last_cycle_duration_count": 4,
        "last_cycle_duration_avg_s": 50.0,
    }
    m = DailyMetrics.from_dict(data)
    assert m.cycle_count == 3
    assert m.comments_published == 2
    assert m.last_cycle_duration_sum_s == 200.0
    assert m.last_cycle_duration_count == 4
    assert m.last_cycle_duration_avg_s == 50.0


def test_from_dict_handles_old_format_with_only_avg():
    """from_dict should fallback when sum/count are missing (old JSON format)."""
    data: Dict[str, Any] = {
        "date": "2026-06-09",
        "cycle_count": 2,
        "last_cycle_duration_avg_s": 65.0,
    }
    m = DailyMetrics.from_dict(data)
    assert m.last_cycle_duration_avg_s == 65.0
    assert m.last_cycle_duration_count == 1


def test_to_dict_includes_sum_and_count():
    """to_dict should export the new sum/count fields."""
    m = DailyMetrics(date_str="2026-06-09")
    m.merge_event("cycle_start")
    m.merge_event("cycle_end", {"duration": 100.0})
    m.merge_event("cycle_start")
    m.merge_event("cycle_end", {"duration": 50.0})
    d = m.to_dict()
    assert d["last_cycle_duration_sum_s"] == 150.0
    assert d["last_cycle_duration_count"] == 2
    assert d["last_cycle_duration_avg_s"] == 75.0


def test_phase_b_reply_success_event_increments_metric():
    """Sending phase_b_reply_success should increment comments_published."""
    m = DailyMetrics(date_str="2026-06-10")
    m.merge_event("phase_b_reply_success", {"post_id": "p1", "comment_id": "c1"})
    assert m.comments_published == 1
    m.merge_event("phase_b_reply_success", {"post_id": "p2", "comment_id": "c2"})
    assert m.comments_published == 2


def test_serialization_with_duration_preserves_sum_count():
    """Save and reload should preserve sum/count for duration calculation."""
    m1 = DailyMetrics(date_str="2026-06-10")
    m1.cycle_count = 1
    m1.last_cycle_duration_sum_s = 100.0
    m1.last_cycle_duration_count = 2
    save_metrics(m1)

    m2 = load_metrics("2026-06-10")
    assert m2.last_cycle_duration_sum_s == 100.0
    assert m2.last_cycle_duration_count == 2
    assert m2.last_cycle_duration_avg_s == 50.0

