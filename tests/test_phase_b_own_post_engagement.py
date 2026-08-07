"""Tests for own-post reply fixes:
- high-engagement older posts enter the candidate pool (engagement ranking)
- deleted agent comments are reconciled so they don't block the per-post cap
- per-post cap comes from config and no longer permanently closes the thread
- full own-post registry is used for the own-post-reply relevance bypass
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from phases.phase_b import PhaseB
from phases.deps import PhaseBDeps


_REPLIES = [
    "In production we observed that the architecture pattern observed in this design effectively prevents cascading failures.",
    "We measured that careful caching with proper framework design improves overall throughput under peak load conditions.",
    "The design strategy for routing and scaling we observed uses a measured approach with proper failover architecture.",
]
_counter = [0]


def _incrementing_reply(*args, **kwargs):
    idx = _counter[0] % len(_REPLIES)
    _counter[0] += 1
    return _REPLIES[idx]


def _make_pb(max_comments_per_post=10, max_comments_per_day=15,
             max_replies_per_cycle=5, agent_name="COMET-RIOBAMBA",
             get_comments_today=None, increment_comments_today=None,
             behavior_extra=None):
    behavior = {
        "max_comments_per_post": max_comments_per_post,
        "max_comments_per_day": max_comments_per_day,
        "max_comment_replies_per_cycle": max_replies_per_cycle,
        "max_feed_replies_per_day": 3,
        "delay_between_comments": 0,
    }
    if behavior_extra:
        behavior.update(behavior_extra)
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg=behavior,
        agent_name=agent_name,
        get_comments_today=get_comments_today or (lambda: 0),
        increment_comments_today=increment_comments_today or (lambda: 0),
    )
    pb = PhaseB(deps)
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(side_effect=_incrementing_reply)
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

    for _jpath, _data in _orig_json_files.items():
        Path(_jpath).write_bytes(_data)


class TestEngagementRanking:
    @pytest.mark.asyncio
    async def test_fetch_own_posts_merges_engagement_and_fresh(self, _redirect_paths):
        """Candidate pool must include high-engagement older posts (API sort=top)
        merged with the newest posts, so old threads stay on the radar."""
        pb = _make_pb()
        pb.api._request = MagicMock(return_value={
            "status": 200,
            "data": {"posts": [
                {"id": "old-top", "comment_count": 807, "title": "Context exhaustion"},
                {"id": "mid", "comment_count": 61, "title": "Agent loops"},
            ]},
        })
        pb.api.fetch_my_posts = MagicMock(return_value=[{"id": "brand-new"}])

        posts = pb._fetch_own_posts_for_replies()
        ids = {p["id"] for p in posts}
        assert "old-top" in ids, "High-engagement old post missing from candidates"
        assert "mid" in ids
        assert "brand-new" in ids

    @pytest.mark.asyncio
    async def test_execute_own_replies_includes_high_engagement_old_post(self, _redirect_paths):
        """A high-comment post that is NOT among the most recent must still be
        processed (it was never a candidate before)."""
        pb = _make_pb(max_comments_per_day=10, max_replies_per_cycle=5)
        top_post = {"id": "top-12345678-aaaa-bbbb-cccc-ddddeeeeffff", "comment_count": 807}
        pb.api._request = MagicMock(return_value={"status": 200, "data": {"posts": [top_post]}})
        pb.api.fetch_my_posts = MagicMock(return_value=[{"id": "fresh-1"}])
        pb.api.fetch_post_comments.return_value = [
            {"id": "c1", "author": {"name": "user1"},
             "content": "What about error handling?", "text": "What about error handling?"},
        ]
        pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}

        await pb._execute_own_post_replies()

        called_posts = [c.kwargs.get("post_id") or c.args[0]
                        for c in pb.api.create_comment.call_args_list if c.kwargs or c.args]
        assert called_posts, "No reply posted at all"
        assert called_posts[0] == top_post["id"], f"High-engagement post should be first, got {called_posts}"

    @pytest.mark.asyncio
    async def test_own_posts_per_cycle_uses_configurable_limit(self, _redirect_paths):
        """El límite de posts propios por ciclo debe ser configurable
        (phase_b_max_own_posts_per_cycle), no 3 fijo: los posts fuera del top-3
        quedaban desatendidos indefinidamente."""
        pb = _make_pb(max_comments_per_day=50, max_replies_per_cycle=5)
        posts = [
            {"id": f"top-{i}000000-aaaa-bbbb-cccc-ddddeeeeffff", "comment_count": 100 - i}
            for i in range(4)
        ]
        pb.api._request = MagicMock(return_value={"status": 200, "data": {"posts": posts}})
        pb.api.fetch_my_posts = MagicMock(return_value=[])
        pb.api.fetch_post_comments.return_value = [
            {"id": "c1", "author": {"name": "user1"},
             "content": "What about error handling?", "text": "What about error handling?"},
        ]
        pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}

        # default 6: los 4 posts entran al ciclo
        await pb._execute_own_post_replies()
        called = set()
        for c in pb.api.create_comment.call_args_list:
            if c.kwargs:
                called.add(c.kwargs.get("post_id"))
            elif c.args:
                called.add(c.args[0])
        assert called == {p["id"] for p in posts}, f"Los 4 posts deberian entrar, got {len(called)}"

        # con limit 1: solo el primero entra (posts distintos para evitar el
        # dedup compartido con el caso anterior)
        pb2 = _make_pb(max_comments_per_day=50, max_replies_per_cycle=5,
                       behavior_extra={"phase_b_max_own_posts_per_cycle": 1})
        posts2 = [
            {"id": f"top2-{i}000000-aaaa-bbbb-cccc-ddddeeeeffff", "comment_count": 100 - i}
            for i in range(4)
        ]
        pb2.api._request = MagicMock(return_value={"status": 200, "data": {"posts": posts2}})
        pb2.api.fetch_my_posts = MagicMock(return_value=[])
        pb2.api.fetch_post_comments.return_value = [
            {"id": "c1", "author": {"name": "user1"},
             "content": "What about error handling?", "text": "What about error handling?"},
        ]
        pb2.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}
        await pb2._execute_own_post_replies()
        called2 = {c.kwargs.get("post_id") or c.args[0]
                   for c in pb2.api.create_comment.call_args_list if c.kwargs or c.args}
        assert called2 == {posts2[0]["id"]}, f"Solo el top-1 deberia entrar, got {called2}"


class TestReconcileDeletedComments:
    @pytest.mark.asyncio
    async def test_reconcile_unblocks_per_post_cap(self, _redirect_paths):
        """Agent comment IDs that 404 on the platform must be pruned so the
        per-post cap is not permanently consumed by deleted comments."""
        pb = _make_pb(max_comments_per_post=2, max_replies_per_cycle=2)
        post_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        pb._dedup.add_agent_comment(post_id, "deleted-c1")
        pb._dedup.add_agent_comment(post_id, "deleted-c2")
        pb.api._request = MagicMock(return_value={"status": 404})
        pb.api.fetch_post_comments.return_value = [
            {"id": "live-c1", "author": {"name": "a1"},
             "content": "What about latency?", "text": "What about latency?"},
        ]
        pb.api.create_comment.return_value = {"success": True, "id": "new-reply", "status": 201}

        result = await pb._process_own_post(post_id)

        assert len(result) == 1, f"Deleted comments should not block replies, got {result}"
        stored = pb._dedup.get_agent_comment_ids().get(post_id, [])
        assert "deleted-c1" not in stored, "Deleted comment id still counted"
        assert "deleted-c2" not in stored, "Deleted comment id still counted"

    @pytest.mark.asyncio
    async def test_reconcile_keeps_live_comments(self, _redirect_paths):
        """Visible agent comments must NOT be pruned."""
        pb = _make_pb()
        post_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        pb._dedup.add_agent_comment(post_id, "live-c1")
        pb._dedup.add_agent_comment(post_id, "gone-c2")
        # live returns 200, gone returns 404
        def fake_request(method, path, **kw):
            cid = path.rsplit("/", 1)[-1]
            return {"status": 200 if cid == "live-c1" else 404}
        pb.api._request = MagicMock(side_effect=fake_request)
        pb.api.fetch_post_comments.return_value = []

        await pb._process_own_post(post_id)

        stored = pb._dedup.get_agent_comment_ids().get(post_id, [])
        assert "live-c1" in stored, "Live comment must be preserved"
        assert "gone-c2" not in stored, "Deleted comment must be pruned"


class TestCapBehavior:
    @pytest.mark.asyncio
    async def test_cap_reached_does_not_close_thread(self, _redirect_paths):
        """Reaching the per-post cap must NOT permanently close the thread."""
        import services.conversation_state as cs
        pb = _make_pb(max_comments_per_post=2)
        post_id = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"
        with patch.object(pb, "_get_agent_reply_count_in_post", return_value=2):
            pb.api.fetch_post_comments.return_value = [
                {"id": "c1", "author": {"name": "a1"}, "content": "Q?", "text": "Q?"},
            ]
            result = await pb._process_own_post(post_id)
        assert result == [], "Post at cap must yield no replies"
        assert cs.is_thread_closed(post_id) is False, "Thread must stay open for future comments"

    @pytest.mark.asyncio
    async def test_cap_uses_config_value(self, _redirect_paths):
        """The early-exit cap must come from config, not a hardcoded 2."""
        pb = _make_pb(max_comments_per_post=10)
        post_id = "cccccccc-dddd-4eee-8fff-aaaaaaaaaaaa"
        with patch.object(pb, "_get_agent_reply_count_in_post", return_value=3):
            pb.api.fetch_post_comments.return_value = [
                {"id": "c1", "author": {"name": "a1"}, "content": "Q?", "text": "Q?"},
            ]
            pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}
            result = await pb._process_own_post(post_id)
        assert len(result) == 1, f"Cap=10 with 3 prior replies should still allow replies, got {result}"


class TestOwnPostRegistry:
    def test_get_own_post_ids_loads_full_registry(self, _redirect_paths, monkeypatch, tmp_path):
        """The own-post relevance bypass must use the full registry, not just
        the most recent posts, so old high-engagement posts get the bypass."""
        import services.own_post_store as ops
        f = tmp_path / "own_post_ids.json"
        f.write_text(json.dumps({"post_ids": [
            "aaaaaaaa-1111-2222-3333-444444444444",
            "bbbbbbbb-1111-2222-3333-444444444444",
        ]}), encoding="utf-8")
        monkeypatch.setattr(ops, "OWN_POST_IDS_PATH", f)
        pb = _make_pb()
        ids = pb._get_own_post_ids()
        assert "aaaaaaaa-1111-2222-3333-444444444444" in ids, "Old post must be in own-post set for bypass"
        assert "bbbbbbbb-1111-2222-3333-444444444444" in ids
