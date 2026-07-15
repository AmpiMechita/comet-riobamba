"""Tests for Phase B author handling bug fix.

Verifies _get_author_name handles dict/str/missing author without crashing,
and _process_own_post correctly distinguishes own vs other-agent comments.
"""

import uuid

from unittest.mock import MagicMock, AsyncMock, patch
import pytest

from phases.phase_b import PhaseB
from phases.deps import PhaseBDeps

# UUIDs válidos para fixtures de test
_POST_ID_1 = "a1b2c3d4-0000-4000-8000-000000000001"
_POST_ID_2 = "a1b2c3d4-0000-4000-8000-000000000002"


def _make_deps(agent_name: str = "COMET-RIOBAMBA", get_comments_today=None, increment_comments_today=None):
    return PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={
            "max_comments_per_post": 3,
            "max_comments_per_day": 6,
            "max_comment_replies_per_cycle": 2,
            "delay_between_comments": 0,
        },
        agent_name=agent_name,
        get_comments_today=get_comments_today or (lambda: 0),
        increment_comments_today=increment_comments_today or (lambda: 0),
    )


@pytest.fixture
def pb():
    deps = _make_deps()
    pb = PhaseB(deps)
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(return_value="In production we measured that architecture patterns with circuit breakers reduce cascade failures by 73% at p99 latency under 200ms.")
    pb.api = MagicMock()
    pb.api.create_comment.return_value = {"success": True, "id": "reply-0"}
    pb._replied_comment_ids = set()
    pb._replied_topic_fingerprints = set()
    pb._last_comment_per_thread = {}
    return pb


# ============================================================
# Tests for _get_author_name
# ============================================================

class TestGetAuthorName:
    def test_author_as_dict_with_name(self):
        comment = {"author": {"name": "comet_riobamba", "id": "123"}}
        result = PhaseB._get_author_name(comment)
        assert result == "comet_riobamba"

    def test_author_as_dict_with_username_only(self):
        comment = {"author": {"username": "other_agent", "id": "456"}}
        result = PhaseB._get_author_name(comment)
        assert result == "other_agent"

    def test_author_as_dict_missing_name(self):
        comment = {"author": {"id": "789"}}
        result = PhaseB._get_author_name(comment)
        assert result == ""

    def test_author_as_string(self):
        comment = {"author": "some_agent"}
        result = PhaseB._get_author_name(comment)
        assert result == "some_agent"

    def test_author_empty_string(self):
        comment = {"author": ""}
        result = PhaseB._get_author_name(comment)
        assert result == ""

    def test_author_missing(self):
        comment = {"content": "hello"}
        result = PhaseB._get_author_name(comment)
        assert result == ""

    def test_author_none(self):
        comment = {"author": None}
        result = PhaseB._get_author_name(comment)
        assert result == ""

    def test_author_as_dict_empty_name(self):
        comment = {"author": {"name": "", "username": ""}}
        result = PhaseB._get_author_name(comment)
        assert result == ""


# ============================================================
# Tests for is-own-comment detection (no crash)
# ============================================================

@pytest.fixture(autouse=True)
def _redirect_conversations(tmp_path):
    """Redirect conversation_state path to temp."""
    import services.conversation_state as cs
    orig = cs.CONVERSATIONS_PATH
    cs.CONVERSATIONS_PATH = tmp_path / "conversations.json"
    yield
    cs.CONVERSATIONS_PATH = orig


@pytest.fixture(autouse=True)
def _redirect_replied_ids(tmp_path):
    """Redirect replied_comment_ids to temp."""
    import phases.phase_b as pb
    orig = pb._REPLIED_IDS_PATH
    pb._REPLIED_IDS_PATH = tmp_path / "replied_comment_ids.json"
    yield
    pb._REPLIED_IDS_PATH = orig


@pytest.fixture(autouse=True)
def _redirect_dedup_store(tmp_path):
    """Redirect DedupStore to temp to avoid stale data from previous runs."""
    import services.dedup_store as ds
    orig = ds.DedupStore._default_db_path
    ds.DedupStore._default_db_path = tmp_path / "comet_dedup_test.db"
    yield
    ds.DedupStore._default_db_path = orig


class TestProcessOwnPostAuthorHandling:
    """Integration-level tests: feed comment lists into _process_own_post."""

    @pytest.mark.asyncio
    async def test_own_comment_dict_author_skipped(self, pb):
        """Author as dict with our agent name → should skip, not crash."""
        pb.api.fetch_post_comments.return_value = [
            {
                "id": "c1",
                "author": {"name": "comet_riobamba", "id": "42"},
                "content": "Great point!",
                "text": "Great point!",
            }
        ]
        result = await pb._process_own_post(_POST_ID_1)
        assert result == []

    @pytest.mark.asyncio
    async def test_other_agent_dict_author_not_skipped(self, pb):
        """Author as dict with other agent → should be processed, not crash."""
        pb.api.fetch_post_comments.return_value = [
            {
                "id": "c2",
                "author": {"name": "esperanza_valorismo", "id": "99"},
                "content": "How does the cascade handle 429 errors?",
                "text": "How does the cascade handle 429 errors?",
            }
        ]
        result = await pb._process_own_post(_POST_ID_1)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_author_as_string_other_agent(self, pb):
        """Author as plain string (legacy format) → should still work."""
        pb.api.fetch_post_comments.return_value = [
            {
                "id": "c3",
                "author": "some_other_agent",
                "content": "What is the max posts per day?",
                "text": "What is the max posts per day?",
            }
        ]
        result = await pb._process_own_post(_POST_ID_1)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_missing_author_skipped(self, pb):
        """Comment with no author at all → should be skipped, not crash."""
        pb.api.fetch_post_comments.return_value = [
            {
                "id": "c4",
                "content": "Hello!",
                "text": "Hello!",
            }
        ]
        result = await pb._process_own_post(_POST_ID_1)
        assert result == []

    @pytest.mark.asyncio
    async def test_mixed_authors_no_own(self, pb):
        """Multiple comments, none from us → process all without crash."""
        pb.api.fetch_post_comments.return_value = [
            {
                "id": "c5",
                "author": {"name": "agent_one", "id": "1"},
                "content": "First question about architecture?",
                "text": "First question about architecture?",
            },
            {
                "id": "c6",
                "author": {"name": "agent_two", "id": "2"},
                "content": "Second question about performance?",
                "text": "Second question about performance?",
            },
        ]
        pb.llm.generate = AsyncMock(return_value="In production we measured that architecture patterns with circuit breakers reduce cascade failures by 73% at p99 latency under 200ms.")
        result = await pb._process_own_post(_POST_ID_1)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_own_and_other_mixed(self, pb):
        """Our own comments intermixed with others → only reply to others, no crash."""
        pb.api.fetch_post_comments.return_value = [
            {
                "id": "c7",
                "author": {"name": "comet_riobamba", "id": "42"},
                "content": "I think the answer is yes.",
                "text": "I think the answer is yes.",
            },
            {
                "id": "c8",
                "author": {"name": "other_agent", "id": "3"},
                "content": "But what about edge cases in production?",
                "text": "But what about edge cases in production?",
            },
        ]
        pb.llm.generate = AsyncMock(return_value="We observed edge cases in production where circuit breakers with 150ms timeout patterns reduce cascade failures by 73% under peak load.")
        result = await pb._process_own_post(_POST_ID_1)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_empty_content_reply_not_crash(self, pb):
        """Comment with empty content from another agent → skip, not crash."""
        pb.api.fetch_post_comments.return_value = [
            {
                "id": "c9",
                "author": {"name": "other_agent", "id": "4"},
                "content": "",
                "text": "",
            }
        ]
        result = await pb._process_own_post(_POST_ID_1)
        assert result == []

    @pytest.mark.asyncio
    async def test_author_dict_without_name_username(self, pb):
        """Author dict with neither name nor username → treat as empty."""
        pb.api.fetch_post_comments.return_value = [
            {
                "id": "c10",
                "author": {"id": "5", "role": "user"},
                "content": "Any questions?",
                "text": "Any questions?",
            }
        ]
        result = await pb._process_own_post(_POST_ID_1)
        assert result is not None  # Should not crash
