"""Tests for Phase B deduplication, limit enforcement, priority, and multi-comment."""

from unittest.mock import MagicMock, AsyncMock, call
from pathlib import Path
import pytest

from phases.phase_b import PhaseB
from phases.deps import PhaseBDeps


_reply_counter = 0

_REPLIES = [
    "In production we observed that the architecture pattern observed in this design effectively prevents cascading failures.",
    "We measured that careful caching with proper framework design improves overall throughput under peak load conditions.",
    "The design strategy for routing and scaling we observed uses a measured approach with proper failover architecture.",
    "Our production data observed that automated failover with detection patterns reduces downtime through careful design.",
]
_counter = [0]


def _incrementing_reply(texts=None):
    """Return a string reply (for use as side_effect in AsyncMock)."""
    if texts is not None:
        return AsyncMock(side_effect=texts)
    idx = _counter[0] % len(_REPLIES)
    _counter[0] += 1
    return _REPLIES[idx]


def _make_pb(max_comments_per_post=3, max_comments_per_day=6,
             max_replies_per_cycle=2, agent_name="COMET-RIOBAMBA",
             get_comments_today=None, increment_comments_today=None):
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
        get_comments_today=get_comments_today or (lambda: 0),
        increment_comments_today=increment_comments_today or (lambda: 0),
    )
    pb = PhaseB(deps)
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(side_effect=lambda **kw: _incrementing_reply())
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
    orig_cs = cs.CONVERSATIONS_PATH
    orig_rep = pb._REPLIED_IDS_PATH
    orig_com = pb._COMMENTED_POSTS_PATH
    orig_dedup = ds.DedupStore._default_db_path
    orig_agenda = ra.AGENDA_PATH
    cs.CONVERSATIONS_PATH = tmp_path / "conversations.json"
    pb._REPLIED_IDS_PATH = tmp_path / "replied_comment_ids.json"
    pb._COMMENTED_POSTS_PATH = tmp_path / "commented_post_ids.json"
    ds.DedupStore._default_db_path = tmp_path / "comet_dedup.db"
    # Phase B feed replies call _add_topic_to_agenda -> load_agenda/save_agenda,
    # which use the module-level AGENDA_PATH. Redirect it so fixture posts never
    # leak into the real data/research_agenda.json.
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
    ds.DedupStore._default_db_path = orig_dedup
    ra.AGENDA_PATH = orig_agenda

    # Restore backed-up JSON files
    for _jpath, _data in _orig_json_files.items():
        Path(_jpath).write_bytes(_data)


# ── Deduplication tests ─────────────────────────────────────────

class TestDeduplication:
    @pytest.mark.asyncio
    async def test_post_own_reply_checks_replied_ids_and_skips(self, _redirect_paths):
        """_post_own_reply should check _replied_comment_ids and return None if already replied."""
        pb = _make_pb()
        pb._replied_comment_ids.add("post-1:c1")
        result = await pb._post_own_reply("post-1", "c1", "user", "Hello?")
        assert result is None, "Should skip already-replied comment"
        pb.api.create_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_post_own_reply_adds_to_replied_after_success(self, _redirect_paths):
        """After successful create_comment, _post_own_reply should add to _replied_comment_ids."""
        pb = _make_pb()
        result = await pb._post_own_reply("post-1", "c1", "user", "Hello?")
        assert result is not None
        assert "post-1:c1" in pb._replied_comment_ids

    @pytest.mark.asyncio
    async def test_post_own_reply_2xx_unverified_adds_replied_id_and_skips_outbox(self, _redirect_paths):
        """When create_comment returns HTTP 2xx but success=False (unverified),
        _post_own_reply must NOT enqueue to outbox (comment is on the server)
        and must add to _replied_comment_ids to prevent future re-reply."""
        pb = _make_pb()
        pb.api.create_comment.return_value = {
            "success": False,
            "status": 200,
            "id": "c-on-server",
            "raw": {
                "comment": {"id": "c-on-server"},
                "verification_required": True,
            },
        }
        with pytest.MonkeyPatch.context() as mp:
            outbox_calls = []
            mp.setattr("phases.phase_b.orchestrator.enqueue_outbox", lambda kind, payload: outbox_calls.append((kind, payload)))
            result = await pb._post_own_reply("post-1", "c1", "user", "Hello?")
        assert result is not None, "Should return a result even when unverified"
        assert "post-1:c1" in pb._replied_comment_ids, "Must add to dedup set to prevent re-reply"
        assert len(outbox_calls) == 0, "Must NOT enqueue to outbox — comment is already on server"

    @pytest.mark.asyncio
    async def test_post_own_reply_non_2xx_still_enqueues_outbox(self, _redirect_paths):
        """When create_comment fails with non-2xx status, _post_own_reply must still
        enqueue to outbox for retry (comment was NOT created on server)."""
        pb = _make_pb()
        pb.api.create_comment.return_value = {
            "success": False,
            "status": 500,
            "id": None,
            "raw": {},
        }
        with pytest.MonkeyPatch.context() as mp:
            outbox_calls = []
            mp.setattr("phases.phase_b.orchestrator.enqueue_outbox", lambda kind, payload: outbox_calls.append((kind, payload)))
            result = await pb._post_own_reply("post-1", "c1", "user", "Hello?")
        assert result is not None
        assert "post-1:c1" not in pb._replied_comment_ids, "Must NOT add to dedup set on non-2xx failure"
        assert len(outbox_calls) == 1, "Must enqueue to outbox for retry"

    @pytest.mark.asyncio
    async def test_process_own_post_does_not_duplicate_in_debate_continuation(self, _redirect_paths):
        """Debate continuation should respect _replied_comment_ids and not reply again."""
        pb = _make_pb(max_comments_per_post=3)
        pb.api.fetch_post_comments.return_value = [
            {
                "id": "c1",
                "author": {"name": "other_agent", "id": "99"},
                "content": "What about error handling?",
                "text": "What about error handling?",
            }
        ]
        result1 = await pb._process_own_post("post-1")
        assert len(result1) == 1
        assert pb.api.create_comment.call_count == 1

        pb.api.create_comment.reset_mock()
        result2 = await pb._process_own_post("post-1")
        assert len(result2) == 0, "Should not reply again to the same comment"
        pb.api.create_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_own_post_skips_replied_ids_from_persistence(self, _redirect_paths):
        """Comments already in _replied_comment_ids from previous runs should be skipped."""
        pb = _make_pb()
        pb._replied_comment_ids.add("post-1:c-replied-previously")
        pb.api.fetch_post_comments.return_value = [
            {
                "id": "c-replied-previously",
                "author": {"name": "other_agent", "id": "99"},
                "content": "How to handle rate limits?",
                "text": "How to handle rate limits?",
            }
        ]
        result = await pb._process_own_post("post-1")
        assert len(result) == 0
        pb.api.create_comment.assert_not_called()


# ── Limit enforcement tests ─────────────────────────────────────

class TestLimitEnforcement:
    @pytest.mark.asyncio
    async def test_process_own_post_respects_per_post_limit(self, _redirect_paths):
        """With max_comments_per_post=1, only first eligible comment gets a reply."""
        pb = _make_pb(max_comments_per_post=1)
        pb.api.fetch_post_comments.return_value = [
            {"id": "c1", "author": {"name": "a1"}, "content": "Question about X?", "text": "Question about X?"},
            {"id": "c2", "author": {"name": "a2"}, "content": "Question about Y?", "text": "Question about Y?"},
        ]
        result = await pb._process_own_post("post-1")
        assert len(result) == 1, "Only 1 reply allowed by per-post limit"
        assert pb.api.create_comment.call_count == 1

    @pytest.mark.asyncio
    async def test_process_own_post_respects_cycle_limit(self, _redirect_paths):
        """With max_replies_per_cycle=1, only first eligible comment across all posts."""
        pb = _make_pb(max_replies_per_cycle=1)
        pb.api.fetch_post_comments.return_value = [
            {"id": "c1", "author": {"name": "a1"}, "content": "Question about X?", "text": "Question about X?"},
            {"id": "c2", "author": {"name": "a2"}, "content": "Question about Y?", "text": "Question about Y?"},
        ]
        result = await pb._process_own_post("post-1")
        assert len(result) == 1, "Only 1 reply allowed by cycle limit"

    @pytest.mark.asyncio
    async def test_process_own_post_respects_daily_limit(self, _redirect_paths):
        """With daily limit reached, should return empty."""
        pb = _make_pb(get_comments_today=lambda: 100)
        pb.api.fetch_post_comments.return_value = [
            {"id": "c1", "author": {"name": "a1"}, "content": "Question?", "text": "Question?"},
        ]
        result = await pb._process_own_post("post-1")
        assert result == []


# ── Feed reply limit tests ──────────────────────────────────────

class TestFeedReplyLimits:
    @pytest.mark.asyncio
    async def test_feed_replies_respects_feed_per_day_limit(self, _redirect_paths):
        """max_feed_replies_per_day should cap feed replies independently."""
        pb = _make_pb(max_replies_per_cycle=5)
        pb.llm.generate = AsyncMock(side_effect=lambda **kw: _incrementing_reply())

        # Mock multiple feed posts
        def mock_feed(limit=20, sort="hot"):
            class MockResp:
                success = True
                data = {"posts": [
                    {"id": f"post-{i}", "title": f"Post {i} about agents",
                     "content": f"How to build agent {i} systems?",
                     "author": "other", "submolt": "agents",
                     "comments": []}
                    for i in range(10)
                ]}
            return MockResp()

        pb.api.get_feed = mock_feed
        pb.api._pick_list = lambda data, *keys: data.get("posts", [])

        # Mock create_comment to succeed
        pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}

        # Run with max_feed=3 (from _make_pb behavior_cfg)
        result = await pb._execute_feed_replies()
        assert len(result) <= 3, f"Should respect max_feed=3, got {len(result)}"

    @pytest.mark.asyncio
    async def test_feed_replies_respects_cycle_limit(self, _redirect_paths):
        """max_replies_per_cycle should cap feed replies per cycle."""
        pb = _make_pb(max_replies_per_cycle=1)

        def mock_feed(limit=20, sort="hot"):
            class MockResp:
                success = True
                data = {"posts": [
                    {"id": f"post-{i}", "title": f"Post {i}",
                     "content": f"Technical question about agent {i}?",
                     "author": "other", "submolt": "agents",
                     "comments": []}
                    for i in range(5)
                ]}
            return MockResp()

        pb.api.get_feed = mock_feed
        pb.api._pick_list = lambda data, *keys: data.get("posts", [])
        pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}

        result = await pb._execute_feed_replies()
        assert len(result) <= 1


# ── Priority: own-post before feed ──────────────────────────────

class TestPriority:
    @pytest.mark.asyncio
    async def test_own_post_replies_before_feed_in_execute(self, _redirect_paths):
        """execute() must call _execute_own_post_replies before _execute_feed_replies."""
        from unittest.mock import AsyncMock

        pb = _make_pb(max_comments_per_day=10, max_replies_per_cycle=5)
        pb.llm.generate = AsyncMock(side_effect=lambda **kw: _incrementing_reply())
        pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}

        call_order = []

        original_own = pb._execute_own_post_replies
        async def tracked_own():
            call_order.append("own")
            return await original_own()
        pb._execute_own_post_replies = tracked_own

        original_feed = pb._execute_feed_replies
        async def tracked_feed(*a, **kw):
            call_order.append("feed")
            return await original_feed(*a, **kw)
        pb._execute_feed_replies = tracked_feed

        await pb.execute()

        assert len(call_order) == 2
        assert call_order[0] == "own", f"own-post must come first, got {call_order}"
        assert call_order[1] == "feed", f"feed must come second, got {call_order}"

    @pytest.mark.asyncio
    async def test_own_post_reply_happens_before_feed_reply(self, _redirect_paths):
        """When both own-post comments and feed candidates exist, the first
        create_comment must be for the own-post reply."""
        from unittest.mock import AsyncMock

        pb = _make_pb(max_comments_per_day=10, max_replies_per_cycle=5)
        pb.llm.generate = AsyncMock(side_effect=lambda **kw: _incrementing_reply())
        pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}

        # Own post with a comment
        pb.api.fetch_my_posts = MagicMock(return_value=[
            {"id": "my-post-1", "title": "My post", "content": "Content about agents"}
        ])
        pb.api.fetch_post_comments.return_value = [
            {"id": "oc1", "author": {"name": "user1"}, "content": "Interesting question?", "text": "Interesting question?"}
        ]

        # Feed with a candidate
        def mock_feed(limit=20, sort="hot"):
            class MockResp:
                success = True
                data = {"posts": [
                    {"id": "feed-post-1", "title": "Feed post",
                     "content": "How to build agents?",
                     "author": "other", "submolt": "agents", "comments": []}
                ]}
            return MockResp()
        pb.api.get_feed = mock_feed
        pb.api._pick_list = lambda data, *keys: data.get("posts", [])

        create_call_args = []
        original_create = pb.api.create_comment
        def tracked_create(*a, **kw):
            create_call_args.append(kw.get("post_id") or a[0] if a else kw.get("post_id"))
            return original_create(*a, **kw)
        pb.api.create_comment = tracked_create

        result = await pb.execute()

        assert len(create_call_args) >= 1, "Expected at least one create_comment call"
        assert create_call_args[0] == "my-post-1", (
            f"First create_comment must be for own post, got {create_call_args[0]}"
        )
        assert result["replies_published"] >= 1


# ── Multi-comment: all relevant comments in same own post ────────

class TestMultiComment:
    @pytest.mark.asyncio
    async def test_two_distinct_comments_in_same_own_post(self, _redirect_paths):
        """With max_comments_per_post >= 2, the agent must reply to both
        distinct comments in the same own post in one pass."""
        pb = _make_pb(max_comments_per_post=6, max_replies_per_cycle=5)
        pb.api.fetch_post_comments.return_value = [
            {"id": "c1", "author": {"name": "user_a"}, "content": "How does error handling work?", "text": "How does error handling work?"},
            {"id": "c2", "author": {"name": "user_b"}, "content": "What about latency?", "text": "What about latency?"},
        ]
        result = await pb._process_own_post("post-1")
        assert len(result) == 2, f"Expected 2 replies for 2 distinct comments, got {len(result)}"
        assert pb.api.create_comment.call_count == 2
        # Each comment should be in dedup set
        assert "post-1:c1" in pb._replied_comment_ids
        assert "post-1:c2" in pb._replied_comment_ids


# ── Thread depth (multi-turn conversation) ────────────────

class TestThreadDepth:
    @pytest.mark.asyncio
    async def test_reply_to_agent_comment_depth_1_generates_reply(self, _redirect_paths):
        """A comment that directly replies to the agent (depth 1) should be answered
        and the LLM prompt must contain the thread history."""
        pb = _make_pb(max_comments_per_post=6, max_replies_per_cycle=5)
        pb._agent_comment_ids["post-1"] = ["agent-c1"]
        pb.api.fetch_post_comments.return_value = [
            {"id": "agent-c1", "author": {"name": "comet_riobamba"}, "content": "Great question!", "text": "Great question!", "parent_id": None},
            {"id": "other-c1", "author": {"name": "user_a"}, "content": "Can you elaborate?", "text": "Can you elaborate?", "parent_id": "agent-c1"},
        ]
        pb.llm.generate = AsyncMock(return_value="We measured in production that elaboration on important topics reveals that 30% of latency comes from thread pool exhaustion under load.")
        result = await pb._process_own_post("post-1")
        assert len(result) == 1, f"Expected 1 reply for depth-1 reply to agent, got {len(result)}"

        # Verify thread history was injected into the first LLM call (reply generation)
        first_kwargs = pb.llm.generate.call_args_list[0][1]
        prompt = first_kwargs.get("prompt", "")
        assert "--- HISTORIAL DEL HILO ---" in prompt, f"Thread history block missing from prompt: {prompt[:200]}"
        assert "[Agente]: Great question!" in prompt, "Agent's previous comment missing from thread history"
        assert "TASK: You are continuing a technical debate" in prompt, "Debate continuation template missing"

    @pytest.mark.asyncio
    async def test_reply_to_agent_comment_depth_3_skipped(self, _redirect_paths):
        """A comment at depth 3 (exceeding MAX_CONVERSATION_DEPTH) should be skipped."""
        pb = _make_pb(max_comments_per_post=6, max_replies_per_cycle=5)
        pb._agent_comment_ids["post-1"] = ["agent-c1", "agent-c2"]
        pb.api.fetch_post_comments.return_value = [
            {"id": "agent-c1", "author": {"name": "comet_riobamba"}, "content": "Great question!", "text": "Great question!", "parent_id": None},
            {"id": "other-c1", "author": {"name": "user_a"}, "content": "Can you elaborate?", "text": "Can you elaborate?", "parent_id": "agent-c1"},
            {"id": "agent-c2", "author": {"name": "comet_riobamba"}, "content": "Sure!", "text": "Sure!", "parent_id": "other-c1"},
            {"id": "other-c2", "author": {"name": "user_b"}, "content": "But what about production?", "text": "But what about production?", "parent_id": "agent-c2"},
        ]
        pb.llm.generate = AsyncMock(return_value="Your request to elaborate reveals an important design principle we observed in production where the measured framework prevents cascading failure modes effectively.")
        result = await pb._process_own_post("post-1")
        assert len(result) == 1, f"Expected only depth-1 comment to be answered, got {len(result)}"

        # Verify the depth-3 comment was skipped entirely (no generate call for it)
        # The generate calls are: reply generation for other-c1 + value classifier
        assert pb.llm.generate.call_count >= 1


class TestMemoryIntegration:
    @pytest.mark.asyncio
    async def test_memory_injected_into_prompt_when_user_known(self, _redirect_paths):
        """When get_memory returns a record, the LLM prompt must include NOTA DE MEMORIA."""
        pb = _make_pb(max_comments_per_post=6, max_replies_per_cycle=5)
        pb._memory.get_memory.return_value = {
            "username": "Juan",
            "summary": "Hablamos de Python",
            "last_interaction": "2026-06-18T12:00:00+00:00",
        }
        pb._agent_comment_ids["post-1"] = ["agent-c1"]
        pb.api.fetch_post_comments.return_value = [
            {"id": "agent-c1", "author": {"name": "comet_riobamba"}, "content": "Great question!", "text": "Great question!", "parent_id": None},
            {"id": "other-c1", "author": {"name": "user_a"}, "content": "Can you elaborate?", "text": "Can you elaborate?", "parent_id": "agent-c1"},
        ]
        pb.llm.generate = AsyncMock(return_value="We measured in production that elaboration on important topics reveals that 30% of latency comes from thread pool exhaustion under load.")
        result = await pb._process_own_post("post-1")
        assert len(result) >= 1

        first_kwargs = pb.llm.generate.call_args_list[0][1]
        prompt = first_kwargs.get("prompt", "")
        assert "COGNITIVE CONTEXT" in prompt, f"Memory note missing from prompt: {prompt[:200]}"
        assert "Hablamos de Python" in prompt, "Memory summary missing from prompt"
        assert "@Juan" in prompt, "Username missing from memory note"

    @pytest.mark.asyncio
    async def test_update_memory_called_after_successful_reply(self, _redirect_paths):
        """After posting a reply successfully, update_memory should be called."""
        pb = _make_pb(max_comments_per_post=6, max_replies_per_cycle=5)
        pb._agent_comment_ids["post-1"] = ["agent-c1"]
        pb.api.fetch_post_comments.return_value = [
            {"id": "agent-c1", "author": {"name": "comet_riobamba"}, "content": "Great question!", "text": "Great question!", "parent_id": None},
            {"id": "other-c1", "author": {"name": "user_a"}, "content": "Can you elaborate?", "text": "Can you elaborate?", "parent_id": "agent-c1"},
        ]
        pb.llm.generate = AsyncMock(return_value="We observed that the detailed explanation reveals a framework where 45% of failures are preventable with proper circuit breaker patterns and fallback strategies.")
        result = await pb._process_own_post("post-1")
        assert len(result) >= 1

        # Check update_memory was called with user_a and part of reply text
        assert pb._memory.update_memory.called
        call_args = pb._memory.update_memory.call_args
        assert call_args[0][0] == "user_a", f"Expected user_a, got {call_args[0][0]}"
        summary = call_args[0][2]
        assert "We observed that the detailed explanation" in summary, \
            f"Reply text missing from summary: {summary}"
