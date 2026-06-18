"""Tests for services/moltbook_api_client.py — token-bucket rate limiter and 429 retry."""

import logging
import time
import pytest
from unittest.mock import MagicMock, patch
from services.moltbook_api_client import MoltbookAPIClient


# ── Helpers ───────────────────────────────────────────────────────


def _make_client(base_url="http://test.com", api_key="sekret"):
    return MoltbookAPIClient(base_url=base_url, api_key=api_key)


class FakeResponse:
    def __init__(self, status_code, data, text="", headers=None):
        self.status_code = status_code
        self._data = data
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("No fake response queued")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


# ── Token-bucket limiter: _wait_for_write_token ───────────────────


def test_write_limiter_first_call_allowed(monkeypatch):
    """First call gets a token immediately — no blocking."""
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "1")
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "150")

    sleep_calls = []
    monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))

    client = _make_client()
    client._wait_for_write_token("create_post")
    assert len(sleep_calls) == 0


def test_write_limiter_blocks_second_call(monkeypatch):
    """Second call within the same window blocks until a token refills."""
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "1")
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "150")

    frozen_time = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: frozen_time[0])
    sleep_calls = []
    monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))

    client = _make_client()

    # First call — token available
    client._wait_for_write_token("create_post")
    assert len(sleep_calls) == 0

    # Second call — no time elapsed, must wait full window
    client._wait_for_write_token("create_post")
    assert len(sleep_calls) == 1
    assert sleep_calls[0] == 150.0


@pytest.mark.parametrize("env_calls,expected_ok_before_block", [
    ("2", 2),
    ("3", 3),
])
def test_write_limiter_custom_calls(monkeypatch, env_calls, expected_ok_before_block):
    """MOLTBOOK_RATE_LIMIT_CALLS=N allows N calls before blocking."""
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", env_calls)
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "60")

    frozen_time = [2000.0]
    monkeypatch.setattr(time, "monotonic", lambda: frozen_time[0])
    sleep_calls = []
    monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))

    client = _make_client()

    for i in range(expected_ok_before_block):
        client._wait_for_write_token("create_post")
        assert len(sleep_calls) == 0, f"call {i+1} should not block"

    # Next call blocks
    client._wait_for_write_token("create_post")
    assert len(sleep_calls) == 1


def test_write_limiter_read_bypass(monkeypatch):
    """Read-only endpoints (get_feed, get_comments) bypass the limiter."""
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "1")

    client = _make_client()

    # Mock _request to return success
    original_request = client._request
    request_calls = []

    def tracking_request(method, path, **kw):
        request_calls.append((method, path))
        return {"status": 200, "data": {"items": [], "posts": []}}

    client._request = tracking_request

    # get_feed is read-only — no token consumed
    feed = client.get_feed()
    assert feed.success is True
    assert client._write_tokens == 1.0  # token not consumed

    # get_comments is read-only — no token consumed
    cmts = client.get_comments("post-1")
    assert cmts.success is True
    assert client._write_tokens == 1.0


# ── 429 retry via _call_write (through create_post) ──────────────


def test_write_limiter_429_retry_after_then_ok(monkeypatch):
    """429 with Retry-After → waits → retries once → succeeds."""
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "5")
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "1")

    sleep_calls = []
    monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))

    client = _make_client()
    call_idx = [0]

    def mock_request(method, path, **kw):
        call_idx[0] += 1
        if call_idx[0] == 1:
            return {"status": 429, "retry_after_seconds": 5, "data": {}}
        return {"status": 200, "data": {"post": {"id": "p123"}}}

    client._request = mock_request

    result = client.create_post("title", "body")
    assert result["success"] is True
    assert result["id"] == "p123"
    assert call_idx[0] == 2  # original + retry
    assert any(s == 5 for s in sleep_calls)  # slept for Retry-After


def test_write_limiter_429_double_failure_raises(monkeypatch):
    """429 → retry → 429 again → raises RuntimeError (no infinite loop)."""
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "5")
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "1")

    sleep_calls = []
    monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))

    client = _make_client()

    def mock_request(method, path, **kw):
        return {"status": 429, "retry_after_seconds": 3, "data": {}}

    client._request = mock_request

    result = client.create_post("title", "body")
    assert result["success"] is False
    assert result["status"] == 0
    assert "Retry-After" in (result.get("error") or "")


# ── ToolFeedback integration: create_comment ──────────────────────


def test_create_comment_toolfeedback_success(caplog):
    """ToolFeedback logs OUTCOME_OK on successful create_comment."""
    caplog.set_level(logging.INFO)
    client = _make_client()
    client._wait_for_write_token = MagicMock()
    client._call_write = MagicMock(return_value={
        "status": 201,
        "data": {"comment": {"id": "c-abc"}},
    })

    result = client.create_comment("post-1", "hello")

    assert result["success"] is True
    assert result["id"] == "c-abc"
    assert any("ToolFeedback create_comment outcome=success confidence=1.000" in msg for msg in caplog.messages)


def test_create_comment_happy_path_through_request(monkeypatch):
    """Integration-style: create_comment uses limiter, _request, parsing, and feedback."""
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "5")
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "1")
    client = _make_client()
    client.session = FakeSession(FakeResponse(201, {"comment": {"id": "c-int"}}))

    result = client.create_comment("post-1", "hello")

    assert result == {"success": True, "status": 201, "id": "c-int", "raw": {"comment": {"id": "c-int"}}}
    call = client.session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://test.com/api/v1/posts/post-1/comments"
    assert call["json"] == {"content": "hello"}
    assert client.circuit.get_stats()["failure_count"] == 0


def test_create_post_toolfeedback_through_request(monkeypatch, caplog):
    """Integration-style: create_post emits ToolFeedback and keeps breaker healthy."""
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "5")
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "1")
    caplog.set_level(logging.INFO)
    client = _make_client()
    client.session = FakeSession(FakeResponse(201, {"post": {"id": "p-int"}}))

    result = client.create_post("title", "body", metadata={"submolt": "ops"})

    assert result == {"success": True, "status": 201, "id": "p-int", "raw": {"post": {"id": "p-int"}}}
    call = client.session.calls[0]
    assert call["url"] == "http://test.com/api/v1/posts"
    assert call["json"] == {"submolt": "ops", "title": "title", "content": "body"}
    assert any("ToolFeedback create_post outcome=success confidence=1.000" in msg for msg in caplog.messages)
    assert client.circuit.get_stats()["failure_count"] == 0


def test_create_post_toolfeedback_low_confidence_forces_open_at_threshold(monkeypatch):
    """Low-confidence create_post results should open the breaker only at threshold."""
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "10")
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "1")
    monkeypatch.setenv("MOLTBOOK_CB_FAILURES", "2")
    client = _make_client()
    client.session = FakeSession(
        FakeResponse(200, {"post": {"text": "accepted"}}),
        FakeResponse(200, {"post": {"text": "accepted again"}}),
    )

    first = client.create_post("title", "body")
    assert first["success"] is True
    assert client.circuit.get_stats()["state"] == "closed"

    second = client.create_post("title", "body")
    assert second["success"] is True
    stats = client.circuit.get_stats()
    assert stats["state"] == "open"
    assert stats["failure_count"] == 2


def test_create_comment_toolfeedback_transport_failure(caplog):
    """ToolFeedback logs transport_failure when _call_write raises."""
    caplog.set_level(logging.INFO)
    client = _make_client()
    client._wait_for_write_token = MagicMock()
    client._call_write = MagicMock(side_effect=ConnectionError("connection refused"))

    result = client.create_comment("post-1", "hello")

    assert result["success"] is False
    assert result["status"] == 0
    assert any("ToolFeedback create_comment outcome=transport_failure" in msg for msg in caplog.messages)


def test_create_comment_toolfeedback_low_confidence(caplog):
    """ToolFeedback logs low confidence and trips circuit when schema is missing."""
    caplog.set_level(logging.INFO)
    client = _make_client()
    client._wait_for_write_token = MagicMock()
    client._call_write = MagicMock(return_value={
        "status": 200,
        "data": {"comment": {"text": "ok"}},
    })

    result = client.create_comment("post-1", "hello")

    assert result["success"] is True  # HTTP 200 → success even without id
    assert result["id"] is None
    assert any("confidence=0." in msg for msg in caplog.messages)
    assert any("trips circuit" in msg for msg in caplog.messages)
    assert client.circuit.get_stats()["failure_count"] == 1


def test_create_comment_toolfeedback_empty_id_rejected(caplog):
    """Empty string comment_id yields response_schema_ok=False (low confidence)."""
    caplog.set_level(logging.INFO)
    client = _make_client()
    client._wait_for_write_token = MagicMock()
    client._call_write = MagicMock(return_value={
        "status": 201,
        "data": {"comment": {"id": ""}},
    })

    result = client.create_comment("post-1", "hello")

    assert result["success"] is True
    assert result["id"] is None  # or-chain rejects empty string
    assert any("confidence=0." in msg for msg in caplog.messages)
    assert any("trips circuit" in msg for msg in caplog.messages)
    assert client.circuit.get_stats()["failure_count"] == 1


def test_logical_success_shape_failure_counts_toward_breaker(monkeypatch):
    """A 2xx response without the expected id is low-confidence and records one failure."""
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "5")
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "1")
    client = _make_client()
    client.session = FakeSession(FakeResponse(200, {"comment": {"text": "accepted"}}))

    result = client.create_comment("post-1", "hello")

    assert result["success"] is True
    assert result["id"] is None
    stats = client.circuit.get_stats()
    assert stats["failure_count"] == 1
    assert stats["state"] == "closed"


def test_low_confidence_does_not_open_circuit_before_threshold(monkeypatch):
    """Low-confidence logical failures use normal breaker thresholds, not force-open."""
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "10")
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "1")
    monkeypatch.setenv("MOLTBOOK_CB_FAILURES", "2")
    client = _make_client()
    client.session = FakeSession(
        FakeResponse(200, {"comment": {"text": "accepted"}}),
        FakeResponse(200, {"comment": {"text": "accepted again"}}),
    )

    first = client.create_comment("post-1", "hello")
    assert first["success"] is True
    assert client.circuit.get_stats()["state"] == "closed"

    second = client.create_comment("post-1", "hello again")
    assert second["success"] is True
    stats = client.circuit.get_stats()
    assert stats["failure_count"] == 2
    assert stats["state"] == "open"
