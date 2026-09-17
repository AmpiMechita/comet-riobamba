"""Tests for the anti-dogpile monotonic per-post reply counter (AGENT_MAX_REPLIES_PER_POST).

The counter (data/replies_per_post.json) is independent of the feed payload,
monotonic (never decremented), and enforced in _safe_publish_comment — the
single publish point shared by the feed and own-post flows.
"""

from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path
import json
import pytest

from phases.phase_b import PhaseB
from phases.deps import PhaseBDeps

UUID_POST_A = "aaaaaaaa-1111-4aaa-8aaa-aaaaaaaaaaaa"
UUID_POST_B = "bbbbbbbb-2222-4bbb-8bbb-bbbbbbbbbbbb"

CONTENT = (
    "In production we measured that circuit breaker recovery windows of "
    "several seconds reduce cascading failures when the downstream retry "
    "budget is exhausted under sustained load, so the architecture should "
    "default to conservative timeouts."
)


def _make_pb(max_comments_per_post=3, max_comments_per_day=6,
             max_replies_per_cycle=2, agent_name="COMET-RIOBAMBA"):
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={
            "max_comments_per_post": max_comments_per_post,
            "max_comments_per_day": max_comments_per_day,
            "max_comment_replies_per_cycle": max_replies_per_cycle,
            "max_feed_replies_per_day": 3,
            "delay_between_comments": 0,
        },
        agent_name=agent_name,
        get_comments_today=lambda: 0,
        increment_comments_today=lambda: 0,
    )
    pb = PhaseB(deps)
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(return_value=CONTENT)
    pb.api = MagicMock()
    pb.api.create_comment.return_value = {"success": True, "id": "new-comment-id", "status": 201}
    pb._memory = MagicMock()
    pb._memory.get_memory.return_value = None
    return pb


@pytest.fixture
def _redirect_paths(tmp_path):
    """Redirect all file paths to temp, restoring originals after test."""
    import services.conversation_state as cs
    import services.dedup_store as ds
    import services.research_agenda as ra
    import phases.phase_b as pb
    import services.reply_cap as rcap
    orig_cs = cs.CONVERSATIONS_PATH
    orig_rep = pb._REPLIED_IDS_PATH
    orig_com = pb._COMMENTED_POSTS_PATH
    orig_agc = pb._AGENT_COMMENT_IDS_PATH
    orig_upv = pb._UPVOTED_POST_IDS_PATH
    orig_fol = pb._FOLLOWED_AGENTS_PATH
    orig_rpp = rcap._REPLIES_PER_POST_PATH
    orig_dedup = ds.DedupStore._default_db_path
    orig_agenda = ra.AGENDA_PATH
    cs.CONVERSATIONS_PATH = tmp_path / "conversations.json"
    pb._REPLIED_IDS_PATH = tmp_path / "replied_comment_ids.json"
    pb._COMMENTED_POSTS_PATH = tmp_path / "commented_post_ids.json"
    pb._AGENT_COMMENT_IDS_PATH = tmp_path / "agent_comment_ids.json"
    pb._UPVOTED_POST_IDS_PATH = tmp_path / "upvoted_post_ids.json"
    pb._FOLLOWED_AGENTS_PATH = tmp_path / "followed_agents.json"
    rcap._REPLIES_PER_POST_PATH = tmp_path / "replies_per_post.json"
    ds.DedupStore._default_db_path = tmp_path / "comet_dedup.db"
    ra.AGENDA_PATH = tmp_path / "research_agenda.json"

    # Prevent JSON migration from loading stale real-world data
    _orig_json_files = {}
    for _ns, _jpath, _fmt in ds._JSON_NAMESPACES:
        _p = Path(_jpath)
        if _p.exists():
            _orig_json_files[_jpath] = _p.read_bytes()
            _p.unlink()

    yield

    cs.CONVERSATIONS_PATH = orig_cs
    pb._REPLIED_IDS_PATH = orig_rep
    pb._COMMENTED_POSTS_PATH = orig_com
    pb._AGENT_COMMENT_IDS_PATH = orig_agc
    pb._UPVOTED_POST_IDS_PATH = orig_upv
    pb._FOLLOWED_AGENTS_PATH = orig_fol
    rcap._REPLIES_PER_POST_PATH = orig_rpp
    ds.DedupStore._default_db_path = orig_dedup
    ra.AGENDA_PATH = orig_agenda

    # Restore backed-up JSON files
    for _jpath, _data in _orig_json_files.items():
        Path(_jpath).write_bytes(_data)


def _counter_file(pb) -> Path:
    return Path(pb._replies_per_post_path)


class TestSharedPhaseBCBudget:
    @pytest.mark.asyncio
    async def test_phase_b_and_phase_c_share_per_post_budget(self, _redirect_paths, tmp_path):
        """Phase B publishes 2 on a post; Phase C's 1st reply passes (total 3)
        and its 2nd is blocked — one shared 3/post budget across phases."""
        from phases.engagement.responder import Responder
        import services.reply_cap as rcap

        counter_path = tmp_path / "replies_per_post.json"
        pb = _make_pb()
        pb._replies_per_post_path = counter_path

        # Phase B: 2 publishes on the same post
        assert pb._safe_publish_comment(UUID_POST_A, CONTENT) is not None
        assert pb._safe_publish_comment(UUID_POST_A, CONTENT) is not None

        res = Responder(
            model_cascade=MagicMock(),
            write_policy=MagicMock(),
            moltbook_client=MagicMock(),
            tracker=MagicMock(),
        )
        res.moltbook_client.create_comment.return_value = {
            "success": True, "status": 201, "id": "c-phase-c", "raw": {},
        }

        # Phase C: 1st attempt passes (total 3), 2nd is blocked
        first = await res.publish_reply(UUID_POST_A, "reply text", {}, {})
        second = await res.publish_reply(UUID_POST_A, "reply text", {}, {})

        assert first is not None, "1st Phase C reply must publish (budget 2/3 -> 3/3)"
        assert second is None, "2nd Phase C reply must be blocked (shared budget 3/3)"
        assert res.moltbook_client.create_comment.call_count == 1, (
            "Phase C must only create one comment"
        )
        stored = json.loads(counter_path.read_text(encoding="utf-8"))
        assert stored[UUID_POST_A] == 3, f"Shared counter must be 3, got {stored.get(UUID_POST_A)}"


class TestAntiDogpile:
    def test_same_post_five_attempts_publishes_three_blocks_two(self, _redirect_paths, tmp_path):
        """5 attempts to publish to the SAME post: 3 publish, 2 blocked (default cap 3)."""
        pb = _make_pb()
        pb._replies_per_post_path = tmp_path / "replies_per_post.json"

        results = [pb._safe_publish_comment(UUID_POST_A, CONTENT) for _ in range(5)]

        published = [r for r in results if r is not None]
        assert len(published) == 3, f"Expected 3 published, got {len(published)}"
        assert pb.api.create_comment.call_count == 3, (
            f"create_comment must be called exactly 3 times, got {pb.api.create_comment.call_count}"
        )
        stored = json.loads(_counter_file(pb).read_text(encoding="utf-8"))
        assert stored[UUID_POST_A] == 3

    def test_different_post_id_has_independent_counter(self, _redirect_paths, tmp_path):
        """A different post_id is unaffected by another post's counter."""
        pb = _make_pb()
        pb._replies_per_post_path = tmp_path / "replies_per_post.json"

        results_a = [pb._safe_publish_comment(UUID_POST_A, CONTENT) for _ in range(3)]
        results_b = [pb._safe_publish_comment(UUID_POST_B, CONTENT) for _ in range(3)]

        assert all(r is not None for r in results_a)
        assert all(r is not None for r in results_b)
        assert pb.api.create_comment.call_count == 6
        stored = json.loads(_counter_file(pb).read_text(encoding="utf-8"))
        assert stored[UUID_POST_A] == 3
        assert stored[UUID_POST_B] == 3

        # Post A still blocked at cap
        assert pb._safe_publish_comment(UUID_POST_A, CONTENT) is None

    def test_counter_persists_between_instances(self, _redirect_paths, tmp_path):
        """Counter survives re-instantiation: a fresh PhaseB keeps blocking."""
        counter_path = tmp_path / "replies_per_post.json"

        pb1 = _make_pb()
        pb1._replies_per_post_path = counter_path
        for _ in range(3):
            assert pb1._safe_publish_comment(UUID_POST_A, CONTENT) is not None
        assert pb1._safe_publish_comment(UUID_POST_A, CONTENT) is None

        # New instance (new "cycle"), same counter file
        pb2 = _make_pb()
        pb2._replies_per_post_path = counter_path
        assert pb2._safe_publish_comment(UUID_POST_A, CONTENT) is None, (
            "Fresh instance must keep blocking the capped post"
        )
        # But a different post on the fresh instance is free
        assert pb2._safe_publish_comment(UUID_POST_B, CONTENT) is not None

    def test_reconcile_never_decrements_counter(self, _redirect_paths, tmp_path):
        """_reconcile_deleted_agent_comments must NOT touch the monotonic counter."""
        pb = _make_pb()
        pb._replies_per_post_path = tmp_path / "replies_per_post.json"
        for _ in range(3):
            assert pb._safe_publish_comment(UUID_POST_A, CONTENT) is not None
        before = json.loads(_counter_file(pb).read_text(encoding="utf-8"))[UUID_POST_A]
        assert before == 3

        pb._reconcile_deleted_agent_comments(UUID_POST_A)

        after = json.loads(_counter_file(pb).read_text(encoding="utf-8"))[UUID_POST_A]
        assert after == before, "Reconcile must not decrement the counter"

    def test_failed_publish_does_not_increment_counter(self, _redirect_paths, tmp_path):
        """Non-2xx / spam responses must not consume the per-post budget."""
        pb = _make_pb()
        pb._replies_per_post_path = tmp_path / "replies_per_post.json"
        pb.api.create_comment.return_value = {"success": False, "status": 500, "id": None}

        result1 = pb._safe_publish_comment(UUID_POST_A, CONTENT)
        result2 = pb._safe_publish_comment(UUID_POST_A, CONTENT)

        assert result1 is not None and result2 is not None, "Failure results pass through"
        assert pb.api.create_comment.call_count == 2
        assert not _counter_file(pb).exists(), "No counter file should be created on failures"


# ── Durable per-comment dedup ────────────────────────────────

class TestDurableCommentDedup:
    def test_same_comment_id_blocked_after_mark_with_reinstantiation(self, tmp_path):
        """Second attempt to reply to the same comment_id is blocked by the
        persisted set, even after 're-instantiating' (reloading from disk)."""
        dedup_path = tmp_path / "replied_comment_ids_durable.json"
        from services.reply_cap import has_replied_to_comment, mark_replied_to_comment

        dedup_key = "post-uuid-1234:0f74c66e-1234-5678-9012-abcdef123456"
        assert not has_replied_to_comment(dedup_key, dedup_path)
        mark_replied_to_comment(dedup_key, dedup_path)
        assert has_replied_to_comment(dedup_key, dedup_path)

        assert has_replied_to_comment(dedup_key, dedup_path), (
            "After re-load, the same key must still be blocked"
        )
        assert not has_replied_to_comment("post-uuid-1234:other-id-abc", dedup_path)


# ── Interlocutors ledger persistence ─────────────────────────

class TestInterlocutorsLedger:
    def test_record_interaction_accumulates_and_persists(self, tmp_path):
        """record_interaction increments count, and the ledger survives
        re-instantiation (fresh load from the same path)."""
        from services.interlocutors import (
            record_interaction, get_interaction_count,
        )
        path = tmp_path / "interlocutors.json"

        author = {"name": "user_x"}
        for _ in range(3):
            record_interaction(author, on_our_post=True, path=path)
        assert get_interaction_count(author, path=path) == 3

        # Same path, fresh read (re-instantiation)
        assert get_interaction_count({"name": "user_x"}, path=path) == 3
        assert get_interaction_count({"name": "user_y"}, path=path) == 0

        # Feed interaction increments
        record_interaction("user_x", on_our_post=False, path=path)
        assert get_interaction_count("user_x", path=path) == 4
