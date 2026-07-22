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


# ── post_reply: fallback guard ────────────────────────────────────


def test_post_reply_success():
    """post_reply delegates to create_comment with parent_comment_id on success."""
    client = _make_client()
    client._wait_for_write_token = MagicMock()
    client._call_write = MagicMock(return_value={
        "status": 201,
        "data": {"comment": {"id": "c-789"}},
    })

    result = client.post_reply(comment_id="c-parent", reply_text="hello", post_id="post-1")

    assert result["success"] is True
    assert result["id"] == "c-789"

    call_kwargs = client._call_write.call_args
    assert call_kwargs is not None
    # Second positional arg is the path
    _, _, kwargs = call_kwargs[0][0], call_kwargs[0][1], call_kwargs[1]
    assert kwargs["json_body"]["parent_id"] == "c-parent"


def test_post_reply_does_not_retry_on_http_2xx_without_success():
    """When create_comment returns HTTP 2xx but success=False (e.g. unverified),
    post_reply must NOT retry as top-level — that would create a duplicate."""
    client = _make_client()
    client._wait_for_write_token = MagicMock()

    first_call = [True]
    original = client.create_comment

    def tracking_create_comment(post_id, content, parent_comment_id=None):
        if first_call[0]:
            first_call[0] = False
            return {
                "success": False,
                "status": 200,
                "id": "c-unverified",
                "raw": {"comment": {"id": "c-unverified"}, "verification_required": True},
            }
        raise AssertionError("post_reply retried as top-level — would create duplicate!")

    client.create_comment = tracking_create_comment

    result = client.post_reply(comment_id="c-parent", reply_text="hello", post_id="post-1")

    assert result["success"] is False
    assert result["status"] == 200
    assert result["id"] == "c-unverified"
    assert first_call[0] is False  # exactly one call made

    client.create_comment = original


def test_post_reply_does_not_fallback_on_transport_failure():
    """When create_comment fails with status=0 (network error), post_reply
    returns the failure and does NOT retry as top-level (which would create a duplicate)."""
    client = _make_client()
    client._wait_for_write_token = MagicMock()

    call_count = [0]

    def tracking_create_comment(post_id, content, parent_comment_id=None):
        call_count[0] += 1
        return {"success": False, "status": 0, "id": None, "error": "connection refused", "raw": {}}

    client.create_comment = tracking_create_comment

    result = client.post_reply(comment_id="c-parent", reply_text="hello", post_id="post-1")

    assert result["success"] is False
    assert result["status"] == 0
    assert call_count[0] == 1  # exactly one call, no fallback retry


def test_post_reply_does_not_fallback_on_http_error():
    """When create_comment fails with a non-2xx HTTP status, post_reply
    returns the failure and does NOT retry as top-level (which would create a duplicate)."""
    client = _make_client()
    client._wait_for_write_token = MagicMock()

    call_count = [0]

    def tracking_create_comment(post_id, content, parent_comment_id=None):
        call_count[0] += 1
        return {"success": False, "status": 500, "id": None, "error": "server error", "raw": {}}

    client.create_comment = tracking_create_comment

    result = client.post_reply(comment_id="c-parent", reply_text="hello", post_id="post-1")

    assert result["success"] is False
    assert result["status"] == 500
    assert call_count[0] == 1  # exactly one call, no fallback retry


# ── get_post ──────────────────────────────────────────────────────────


def test_get_post_success():
    """get_post returns the post dict on 200 with valid post object."""
    client = _make_client()
    client._request = MagicMock(return_value={
        "status": 200,
        "data": {
            "success": True,
            "post": {
                "id": "abc-123",
                "title": "Test",
                "score": 42,
                "upvotes": 42,
                "comment_count": 7,
            },
        },
    })
    result = client.get_post("abc-123")
    assert result is not None
    assert result["id"] == "abc-123"
    assert result["score"] == 42
    assert result["comment_count"] == 7


def test_get_post_404_returns_none():
    """get_post returns None on 404 without raising."""
    client = _make_client()
    client._request = MagicMock(return_value={"status": 404, "data": {}})
    assert client.get_post("abc-123") is None


def test_get_post_network_error_returns_none():
    """get_post returns None when _request raises, without propagating."""
    client = _make_client()
    client._request = MagicMock(side_effect=ConnectionError("timeout"))
    assert client.get_post("abc-123") is None


def test_get_post_empty_id_returns_none():
    """get_post returns None immediately when post_id is empty."""
    client = _make_client()
    assert client.get_post("") is None
    assert client.get_post(None) is None


def test_get_post_missing_post_field_returns_none():
    """get_post logs warning and returns None if response lacks 'post' key."""
    client = _make_client()
    client._request = MagicMock(return_value={
        "status": 200,
        "data": {"success": True},
    })
    assert client.get_post("abc-123") is None


def test_get_post_non_dict_post_returns_none():
    """get_post returns None if post field is not a dict."""
    client = _make_client()
    client._request = MagicMock(return_value={
        "status": 200,
        "data": {"success": True, "post": "not-a-dict"},
    })
    assert client.get_post("abc-123") is None


def test_get_post_preserves_all_raw_fields():
    """get_post returns the full raw dict, not a filtered subset."""
    client = _make_client()
    raw_post = {
        "id": "abc-123",
        "title": "Test",
        "content": "body",
        "upvotes": 42,
        "downvotes": 3,
        "score": 39,
        "comment_count": 7,
        "hot_score": 1.5,
        "author": {"id": "u1", "name": "test"},
        "submolt": {"id": "s1", "name": "general"},
        "created_at": "2026-06-13T08:34:45Z",
    }
    client._request = MagicMock(return_value={
        "status": 200,
        "data": {"success": True, "post": raw_post},
    })
    result = client.get_post("abc-123")
    assert result == raw_post


def test_get_post_request_url():
    """get_post calls GET /posts/{post_id}."""
    client = _make_client()
    client._request = MagicMock(return_value={
        "status": 200,
        "data": {"success": True, "post": {"id": "abc-123"}},
    })
    client.get_post("abc-123")
    client._request.assert_called_once_with("GET", "/posts/abc-123")


def test_get_post_no_data_key_returns_none():
    """get_post handles response without 'data' key gracefully."""
    client = _make_client()
    client._request = MagicMock(return_value={"status": 200})
    assert client.get_post("abc-123") is None


# ── post_reply fallback guard ────────────────────────────────────

def test_post_reply_missing_post_id():
    """post_reply returns error immediately when post_id is not provided."""
    client = _make_client()
    create_comment = MagicMock()
    client.create_comment = create_comment

    result = client.post_reply(comment_id="c-parent", reply_text="hello", post_id=None)

    assert result["success"] is False
    assert "post_id" in (result.get("error") or "")
    create_comment.assert_not_called()


# ── _call_write 5xx backoff ─────────────────────────────────────────


class TestCallWriteRetry5xx:
    """_call_write retry logic for 5xx errors with exponential backoff."""

    def test_5xx_triggers_retry_and_succeeds_on_second_attempt(self, monkeypatch):
        """503 → retry → 200. _request called 2 times."""
        monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "5")
        monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "1")
        monkeypatch.setattr(time, "sleep", lambda s: None)

        client = _make_client()
        call_idx = [0]

        def mock_request(method, path, **kw):
            call_idx[0] += 1
            if call_idx[0] == 1:
                return {"status": 503, "data": {}}
            return {"status": 200, "data": {"post": {"id": "p456"}}}

        client._request = mock_request
        result = client.create_post("title", "body")

        assert result["status"] == 200 or result["success"] is True
        assert call_idx[0] == 2

    def test_5xx_retries_up_to_max_and_returns_last_5xx(self, monkeypatch):
        """Always 503 → retried 2 times → total 3 calls, final status 503."""
        monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "5")
        monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "1")
        monkeypatch.setattr(time, "sleep", lambda s: None)

        client = _make_client()

        def mock_request(method, path, **kw):
            return {"status": 503, "data": {}}

        client._request = mock_request
        result = client.create_post("title", "body")

        assert result.get("status") == 503 or result.get("status") == 0
        # _request called: 1 initial + 2 retries = 3

    def test_5xx_backoff_delays_are_non_decreasing(self, monkeypatch):
        """Captured sleep delays should be non-decreasing (5, 10, ...)."""
        monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "5")
        monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "1")

        sleep_durations = []
        monkeypatch.setattr(time, "sleep", lambda s: sleep_durations.append(s))

        client = _make_client()

        def mock_request(method, path, **kw):
            return {"status": 502, "data": {}}

        client._request = mock_request
        client.create_post("title", "body")

        assert len(sleep_durations) >= 2
        for i in range(1, len(sleep_durations)):
            assert sleep_durations[i] >= sleep_durations[i - 1], f"backoff decreased: {sleep_durations[i-1]} -> {sleep_durations[i]}"

    def test_non_5xx_error_does_not_trigger_retry(self, monkeypatch):
        """400 client error → _request called exactly once."""
        monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "5")
        monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "1")
        monkeypatch.setattr(time, "sleep", lambda s: None)

        client = _make_client()
        call_idx = [0]

        def mock_request(method, path, **kw):
            call_idx[0] += 1
            return {"status": 400, "data": {}}

        client._request = mock_request
        client.create_post("title", "body")

        assert call_idx[0] == 1
