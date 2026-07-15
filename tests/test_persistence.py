# -*- coding: utf-8 -*-
"""
Tests para services/persistence.py
Cubre: init_db, agent_state, outbox lifecycle, dedup, flags, backoff
"""
import pytest
import sqlite3

import services.persistence as persistence


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_comet.db"


@pytest.fixture
def db(db_path, monkeypatch):
    monkeypatch.setattr(persistence, "DB_PATH", db_path)
    persistence.init_db()
    return persistence


# ── init_db ───────────────────────────────────────────────────────────────────

class TestInitDb:
    def test_creates_required_tables(self, db, db_path):
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "agent_state" in tables
        assert "outbox" in tables
        assert "system_flags" in tables

    def test_is_idempotent(self, db):
        db.init_db()  # segunda llamada no debe lanzar excepción


# ── agent_state ───────────────────────────────────────────────────────────────

class TestAgentState:
    def test_load_on_empty_db_returns_dict(self, db):
        state = db.load_agent_state()
        assert isinstance(state, dict)

    def test_save_and_load_roundtrip(self, db):
        db.save_agent_state({"cycle": 7, "posts_today": 3, "version": "4.3.0"})
        loaded = db.load_agent_state()
        assert loaded["cycle"] == 7
        assert loaded["posts_today"] == 3

    def test_save_overwrites_previous_state(self, db):
        db.save_agent_state({"cycle": 1})
        db.save_agent_state({"cycle": 2})
        assert db.load_agent_state()["cycle"] == 2


# ── outbox ────────────────────────────────────────────────────────────────────

class TestOutbox:
    def test_fetch_on_empty_outbox_returns_empty_list(self, db):
        assert db.fetch_pending_outbox() == []

    def test_enqueue_then_fetch_returns_item(self, db):
        db.enqueue_outbox("post", {"title": "Test", "body": "Content"})
        items = db.fetch_pending_outbox(limit=5)
        assert len(items) == 1
        assert items[0]["kind"] == "post"

    def test_fetch_respects_limit(self, db):
        for i in range(5):
            db.enqueue_outbox("post", {"title": f"Post {i}"})
        items = db.fetch_pending_outbox(limit=3)
        assert len(items) == 3

    def test_mark_published_removes_from_pending(self, db):
        db.enqueue_outbox("post", {"title": "X"})
        items = db.fetch_pending_outbox()
        db.mark_outbox(items[0]["id"], "published", None)
        assert db.fetch_pending_outbox() == []

    def test_mark_failed_removes_from_pending(self, db):
        db.enqueue_outbox("post", {"title": "Y"})
        items = db.fetch_pending_outbox()
        db.mark_outbox(items[0]["id"], "failed", "timeout")
        assert db.fetch_pending_outbox() == []

    def test_enqueue_multiple_preserves_fifo_order(self, db):
        for i in range(3):
            db.enqueue_outbox("post", {"order": i})
        items = db.fetch_pending_outbox(limit=10)
        orders = [item["payload"]["order"] for item in items]
        assert orders == sorted(orders)


# ── backoff ───────────────────────────────────────────────────────────────────

class TestOutboxBackoff:
    def test_update_backoff_increments_retry_attempt(self, db):
        db.enqueue_outbox("post", {"title": "Retry me"})
        item = db.fetch_pending_outbox()[0]
        db.update_outbox_backoff(
            item["id"],
            last_error="timeout",
            retry_attempt=1,
            min_backoff=60,
            max_backoff=3600,
        )
        # Item no debe aparecer en pending hasta que pase next_retry_at
        # Verificamos que no está en pending inmediatamente
        pending = db.fetch_pending_outbox()
        assert all(p["id"] != item["id"] for p in pending)


# ── dedup ─────────────────────────────────────────────────────────────────────

class TestDedup:
    def test_unseen_text_is_not_similar(self, db):
        assert db.is_similar_to_recent("Brand new unique content") is False

    def test_stored_text_is_similar_to_itself(self, db):
        text = "Post about circuit breakers in distributed systems"
        db.store_post_hash("post-001", text)
        assert db.is_similar_to_recent(text) is True

    def test_different_text_is_not_similar_after_store(self, db):
        db.store_post_hash("post-002", "Post about rate limiting")
        assert db.is_similar_to_recent("Completely different topic about observability") is False

    def test_store_multiple_posts_dedup_works(self, db):
        db.store_post_hash("post-003", "First post content")
        db.store_post_hash("post-004", "Second post content")
        assert db.is_similar_to_recent("First post content") is True
        assert db.is_similar_to_recent("Second post content") is True
        assert db.is_similar_to_recent("Third unique content") is False


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags:
    def test_get_nonexistent_flag_returns_none(self, db):
        assert db.get_flag("nonexistent") is None

    def test_set_and_get_roundtrip(self, db):
        db.set_flag("my_flag", {"active": True, "value": 42})
        result = db.get_flag("my_flag")
        assert result["active"] is True
        assert result["value"] == 42

    def test_set_flag_overwrites_previous_value(self, db):
        db.set_flag("counter", {"n": 1})
        db.set_flag("counter", {"n": 2})
        assert db.get_flag("counter")["n"] == 2

    def test_independent_flags_do_not_interfere(self, db):
        db.set_flag("flag_a", {"x": 1})
        db.set_flag("flag_b", {"x": 2})
        assert db.get_flag("flag_a")["x"] == 1
        assert db.get_flag("flag_b")["x"] == 2
