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


@pytest.fixture(autouse=True)
def _isolate_outbox_db(tmp_path, monkeypatch):
    """Aisla el DB del outbox (comet_state.db) a tmp_path.
    Sin esto, los tests escriben 'T'/'B' al outbox real y el agente
    los publica al arrancar (bug observado 2026-09-15).
    """
    import services.persistence as sp
    monkeypatch.setattr(sp, "DB_PATH", tmp_path / "comet_state.db", raising=False)


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
def _patch_db(tmp_path):
    original = DB_PATH
    test_db = tmp_path / "test_outbox_backoff.db"
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


# ── Error classification: needs_reconciliation vs failed vs pending ──

def test_timeout_marks_needs_reconciliation():
    """Timeout / network exception → 'needs_reconciliation', NOT 'pending'."""
    from services.persistence import init_db, enqueue_outbox, get_conn, mark_outbox

    init_db()
    enqueue_outbox("post", {"title": "T", "body": "B"})

    with get_conn() as conn:
        item_id = conn.execute(
            "SELECT id FROM outbox WHERE kind='post' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]

    # Simulate what _retry_outbox does on network exception
    mark_outbox(item_id, "needs_reconciliation", "ConnectionError: timeout")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, last_error FROM outbox WHERE id = ?", (item_id,)
        ).fetchone()
    assert row[0] == "needs_reconciliation"
    assert "timeout" in (row[1] or "")

    # Also verify fetch_pending_outbox does NOT return needs_reconciliation items
    from services.persistence import fetch_pending_outbox
    pending = fetch_pending_outbox(limit=10)
    post_ids = [i["id"] for i in pending if i.get("kind") == "post"]
    assert item_id not in post_ids, "needs_reconciliation item was returned as pending"


def test_validation_error_marks_failed():
    """4xx validation error → 'failed', should NOT be retried."""
    from unittest.mock import MagicMock
    from services.persistence import init_db, enqueue_outbox, get_conn, mark_outbox

    init_db()
    enqueue_outbox("post", {"title": "T", "body": "B"})

    # Simulate an outbox item that got a 422 from the API
    with get_conn() as conn:
        item_id = conn.execute(
            "SELECT id FROM outbox WHERE kind='post' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]

    mark_outbox(item_id, "failed", "HTTP 422: validation error")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, last_error FROM outbox WHERE id = ?", (item_id,)
        ).fetchone()
    assert row[0] == "failed"
    assert "422" in (row[1] or "")


def test_retryable_503_keeps_pending():
    """503 Service Unavailable should keep 'pending' with backoff."""
    from unittest.mock import MagicMock
    from services.persistence import init_db, enqueue_outbox, get_conn, update_outbox_backoff

    init_db()
    enqueue_outbox("post", {"title": "T", "body": "B"})

    with get_conn() as conn:
        item_id = conn.execute(
            "SELECT id FROM outbox WHERE kind='post' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]

    update_outbox_backoff(item_id, "HTTP 503", retry_attempt=1)

    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, retry_attempt, next_retry_at FROM outbox WHERE id = ?", (item_id,)
        ).fetchone()
    assert row[0] == "pending"
    assert row[1] == 1
    assert row[2] is not None  # next_retry_at was set


# ── explicit_delay_seconds for 429 Retry-After ────────────────────

def test_explicit_delay_uses_server_retry_after():
    """When explicit_delay_seconds is provided, next_retry_at must reflect
    approximately that delay, not generic exponential backoff."""
    from services.persistence import init_db, enqueue_outbox, get_conn, update_outbox_backoff
    from datetime import datetime, timedelta, timezone

    init_db()
    enqueue_outbox("post", {"title": "T", "body": "B"})

    with get_conn() as conn:
        item_id = conn.execute(
            "SELECT id FROM outbox WHERE kind='post' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]

    # Simulate 429 with Retry-After: 107 seconds
    update_outbox_backoff(item_id, "HTTP 429", retry_attempt=1, explicit_delay_seconds=107)

    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, retry_attempt, next_retry_at FROM outbox WHERE id = ?", (item_id,)
        ).fetchone()
    assert row[0] == "pending"
    assert row[1] == 1

    # The delay should be approximately 107s (not the exponential 60s)
    next_at = datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    delay = (next_at - now).total_seconds()
    # With explicit_delay=107 and min=max=107, the formula gives 107*2^0=107
    assert 100 <= delay <= 115, f"Expected ~107s delay, got {delay:.0f}s"


def test_explicit_delay_capped_at_max_backoff():
    """explicit_delay_seconds must be capped at max_backoff."""
    from services.persistence import init_db, enqueue_outbox, get_conn, update_outbox_backoff
    from datetime import datetime, timedelta, timezone

    init_db()
    enqueue_outbox("post", {"title": "T", "body": "B"})

    with get_conn() as conn:
        item_id = conn.execute(
            "SELECT id FROM outbox WHERE kind='post' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]

    # Simulate 429 with absurdly large Retry-After: 99999 seconds
    update_outbox_backoff(item_id, "HTTP 429", retry_attempt=1,
                          max_backoff=3600, explicit_delay_seconds=99999)

    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, retry_attempt, next_retry_at FROM outbox WHERE id = ?", (item_id,)
        ).fetchone()
    assert row[0] == "pending"

    next_at = datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    delay = (next_at - now).total_seconds()
    assert delay <= 3605, f"Expected delay capped at 3600, got {delay:.0f}s"


def test_explicit_delay_does_not_affect_generic_5xx():
    """Without explicit_delay_seconds, behavior is unchanged (exponential backoff)."""
    from services.persistence import init_db, enqueue_outbox, get_conn, update_outbox_backoff
    from datetime import datetime, timedelta, timezone

    init_db()
    enqueue_outbox("post", {"title": "T", "body": "B"})

    with get_conn() as conn:
        item_id = conn.execute(
            "SELECT id FROM outbox WHERE kind='post' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]

    # Generic 5xx without explicit delay
    update_outbox_backoff(item_id, "HTTP 503", retry_attempt=0)

    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, retry_attempt, next_retry_at FROM outbox WHERE id = ?", (item_id,)
        ).fetchone()
    assert row[0] == "pending"
    next_at = datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    delay = (next_at - now).total_seconds()
    # Retry 0 with min 60 = 60 * 2^0 = 60
    assert 55 <= delay <= 65, f"Expected ~60s default backoff, got {delay:.0f}s"



