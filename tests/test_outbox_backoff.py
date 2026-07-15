"""Tests for outbox exponential backoff (7.1)."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.persistence import (
    _compute_next_retry_at,
    enqueue_outbox,
    fetch_pending_outbox,
    mark_outbox,
    update_outbox_backoff,
    DB_PATH,
)


# ── _compute_next_retry_at ───────────────────────────────────────


def test_compute_next_retry_at_monotonic_increase():
    t0 = _compute_next_retry_at(0, min_backoff=60, max_backoff=3600)
    t1 = _compute_next_retry_at(1, min_backoff=60, max_backoff=3600)
    t2 = _compute_next_retry_at(2, min_backoff=60, max_backoff=3600)
    # Each retry has a later timestamp
    assert t0 < t1 < t2


def test_compute_next_retry_at_capped():
    t_high = _compute_next_retry_at(10, min_backoff=60, max_backoff=3600)
    dt = datetime.strptime(t_high, "%Y-%m-%d %H:%M:%S")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Delay should be at most 3600s
    assert (dt - now).total_seconds() <= 3700


def test_compute_next_retry_at_formula():
    t = _compute_next_retry_at(0, min_backoff=60, max_backoff=3600)
    dt = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert 55 <= (dt - now).total_seconds() <= 65  # ~60s


# ── fetch_pending_outbox filters by next_retry_at ────────────────


@pytest.fixture
def _patch_db():
    original = DB_PATH
    test_db = Path("data/test_outbox_backoff.db")
    test_db.parent.mkdir(parents=True, exist_ok=True)
    test_db.unlink(missing_ok=True)
    import services.persistence as _p
    _p.DB_PATH = test_db
    from services.persistence import init_db
    init_db()
    yield
    test_db.unlink(missing_ok=True)
    _p.DB_PATH = original


def test_fetch_pending_skips_future_retry(_patch_db):
    enqueue_outbox("comment", {"post_id": "p1", "content": "hello"})
    enqueue_outbox("comment", {"post_id": "p2", "content": "world"})

    items = fetch_pending_outbox(limit=10)
    assert len(items) == 2

    # Apply backoff to item 1 (future retry)
    update_outbox_backoff(items[0]["id"], "error", retry_attempt=1)

    items_after = fetch_pending_outbox(limit=10)
    assert len(items_after) == 1
    # Item 1 should be filtered out (future retry)
    assert items_after[0]["id"] == items[1]["id"]


def test_fetch_pending_returns_expired_retry(_patch_db):
    enqueue_outbox("comment", {"post_id": "p1", "content": "hello"})
    items = fetch_pending_outbox(limit=10)
    item_id = items[0]["id"]

    # Force next_retry_at to the past
    from services.persistence import get_conn
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute(
            "UPDATE outbox SET retry_attempt = 2, next_retry_at = ? WHERE id = ?",
            (past, item_id),
        )

    items_after = fetch_pending_outbox(limit=10)
    assert len(items_after) == 1
    assert items_after[0]["retry_attempt"] == 2


def test_fetch_pending_returns_items_without_next_retry_at(_patch_db):
    enqueue_outbox("comment", {"post_id": "p1", "content": "fresh"})
    items = fetch_pending_outbox(limit=10)
    assert len(items) == 1
    assert items[0]["retry_attempt"] == 0


# ── update_outbox_backoff ────────────────────────────────────────


def test_update_outbox_backoff_increments_retry_attempt(_patch_db):
    enqueue_outbox("comment", {"post_id": "p1", "content": "test"})
    items = fetch_pending_outbox(limit=10)
    item_id = items[0]["id"]

    update_outbox_backoff(item_id, "some error", retry_attempt=1)
    items_after = fetch_pending_outbox(limit=10)
    assert len(items_after) == 0  # filtered by future next_retry_at

    # Verify through raw query
    from services.persistence import get_conn
    with get_conn() as conn:
        row = conn.execute("SELECT retry_attempt, next_retry_at FROM outbox WHERE id = ?", (item_id,)).fetchone()
        assert row[0] == 1
        assert row[1] is not None



