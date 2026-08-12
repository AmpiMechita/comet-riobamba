"""Tests for home dashboard, strategic upvotes, following, and semantic search."""
import json
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from services.moltbook_api_client import MoltbookAPIClient
from phases.phase_b import PhaseB, _load_upvoted_post_ids, _save_upvoted_post_ids, _load_followed_agent_names, _save_followed_agent_names
from phases.deps import PhaseBDeps


# ====================================================================
# Helpers
# ====================================================================

def _make_client():
    return MoltbookAPIClient(base_url="http://test.com", api_key="sekret")


def _make_pb(**overrides):
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={
            "max_comments_per_post": 3,
            "max_comments_per_day": 6,
            "max_comment_replies_per_cycle": 2,
            "max_feed_replies_per_day": 3,
            "delay_between_comments": 0,
            **overrides,
        },
        agent_name="comet_riobamba",
        get_comments_today=lambda: 0,
        increment_comments_today=lambda: 0,
        pending_home_post_ids=set(),
    )
    pb = PhaseB(deps)
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(return_value="A thoughtful technical reply.")
    pb.api = MagicMock()
    pb.api.create_comment.return_value = {"success": True, "id": "new-comment-id", "status": 201}
    pb.api.upvote_post.return_value = True
    pb.api.follow_agent.return_value = True
    pb.api.semantic_search.return_value = []
    return pb


# ====================================================================
# 1. API Client: fetch_home_dashboard
# ====================================================================


def test_home_dashboard_success(monkeypatch):
    client = _make_client()
    def mock_request(method, path, **kw):
        return {
            "status": 200,
            "data": {
                "your_account": {"name": "comet_riobamba", "karma": 42, "unread_notification_count": 3},
                "activity_on_your_posts": [
                    {"post_id": "p1", "post_title": "Post 1", "new_notification_count": 2, "latest_commenters": ["user_a"]},
                    {"post_id": "p2", "post_title": "Post 2", "new_notification_count": 0, "latest_commenters": []},
                ],
                "latest_moltbook_announcement": {"id": "ann-1", "title": "New features!"},
            },
        }
    client._request = mock_request
    home = client.fetch_home_dashboard()
    assert home["karma"] == 42
    assert home["unread_notifications"] == 3
    assert home["active_posts"] == 2
    assert len(home["activity_on_your_posts"]) == 2
    assert home["activity_on_your_posts"][0]["title"] == "Post 1"
    assert home["activity_on_your_posts"][0]["authors"] == ["user_a"]
    assert home["latest_moltbook_announcement"]["id"] == "ann-1"


def test_home_dashboard_fails_gracefully(monkeypatch):
    client = _make_client()
    def mock_request(method, path, **kw):
        raise RuntimeError("network error")
    client._request = mock_request
    home = client.fetch_home_dashboard()
    assert home == {}


def test_home_dashboard_http_error(monkeypatch):
    client = _make_client()
    def mock_request(method, path, **kw):
        return {"status": 500, "data": {}}
    client._request = mock_request
    home = client.fetch_home_dashboard()
    assert home == {}


# ====================================================================
# 2. API Client: upvote_post
# ====================================================================


def test_upvote_post_success(monkeypatch):
    client = _make_client()
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "5")
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "1")
    def mock_call_write(method, path, **kw):
        return {"status": 200, "data": {}}
    client._call_write = mock_call_write
    assert client.upvote_post("post-123") is True


def test_upvote_post_fails_gracefully(monkeypatch):
    client = _make_client()
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "5")
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "1")
    def mock_call_write(method, path, **kw):
        raise RuntimeError("timeout")
    client._call_write = mock_call_write
    assert client.upvote_post("post-123") is False


def test_upvote_post_empty_id():
    client = _make_client()
    assert client.upvote_post("") is False
    assert client.upvote_post(None) is False


# ====================================================================
# 3. API Client: follow_agent
# ====================================================================


def test_follow_agent_success(monkeypatch):
    client = _make_client()
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_CALLS", "5")
    monkeypatch.setenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS", "1")
    def mock_call_write(method, path, **kw):
        return {"status": 200, "data": {}}
    client._call_write = mock_call_write
    assert client.follow_agent("other_agent") is True


def test_follow_agent_fails_gracefully(monkeypatch):
    client = _make_client()
    def mock_call_write(method, path, **kw):
        raise RuntimeError("timeout")
    client._call_write = mock_call_write
    assert client.follow_agent("other_agent") is False


def test_follow_agent_empty_name():
    client = _make_client()
    assert client.follow_agent("") is False
    assert client.follow_agent("   ") is False


# ====================================================================
# 4. API Client: semantic_search
# ====================================================================


def test_semantic_search_success(monkeypatch):
    client = _make_client()
    def mock_request(method, path, **kw):
        return {
            "status": 200,
            "data": {
                "items": [
                    {"id": "s1", "title": "Result 1", "content": "Body 1", "author": "user1", "submolt": "agents"},
                    {"id": "s2", "title": "Result 2", "content": "Body 2", "author": "user2", "submolt": "ai"},
                ],
            },
        }
    client._request = mock_request
    results = client.semantic_search("agent failure mode")
    assert len(results) == 2
    assert results[0]["id"] == "s1"
    assert results[0]["_search_query"] == "agent failure mode"


def test_semantic_search_empty_query():
    client = _make_client()
    assert client.semantic_search("") == []
    assert client.semantic_search("   ") == []


def test_semantic_search_fails_gracefully(monkeypatch):
    client = _make_client()
    def mock_request(method, path, **kw):
        raise RuntimeError("API down")
    client._request = mock_request
    assert client.semantic_search("test") == []


# ====================================================================
# 5. Phase B: _maybe_upvote
# ====================================================================


def test_maybe_upvote_happy_path(monkeypatch):
    monkeypatch.setenv("UPVOTES_ENABLED", "true")
    monkeypatch.setenv("MAX_UPVOTES_PER_CYCLE", "3")
    pb = _make_pb()
    pb.api.upvote_post.return_value = True
    pb._upvoted_post_ids = set()
    pb._upvotes_this_cycle = 0

    pb._maybe_upvote("post-1", "HIGH_VALUE")
    assert "post-1" in pb._upvoted_post_ids
    assert pb._upvotes_this_cycle == 1
    pb.api.upvote_post.assert_called_once_with("post-1")


def test_maybe_upvote_skip_already_upvoted(monkeypatch):
    monkeypatch.setenv("UPVOTES_ENABLED", "true")
    pb = _make_pb()
    pb._upvoted_post_ids = {"post-1"}
    pb._upvotes_this_cycle = 0
    pb._maybe_upvote("post-1", "HIGH_VALUE")
    pb.api.upvote_post.assert_not_called()


def test_maybe_upvote_skip_trivial(monkeypatch):
    monkeypatch.setenv("UPVOTES_ENABLED", "true")
    pb = _make_pb()
    pb._upvoted_post_ids = set()
    pb._maybe_upvote("post-1", "TRIVIAL")
    pb.api.upvote_post.assert_not_called()


def test_maybe_upvote_skip_cycle_limit(monkeypatch):
    monkeypatch.setenv("UPVOTES_ENABLED", "true")
    monkeypatch.setenv("MAX_UPVOTES_PER_CYCLE", "2")
    pb = _make_pb()
    pb._upvoted_post_ids = set()
    pb._upvotes_this_cycle = 2
    pb._maybe_upvote("post-1", "HIGH_VALUE")
    pb.api.upvote_post.assert_not_called()


def test_maybe_upvote_disabled(monkeypatch):
    monkeypatch.setenv("UPVOTES_ENABLED", "false")
    pb = _make_pb()
    pb._maybe_upvote("post-1", "HIGH_VALUE")
    pb.api.upvote_post.assert_not_called()


def test_maybe_upvote_api_failure(monkeypatch):
    monkeypatch.setenv("UPVOTES_ENABLED", "true")
    pb = _make_pb()
    pb._upvoted_post_ids = set()
    pb.api.upvote_post.return_value = False
    pb._maybe_upvote("post-1", "HIGH_VALUE")
    # Not added to set, not counted
    assert "post-1" not in pb._upvoted_post_ids
    assert pb._upvotes_this_cycle == 0


# ====================================================================
# 6. Phase B: _maybe_follow_author  (new simplified signature)
# ====================================================================


def test_maybe_follow_author_happy_path(monkeypatch):
    monkeypatch.setenv("FOLLOWING_ENABLED", "true")
    monkeypatch.setenv("MAX_FOLLOWS_PER_CYCLE", "2")
    pb = _make_pb()
    pb._followed_agent_names = set()
    pb._follows_this_cycle = 0
    pb.api.follow_agent.return_value = True

    pb._maybe_follow_author("other_agent")
    assert "other_agent" in pb._followed_agent_names
    assert pb._follows_this_cycle == 1
    pb.api.follow_agent.assert_called_once_with("other_agent")


def test_maybe_follow_author_skip_self(monkeypatch):
    monkeypatch.setenv("FOLLOWING_ENABLED", "true")
    pb = _make_pb()
    pb._followed_agent_names = set()
    pb._follows_this_cycle = 0
    pb._maybe_follow_author("comet_riobamba")
    pb.api.follow_agent.assert_not_called()


def test_maybe_follow_author_skip_already_following(monkeypatch):
    monkeypatch.setenv("FOLLOWING_ENABLED", "true")
    pb = _make_pb()
    pb._followed_agent_names = {"other_agent"}
    pb._follows_this_cycle = 0
    pb._maybe_follow_author("other_agent")
    pb.api.follow_agent.assert_not_called()


def test_maybe_follow_author_skip_cycle_limit(monkeypatch):
    monkeypatch.setenv("FOLLOWING_ENABLED", "true")
    monkeypatch.setenv("MAX_FOLLOWS_PER_CYCLE", "2")
    pb = _make_pb()
    pb._followed_agent_names = set()
    pb._follows_this_cycle = 2
    pb._maybe_follow_author("other_agent")
    pb.api.follow_agent.assert_not_called()


def test_maybe_follow_author_disabled(monkeypatch):
    monkeypatch.setenv("FOLLOWING_ENABLED", "false")
    pb = _make_pb()
    pb._maybe_follow_author("other_agent")
    pb.api.follow_agent.assert_not_called()


def test_maybe_follow_author_api_failure(monkeypatch):
    monkeypatch.setenv("FOLLOWING_ENABLED", "true")
    monkeypatch.setenv("MAX_FOLLOWS_PER_CYCLE", "2")
    pb = _make_pb()
    pb._followed_agent_names = set()
    pb._follows_this_cycle = 0
    pb.api.follow_agent.return_value = False
    pb._maybe_follow_author("other_agent")
    assert "other_agent" not in pb._followed_agent_names
    assert pb._follows_this_cycle == 0


def test_maybe_follow_author_empty_name(monkeypatch):
    monkeypatch.setenv("FOLLOWING_ENABLED", "true")
    pb = _make_pb()
    pb._maybe_follow_author("")
    pb.api.follow_agent.assert_not_called()


# ====================================================================
# 7. Phase B: _derive_search_queries
# ====================================================================


def test_derive_search_queries_from_agenda(monkeypatch, tmp_path):
    monkeypatch.setenv("SEMANTIC_SEARCH_MAX_QUERIES", "2")
    agenda_file = Path("data/research_agenda.json")
    orig_content = agenda_file.read_text(encoding="utf-8") if agenda_file.exists() else None
    try:
        agenda_file.write_text(json.dumps({
            "pending_topics": [
                {"topic": "Observability gaps in long-running agent loops", "source": "test"},
                {"topic": "Model cascade reliability patterns", "source": "test"},
                {"topic": "Third topic that should not appear due to max_queries", "source": "test"},
            ]
        }, ensure_ascii=False), encoding="utf-8")
        qs = PhaseB._derive_search_queries()
        assert len(qs) == 2
        assert "Observability gaps in long-running agent loops" in qs
        assert "Model cascade reliability patterns" in qs
    finally:
        if orig_content:
            agenda_file.write_text(orig_content, encoding="utf-8")
        else:
            agenda_file.unlink(missing_ok=True)


def test_derive_search_queries_roadmap_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("SEMANTIC_SEARCH_MAX_QUERIES", "1")
    agenda_file = Path("data/research_agenda.json")
    roadmap_file = Path("data/topic_roadmap.json")
    orig_agenda = agenda_file.read_text(encoding="utf-8") if agenda_file.exists() else None
    orig_roadmap = roadmap_file.read_text(encoding="utf-8") if roadmap_file.exists() else None
    try:
        # Clear research_agenda so fallback is tested
        agenda_file.write_text(json.dumps({"pending_topics": []}), encoding="utf-8")
        roadmap_file.write_text(json.dumps({
            "series": [{"id": "s1", "weight": 3, "topics": ["ReAct patterns in Moltbook agents"]}]
        }), encoding="utf-8")
        qs = PhaseB._derive_search_queries()
        assert len(qs) == 1
        assert "ReAct patterns in Moltbook agents" in qs
    finally:
        if orig_agenda:
            agenda_file.write_text(orig_agenda, encoding="utf-8")
        else:
            agenda_file.unlink(missing_ok=True)
        if orig_roadmap:
            roadmap_file.write_text(orig_roadmap, encoding="utf-8")
        else:
            roadmap_file.unlink(missing_ok=True)


def test_derive_search_queries_env_fallback(monkeypatch):
    monkeypatch.setenv("SEMANTIC_SEARCH_QUERIES", "test query,another query")
    monkeypatch.setenv("SEMANTIC_SEARCH_MAX_QUERIES", "2")
    qs = PhaseB._derive_search_queries()
    assert len(qs) >= 1  # will use agenda/roadmap first if available, env as last resort


# ====================================================================
# 8. Phase B: _fetch_semantic_search_posts  (mock _derive_search_queries)
# ====================================================================


def test_semantic_search_fetch_returns_posts(monkeypatch):
    monkeypatch.setenv("SEMANTIC_SEARCH_ENABLED", "true")
    monkeypatch.setenv("SEMANTIC_SEARCH_MAX_QUERIES", "1")
    monkeypatch.setenv("SEMANTIC_SEARCH_QUERIES", "test query")
    pb = _make_pb()
    pb.api.semantic_search.return_value = [
        {"id": "sp1", "title": "Search 1", "content": "Body", "author": "u1", "submolt": "agents"},
    ]
    import asyncio
    results = asyncio.run(pb._fetch_semantic_search_posts())
    assert len(results) == 1
    assert results[0]["id"] == "sp1"


def test_semantic_search_fetch_deduplicates(monkeypatch):
    monkeypatch.setenv("SEMANTIC_SEARCH_ENABLED", "true")
    monkeypatch.setenv("SEMANTIC_SEARCH_MAX_QUERIES", "2")
    monkeypatch.setenv("SEMANTIC_SEARCH_QUERIES", "q1,q2")
    pb = _make_pb()
    pb.api.semantic_search.return_value = [
        {"id": "sp1", "title": "Same", "content": "Body", "author": "u1", "submolt": "agents"},
    ]
    import asyncio
    results = asyncio.run(pb._fetch_semantic_search_posts())
    assert len(results) == 1


def test_semantic_search_fetch_filters_blocked_submolt(monkeypatch):
    monkeypatch.setenv("SEMANTIC_SEARCH_ENABLED", "true")
    monkeypatch.setenv("SEMANTIC_SEARCH_MAX_QUERIES", "1")
    monkeypatch.setenv("SEMANTIC_SEARCH_QUERIES", "test")
    pb = _make_pb()
    pb.api.semantic_search.return_value = [
        {"id": "sp1", "title": "Bad", "content": "Body", "author": "u1", "submolt": "introductions"},
    ]
    import asyncio
    results = asyncio.run(pb._fetch_semantic_search_posts())
    assert len(results) == 0


def test_semantic_search_fetch_disabled(monkeypatch):
    monkeypatch.setenv("SEMANTIC_SEARCH_ENABLED", "false")
    pb = _make_pb()
    import asyncio
    results = asyncio.run(pb._fetch_semantic_search_posts())
    assert results == []


# ====================================================================
# 9. Upvote and follow persistence
# ====================================================================


def test_upvote_persistence_roundtrip(tmp_path):
    import phases.phase_b.orchestrator as pbo
    orig_path = pbo._UPVOTED_POST_IDS_PATH
    pbo._UPVOTED_POST_IDS_PATH = tmp_path / "upvoted_post_ids.json"
    try:
        ids = {"p1", "p2", "p3"}
        _save_upvoted_post_ids(ids)
        loaded = _load_upvoted_post_ids()
        assert loaded == ids
    finally:
        pbo._UPVOTED_POST_IDS_PATH = orig_path


def test_follow_persistence_roundtrip(tmp_path):
    import phases.phase_b.orchestrator as pbo
    orig_path = pbo._FOLLOWED_AGENTS_PATH
    pbo._FOLLOWED_AGENTS_PATH = tmp_path / "followed_agents.json"
    try:
        names = {"agent1", "agent2"}
        _save_followed_agent_names(names)
        loaded = _load_followed_agent_names()
        assert loaded == names
    finally:
        pbo._FOLLOWED_AGENTS_PATH = orig_path


def test_follow_persistence_dict_format(tmp_path):
    import phases.phase_b.orchestrator as pbo
    orig_path = pbo._FOLLOWED_AGENTS_PATH
    pbo._FOLLOWED_AGENTS_PATH = tmp_path / "followed_agents_dict.json"
    try:
        names = {"agent1", "agent2"}
        _save_followed_agent_names(names)
        raw = json.loads((tmp_path / "followed_agents_dict.json").read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert "following" in raw
        assert "unfollowed" in raw
        assert set(raw["following"]) == names
        assert raw["unfollowed"] == []
    finally:
        pbo._FOLLOWED_AGENTS_PATH = orig_path


def test_follow_persistence_loads_old_list_format(tmp_path):
    import phases.phase_b.orchestrator as pbo
    orig_path = pbo._FOLLOWED_AGENTS_PATH
    pbo._FOLLOWED_AGENTS_PATH = tmp_path / "followed_agents_old.json"
    try:
        (tmp_path / "followed_agents_old.json").write_text(
            json.dumps(["agent1", "agent2"]), encoding="utf-8")
        loaded = _load_followed_agent_names()
        assert loaded == {"agent1", "agent2"}
    finally:
        pbo._FOLLOWED_AGENTS_PATH = orig_path
