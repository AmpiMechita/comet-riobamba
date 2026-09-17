"""Tests for core/write_policy.py — Editorial gate + rate limit."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import core.write_policy as wp
from core.write_policy import (
    TokenBucket,
    WriteDecision,
    WritePolicyEngine,
    WriteRequest,
)


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def config() -> dict:
    return {
        "max_posts_per_day": None,
        "per_submolt_daily_post_cap": 2,
        "enable_recent_post_guard": False,
        "require_english_for_posts": True,
        "require_agentic_niche": True,
        "require_named_pattern": True,
        "require_specific_agent_example": True,
        "require_production_context": True,
        "min_actionable_points": 2,
        "global_daily_reply_cap": 20,
        "per_thread_reply_cap": 1,
    }


@pytest.fixture
def engine(config: dict, base_dir: Path) -> WritePolicyEngine:
    return WritePolicyEngine(behavior_cfg=config, base_dir=base_dir)


@pytest.fixture
def valid_body() -> str:
    return (
        "The support agent uses a runtime policy engine to enforce "
        "guardrails in production. We log every handoff and trace each "
        "tool execution for observability. Monitoring and evaluation "
        "metrics validate each request before deployment."
    )


@pytest.fixture
def valid_post(valid_body: str) -> WriteRequest:
    return WriteRequest(
        write_type="post",
        title="Runtime policy engines for production support agents",
        body=valid_body,
        submolt="general",
        thread_id=None,
        topic_key="runtime-policy-support",
        now=datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc),
        phase="A",
    )


# ─── TokenBucket ─────────────────────────────────────────────────


class TestTokenBucket:
    def test_fresh_bucket_is_ready(self):
        bucket = TokenBucket(interval_seconds=60)
        assert bucket.can_write() is True
        assert bucket.seconds_until_ready() == 0.0

    def test_bucket_blocks_after_consume(self):
        bucket = TokenBucket(interval_seconds=60)
        bucket.consume()
        assert bucket.can_write() is False
        assert 0 < bucket.seconds_until_ready() <= 60

    def test_bucket_ready_after_interval(self, monkeypatch):
        bucket = TokenBucket(interval_seconds=10)
        bucket.consume()
        real_time = wp._time
        monkeypatch.setattr(wp, "_time", lambda: real_time() + 100)
        assert bucket.can_write() is True
        assert bucket.seconds_until_ready() == 0.0


# ─── Predicados de texto ─────────────────────────────────────────


class TestPredicates:
    def test_mostly_english_positive(self, engine: WritePolicyEngine):
        assert engine._is_mostly_english(
            "The agent runs in production and monitors every runtime."
        ) is True

    def test_mostly_english_negative(self, engine: WritePolicyEngine):
        assert engine._is_mostly_english(
            "El agente de produccion requiere gobernanza y observabilidad."
        ) is False

    def test_mostly_english_empty(self, engine: WritePolicyEngine):
        assert engine._is_mostly_english("") is False

    def test_agentic_niche_positive(self, engine: WritePolicyEngine):
        assert engine._has_agentic_niche(
            "The runtime policy engine enforces guardrails on every tool call."
        ) is True

    def test_agentic_niche_negative(self, engine: WritePolicyEngine):
        assert engine._has_agentic_niche(
            "Pasta recipes for the whole family, easy and delicious."
        ) is False

    def test_named_pattern(self, engine: WritePolicyEngine):
        assert engine._has_named_pattern(
            "A runtime policy engine drives the flow."
        ) is True
        assert engine._has_named_pattern(
            "Nothing here matches the keywords."
        ) is False

    def test_specific_agent_example(self, engine: WritePolicyEngine):
        assert engine._has_specific_agent_example(
            "The support agent handles tickets."
        ) is True
        assert engine._has_specific_agent_example(
            "Random text without example."
        ) is False

    def test_production_context(self, engine: WritePolicyEngine):
        assert engine._has_production_context(
            "Deployed in production runtime."
        ) is True
        assert engine._has_production_context(
            "Just a prototype idea."
        ) is False

    def test_count_actionable_markers(self, engine: WritePolicyEngine):
        text = "We must log every step, trace each span, and monitor the pipeline."
        assert engine._count_actionable_markers(text) >= 3

    def test_count_actionable_markers_zero(self, engine: WritePolicyEngine):
        assert engine._count_actionable_markers(
            "Random musings without any concrete verbs."
        ) == 0


# ─── Hash / idempotency ──────────────────────────────────────────


class TestHashContent:
    def test_hash_stable(self, engine: WritePolicyEngine):
        h1 = engine._hash_content("title", "body")
        h2 = engine._hash_content("title", "body")
        assert h1 == h2

    def test_hash_differs_on_body(self, engine: WritePolicyEngine):
        assert engine._hash_content("t", "b1") != engine._hash_content("t", "b2")

    def test_hash_differs_on_title(self, engine: WritePolicyEngine):
        assert engine._hash_content("t1", "b") != engine._hash_content("t2", "b")


# ─── _validate_editorial_fit ─────────────────────────────────────


class TestEditorialFit:
    def test_reply_skips_editorial(self, engine: WritePolicyEngine, valid_post: WriteRequest):
        reply = WriteRequest(
            write_type="reply", title=None, body="ok",
            submolt="general", thread_id="t1", topic_key=None,
            now=valid_post.now, phase="B",
        )
        assert engine._validate_editorial_fit(reply) is None

    def test_empty_body(self, engine: WritePolicyEngine, valid_post: WriteRequest):
        req = WriteRequest(
            write_type="post", title="t", body="   ",
            submolt="general", thread_id=None, topic_key=None,
            now=valid_post.now, phase="A",
        )
        assert engine._validate_editorial_fit(req) == "empty_body"

    def test_not_english(self, engine: WritePolicyEngine, valid_post: WriteRequest):
        req = WriteRequest(
            write_type="post", title="t",
            body="El agente de produccion requiere gobernanza.",
            submolt="general", thread_id=None, topic_key=None,
            now=valid_post.now, phase="A",
        )
        assert engine._validate_editorial_fit(req) == "post_not_mostly_english"

    def test_outside_niche(self, engine: WritePolicyEngine, valid_post: WriteRequest):
        body = (
            "Cooking tips for the family. The soup is hot and the bread "
            "is fresh and everything is delicious in the kitchen."
        )
        req = WriteRequest(
            write_type="post", title="t", body=body,
            submolt="general", thread_id=None, topic_key=None,
            now=valid_post.now, phase="A",
        )
        assert engine._validate_editorial_fit(req) == "post_outside_agentic_niche"

    def test_valid_body_passes(self, engine: WritePolicyEngine, valid_post: WriteRequest):
        assert engine._validate_editorial_fit(valid_post) is None


# ─── _topic_recently_used ────────────────────────────────────────


class TestTopicCooldown:
    def test_none_topic_returns_false(self, engine: WritePolicyEngine):
        now = datetime.now(timezone.utc)
        assert engine._topic_recently_used(None, now) is False

    def test_no_file_returns_false(self, engine: WritePolicyEngine):
        now = datetime.now(timezone.utc)
        assert engine._topic_recently_used("t1", now) is False

    def test_recent_topic_returns_true(self, engine: WritePolicyEngine, base_dir: Path):
        idx = base_dir / "data" / "topic_index.json"
        idx.parent.mkdir(parents=True, exist_ok=True)
        now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        idx.write_text(
            json.dumps({"topic-a": (now - timedelta(hours=1)).isoformat()}),
            encoding="utf-8",
        )
        assert engine._topic_recently_used("topic-a", now) is True

    def test_stale_topic_returns_false(self, engine: WritePolicyEngine, base_dir: Path):
        idx = base_dir / "data" / "topic_index.json"
        idx.parent.mkdir(parents=True, exist_ok=True)
        now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        idx.write_text(
            json.dumps({"topic-b": (now - timedelta(hours=48)).isoformat()}),
            encoding="utf-8",
        )
        assert engine._topic_recently_used("topic-b", now) is False


# ─── decide() ────────────────────────────────────────────────────


class TestDecide:
    def test_valid_post_allowed(self, engine: WritePolicyEngine, valid_post: WriteRequest):
        d = engine.decide(valid_post)
        assert d.allowed is True
        assert d.reason == "allowed"
        assert d.idempotency_key

    def test_max_posts_cap_denies(self, config: dict, base_dir: Path, valid_post: WriteRequest):
        config["max_posts_per_day"] = 0
        eng = WritePolicyEngine(behavior_cfg=config, base_dir=base_dir)
        d = eng.decide(valid_post)
        assert d.allowed is False
        assert d.reason == "global_daily_post_cap_reached"

    def test_reply_valid_under_caps(self, engine: WritePolicyEngine, valid_post: WriteRequest):
        reply = WriteRequest(
            write_type="reply", title=None, body="Agreed, tracing matters.",
            submolt="general", thread_id="thread-1", topic_key=None,
            now=valid_post.now, phase="B",
        )
        d = engine.decide(reply)
        assert d.allowed is True

    def test_reply_global_cap_denies(self, config: dict, base_dir: Path, valid_post: WriteRequest):
        config["global_daily_reply_cap"] = 0
        eng = WritePolicyEngine(behavior_cfg=config, base_dir=base_dir)
        reply = WriteRequest(
            write_type="reply", title=None, body="ok",
            submolt="general", thread_id="t1", topic_key=None,
            now=valid_post.now, phase="B",
        )
        d = eng.decide(reply)
        assert d.allowed is False
        assert d.reason == "global_daily_reply_cap_reached"

    def test_post_rate_limit_after_consume(self, engine: WritePolicyEngine, valid_post: WriteRequest):
        d1 = engine.decide(valid_post)
        assert d1.allowed is True
        engine.log_write(valid_post, platform_id="p1")
        d2 = engine.decide(valid_post)
        assert d2.allowed is False
        assert "post_rate_limited" in d2.reason


# ─── log_write ───────────────────────────────────────────────────


class TestLogWrite:
    def test_writes_jsonl(self, engine: WritePolicyEngine, valid_post: WriteRequest, base_dir: Path):
        engine.log_write(valid_post, platform_id="plat-1")
        log_path = base_dir / "data" / "write_log.jsonl"
        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["id"] == "plat-1"
        assert rec["type"] == "post"
        assert rec["phase"] == "A"
        assert rec["idempotency_key"]

    def test_updates_topic_index(self, engine: WritePolicyEngine, valid_post: WriteRequest, base_dir: Path):
        engine.log_write(valid_post, platform_id="plat-2")
        idx = base_dir / "data" / "topic_index.json"
        assert idx.exists()
        data = json.loads(idx.read_text(encoding="utf-8"))
        assert "runtime-policy-support" in data

    def test_consumes_rate_limit_bucket(self, engine: WritePolicyEngine, valid_post: WriteRequest):
        engine.log_write(valid_post, platform_id="plat-3")
        assert engine._post_bucket.can_write() is False

