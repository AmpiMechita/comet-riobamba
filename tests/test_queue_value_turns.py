# -*- coding: utf-8 -*-
"""Tests del umbral de valor en la cola (el presupuesto es techo, no cuota)
y del limite de turnos dinamico en conversaciones enhebradas."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest_plugins = ("pytest_asyncio",)

from phases.phase_b import PhaseB
from phases.deps import PhaseBDeps


_REPLY_TEXT = (
    "The fix is a canonical key contract: the consumer reads the same field the "
    "client normalizes, and a contract test asserts the pair stays aligned."
)


def _make_pb(max_comments_per_post=10, max_comments_per_day=15,
             max_replies_per_cycle=5, behavior_extra=None):
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
        agent_name="COMET-RIOBAMBA",
        get_comments_today=lambda: 0,
        increment_comments_today=lambda: 0,
    )
    pb = PhaseB(deps)
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(return_value=_REPLY_TEXT)
    pb.api = MagicMock()
    pb.api.create_comment.return_value = {"success": True, "id": "new-comment-id", "status": 201}
    pb._memory = MagicMock()
    pb._memory.get_memory.return_value = None
    return pb


@pytest.fixture
def _redirect_paths(tmp_path):
    """Redirect file paths a tmp (mismo patron que test_phase_b_own_post_engagement)."""
    import services.conversation_state as cs
    import services.dedup_store as ds
    import services.research_agenda as ra
    import phases.phase_b as pb_mod
    import services.reply_cap as rcap_mod
    import services.interlocutors as il

    orig_cs = cs.CONVERSATIONS_PATH
    orig_rep = pb_mod._REPLIED_IDS_PATH
    orig_com = pb_mod._COMMENTED_POSTS_PATH
    orig_agc = pb_mod._AGENT_COMMENT_IDS_PATH
    orig_upv = pb_mod._UPVOTED_POST_IDS_PATH
    orig_fol = pb_mod._FOLLOWED_AGENTS_PATH
    orig_rpp = rcap_mod._REPLIES_PER_POST_PATH
    orig_dedup = ds.DedupStore._default_db_path
    orig_agenda = ra.AGENDA_PATH
    orig_il = il._INTERLOCUTORS_PATH
    cs.CONVERSATIONS_PATH = tmp_path / "conversations.json"
    pb_mod._REPLIED_IDS_PATH = tmp_path / "replied_comment_ids.json"
    pb_mod._COMMENTED_POSTS_PATH = tmp_path / "commented_post_ids.json"
    pb_mod._AGENT_COMMENT_IDS_PATH = tmp_path / "agent_comment_ids.json"
    pb_mod._UPVOTED_POST_IDS_PATH = tmp_path / "upvoted_post_ids.json"
    pb_mod._FOLLOWED_AGENTS_PATH = tmp_path / "followed_agents.json"
    rcap_mod._REPLIES_PER_POST_PATH = tmp_path / "replies_per_post.json"
    ds.DedupStore._default_db_path = tmp_path / "comet_dedup.db"
    ra.AGENDA_PATH = tmp_path / "research_agenda.json"
    il._INTERLOCUTORS_PATH = tmp_path / "interlocutors.json"

    _orig_json_files = {}
    for _ns, _jpath, _fmt in ds._JSON_NAMESPACES:
        _p = Path(_jpath)
        if _p.exists():
            _orig_json_files[_jpath] = _p.read_bytes()
            _p.unlink()

    yield

    cs.CONVERSATIONS_PATH = orig_cs
    pb_mod._REPLIED_IDS_PATH = orig_rep
    pb_mod._COMMENTED_POSTS_PATH = orig_com
    pb_mod._AGENT_COMMENT_IDS_PATH = orig_agc
    pb_mod._UPVOTED_POST_IDS_PATH = orig_upv
    pb_mod._FOLLOWED_AGENTS_PATH = orig_fol
    rcap_mod._REPLIES_PER_POST_PATH = orig_rpp
    ds.DedupStore._default_db_path = orig_dedup
    ra.AGENDA_PATH = orig_agenda
    il._INTERLOCUTORS_PATH = orig_il

    for _jpath, _data in _orig_json_files.items():
        Path(_jpath).write_bytes(_data)


# ── Umbral de valor en la cola (presupuesto = techo, no cuota) ──

class TestQueueValueThreshold:
    @pytest.mark.asyncio
    async def test_low_value_comment_skipped_even_with_free_slots(self, _redirect_paths, monkeypatch):
        """Con AGENT_MIN_REPLY_VALUE_SCORE alto y slots libres, un comentario de
        bajo valor NO entra a la cola: se responde 0, no 1."""
        monkeypatch.setenv("AGENT_MIN_REPLY_VALUE_SCORE", "0.4")
        pb = _make_pb(max_comments_per_day=50, max_replies_per_cycle=5)
        post = {"id": "top-12345678-aaaa-bbbb-cccc-ddddeeeeffff", "comment_count": 10}
        pb.api._request = MagicMock(return_value={"status": 200, "data": {"posts": [post]}})
        pb.api.fetch_my_posts = MagicMock(return_value=[])
        pb.api.fetch_post_comments.return_value = [
            {"id": "c1", "author": {"name": "user1"},
             "content": "ok thanks", "text": "ok thanks"},
        ]
        pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}
        pb._classify_and_log_value = AsyncMock()

        await pb._execute_own_post_replies()

        pb.api.create_comment.assert_not_called()
        assert pb._stats.get("queue_prefiltered", 0) >= 1, "el filtrado por valor se cuenta"

    @pytest.mark.asyncio
    async def test_watchlist_uses_lower_floor(self, _redirect_paths, monkeypatch):
        """El autor watchlist entra con el piso rebajado (0.4 -> 0.2) aunque su
        comentario corto valga 0.3: prioridad de relacion, no ruido."""
        monkeypatch.setenv("AGENT_MIN_REPLY_VALUE_SCORE", "0.4")
        wl = "wl_author"
        pb = _make_pb(max_comments_per_day=50, max_replies_per_cycle=5)
        pb._watchlist_authors = {wl}
        post = {"id": "top-12345678-aaaa-bbbb-cccc-ddddeeeeffff", "comment_count": 10}
        pb.api._request = MagicMock(return_value={"status": 200, "data": {"posts": [post]}})
        pb.api.fetch_my_posts = MagicMock(return_value=[])
        pb.api.fetch_post_comments.return_value = [
            {"id": "c1", "author": {"name": wl},
             "content": "What about error handling in the retry loop?", "text": "What about error handling in the retry loop?"},
        ]
        pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}
        pb._classify_and_log_value = AsyncMock()

        await pb._execute_own_post_replies()

        pb.api.create_comment.assert_called_once()

    @pytest.mark.asyncio
    async def test_score_distribution_logged_each_cycle(self, _redirect_paths, caplog):
        """Con el umbral en 0 (default), la distribucion de scores se loguea
        para calibrar AGENT_MIN_REPLY_VALUE_SCORE con datos."""
        import logging
        pb = _make_pb(max_comments_per_day=50, max_replies_per_cycle=5)
        post = {"id": "top-12345678-aaaa-bbbb-cccc-ddddeeeeffff", "comment_count": 10}
        pb.api._request = MagicMock(return_value={"status": 200, "data": {"posts": [post]}})
        pb.api.fetch_my_posts = MagicMock(return_value=[])
        pb.api.fetch_post_comments.return_value = [
            {"id": "c1", "author": {"name": "user1"},
             "content": "ok thanks", "text": "ok thanks"},
            {"id": "c2", "author": {"name": "user2"},
             "content": "What about error handling in the retry loop?", "text": "What about error handling in the retry loop?"},
        ]
        pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}
        pb._classify_and_log_value = AsyncMock()

        with caplog.at_level(logging.INFO, logger="phases.phase_b"):
            await pb._execute_own_post_replies()

        dist_lines = [r.getMessage() for r in caplog.records if "own-post queue scores" in r.getMessage()]
        assert dist_lines, "la distribucion de scores debe loguearse"
        assert "(n=2)" in dist_lines[0]
        assert "min=" in dist_lines[0] and "mediana=" in dist_lines[0] and "max=" in dist_lines[0]


    @pytest.mark.asyncio
    async def test_first_interaction_gets_lowered_floor(self, _redirect_paths, monkeypatch):
        """Enganche temprano: autor SIN historial con comentario de 0.3 entra
        (piso rebajado 0.4->0.2) aunque no supere el umbral normal."""
        monkeypatch.setenv("AGENT_MIN_REPLY_VALUE_SCORE", "0.4")
        pb = _make_pb(max_comments_per_day=50, max_replies_per_cycle=5)
        pb._get_own_post_ids = lambda: {"top-12345678-aaaa-bbbb-cccc-ddddeeeeffff"}
        post = {"id": "top-12345678-aaaa-bbbb-cccc-ddddeeeeffff", "comment_count": 10}
        pb.api._request = MagicMock(return_value={"status": 200, "data": {"posts": [post]}})
        pb.api.fetch_my_posts = MagicMock(return_value=[])
        pb.api.fetch_post_comments.return_value = [
            {"id": "c1", "author": {"name": "newcomer"},
             "content": "What about error handling in the retry loop?", "text": "What about error handling in the retry loop?"},
        ]
        pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}
        pb._classify_and_log_value = AsyncMock()

        await pb._execute_own_post_replies()

        pb.api.create_comment.assert_called_once(), "la primera interaccion no muere en el umbral"

    @pytest.mark.asyncio
    async def test_returning_author_below_floor_still_filtered(self, _redirect_paths, monkeypatch):
        """Autor con 1-2 interacciones previas (no historial 3+) y score 0.3:
        piso normal 0.4 -> no entra."""
        from services.interlocutors import record_interaction
        record_interaction({"name": "returning"}, on_our_post=True)
        monkeypatch.setenv("AGENT_MIN_REPLY_VALUE_SCORE", "0.4")
        pb = _make_pb(max_comments_per_day=50, max_replies_per_cycle=5)
        pb._get_own_post_ids = lambda: {"top-12345678-aaaa-bbbb-cccc-ddddeeeeffff"}
        post = {"id": "top-12345678-aaaa-bbbb-cccc-ddddeeeeffff", "comment_count": 10}
        pb.api._request = MagicMock(return_value={"status": 200, "data": {"posts": [post]}})
        pb.api.fetch_my_posts = MagicMock(return_value=[])
        pb.api.fetch_post_comments.return_value = [
            {"id": "c1", "author": {"name": "returning"},
             "content": "What about error handling in the retry loop?", "text": "What about error handling in the retry loop?"},
        ]
        pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}
        pb._classify_and_log_value = AsyncMock()

        await pb._execute_own_post_replies()

        pb.api.create_comment.assert_not_called()
        assert pb._stats.get("queue_prefiltered", 0) >= 1

    @pytest.mark.asyncio
    async def test_first_interaction_bot_like_still_filtered(self, _redirect_paths, monkeypatch):
        """Primera interaccion con texto clasificable como basura: el piso
        rebajado no aplica (no abrir la puerta a bots)."""
        monkeypatch.setenv("AGENT_MIN_REPLY_VALUE_SCORE", "0.4")
        pb = _make_pb(max_comments_per_day=50, max_replies_per_cycle=5)
        pb._get_own_post_ids = lambda: {"top-12345678-aaaa-bbbb-cccc-ddddeeeeffff"}
        post = {"id": "top-12345678-aaaa-bbbb-cccc-ddddeeeeffff", "comment_count": 10}
        pb.api._request = MagicMock(return_value={"status": 200, "data": {"posts": [post]}})
        pb.api.fetch_my_posts = MagicMock(return_value=[])
        pb.api.fetch_post_comments.return_value = [
            {"id": "c1", "author": {"name": "spammy_newcomer"},
             "content": "ok thanks", "text": "ok thanks"},
        ]
        pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}
        pb._classify_and_log_value = AsyncMock()

        await pb._execute_own_post_replies()

        pb.api.create_comment.assert_not_called()

    def test_watchlist_cap_default_is_three(self):
        """El freno anti-reply-guy vuelve a 3 al dia (configurable por env)."""
        import os
        os.environ.pop("AGENT_MAX_PER_WATCHLIST_AUTHOR_DAY", None)
        pb = _make_pb()
        assert pb._watchlist_max_per_author_day == 3, "default 3"
        os.environ["AGENT_MAX_PER_WATCHLIST_AUTHOR_DAY"] = "8"
        pb2 = _make_pb()
        assert pb2._watchlist_max_per_author_day == 8
        os.environ.pop("AGENT_MAX_PER_WATCHLIST_AUTHOR_DAY", None)


# ── Cap por post chequeado ANTES de generar ──────────────────────

class TestPostCapPrefilter:
    def test_queuable_rejects_post_at_cap(self):
        queuable, reason = PhaseB._comment_queuable(
            {"id": "c1", "content": "text"}, "post-1",
            post_cap=1, post_count=1,
        )
        assert (queuable, reason) == (False, "post_cap_reached")

    def test_queuable_accepts_post_below_cap(self):
        queuable, reason = PhaseB._comment_queuable(
            {"id": "c1", "content": "text"}, "post-1",
            post_cap=30, post_count=29,
        )
        assert queuable is True
        assert reason == ""

    def test_queuable_without_cap_keeps_old_behavior(self):
        queuable, reason = PhaseB._comment_queuable({"id": "c1", "content": "text"}, "post-1")
        assert queuable is True

    @pytest.mark.asyncio
    async def test_comment_in_post_with_exhausted_cap_not_queued(self, _redirect_paths):
        """Post con max_comments_per_post agotado: el comentario no entra a la
        cola y NO se genera ninguna reply (el LLM no se llama)."""
        pb = _make_pb(max_comments_per_post=1, max_comments_per_day=50, max_replies_per_cycle=5)
        post = {"id": "top-12345678-aaaa-bbbb-cccc-ddddeeeeffff", "comment_count": 10}
        pb._dedup.add_agent_comment(post["id"], "already-answered")
        pb.api._request = MagicMock(return_value={"status": 200, "data": {"posts": [post]}})
        pb.api.fetch_my_posts = MagicMock(return_value=[])
        pb.api.fetch_post_comments.return_value = [
            {"id": "c1", "author": {"name": "user1"},
             "content": "What about error handling in the retry loop?", "text": "What about error handling in the retry loop?"},
        ]
        pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}
        pb._classify_and_log_value = AsyncMock()

        await pb._execute_own_post_replies()

        pb.api.create_comment.assert_not_called()
        pb.llm.generate.assert_not_awaited()  # sin generar respuestas que moriran
        assert pb._stats.get("queue_prefiltered", 0) >= 1


# ── Fragmentos de busqueda semantica: rehidratar, no responder ──

class TestSemanticSnippetRehydration:
    def _pb(self):
        pb = _make_pb()
        pb._semantic_search_enabled = True
        pb._derive_search_queries = lambda: ["q1"]
        return pb

    @pytest.mark.asyncio
    async def test_hl_snippet_rehydrated_to_full_post(self):
        """Snippet con ⟦HL⟧ se rehidrata con el post COMPLETO por id."""
        pb = self._pb()
        pb.api.semantic_search.return_value = [
            {"id": "p1", "content": "⟦HL⟧reward⟦/HL⟧ ⟦HL⟧function⟦/HL⟧ defines the ⟦HL⟧social⟦/HL⟧ contract..."},
        ]
        pb.api.get_post.return_value = {
            "id": "p1", "title": "My reward function is not a social contract",
            "content": "The full real post body with plenty of technical depth for scoring.",
        }

        results = await pb._fetch_semantic_search_posts()

        assert len(results) == 1
        post = results[0]
        assert post.get("_rehydrated") is True
        assert "⟦HL⟧" not in str(post.get("content") or ""), "el post rehidratado no lleva marcadores"
        pb.api.get_post.assert_called_once_with("p1")

    @pytest.mark.asyncio
    async def test_hl_snippet_discarded_when_rehydration_fails(self, caplog):
        """Si no se puede rehidratar, el fragmento se descarta (responder a un
        snippet seria incoherente)."""
        import logging
        pb = self._pb()
        pb.api.semantic_search.return_value = [
            {"id": "p2", "content": "⟦HL⟧short snippet⟦/HL⟧ only 129 chars"},
        ]
        pb.api.get_post.return_value = None

        with caplog.at_level(logging.INFO, logger="phases.phase_b"):
            results = await pb._fetch_semantic_search_posts()

        assert results == []
        assert any("rehidratar" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_normal_post_without_marker_passes_through(self):
        """Un post real sin marcadores entra directo (sin rehidratacion)."""
        pb = self._pb()
        pb.api.semantic_search.return_value = [
            {"id": "p3", "content": "A normal post body without highlight markers."},
        ]

        results = await pb._fetch_semantic_search_posts()

        assert len(results) == 1
        assert results[0].get("_rehydrated") is None
        pb.api.get_post.assert_not_called()


def tmp_watchlist():
    """Autor watchlist temporal (config/phase_b_strategy.yaml de prueba)."""
    import yaml
    from config import BASE_DIR
    path = BASE_DIR / "config/phase_b_strategy.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    authors = [str(a).strip().lower() for a in (data.get("watchlist_authors") or [])]
    return authors[0] if authors else "nonexistent_watchlist_author"


# ── Limite de turnos dinamico ────────────────────────────────────

class TestThreadDepthLimit:
    def _comments(self, chain):
        """Construye all_comments a partir de una cadena (parent, texto)."""
        return [{"id": cid, "parent_id": pid, "content": text}
                for cid, pid, text in chain]

    def test_repetitive_thread_closes_before_base(self):
        pb = PhaseB(MagicMock())
        comments = self._comments([
            ("c1", None, "I keep saying the same thing about retries"),
            ("c2", "c1", "I keep saying the same thing about retries"),
        ])
        limit, reason = pb._thread_depth_limit(comments[1], comments, "user1", False)
        assert reason == "repetición"
        assert limit == 1, "se corta antes del piso"

    def test_watchlist_with_question_and_new_contribution_reaches_8(self):
        pb = PhaseB(MagicMock())
        comments = self._comments([
            ("c1", None, "A first message about retry backoff"),
            ("c2", "c1", "But does that actually scale to ten thousand agents?"),
            ("c3", "c2", "Yes, if you gate on the drift metric it does."),
        ])
        limit, reason = pb._thread_depth_limit(comments[2], comments, "watchlist_author", True)
        assert limit == 8
        assert reason is None

    def test_watchlist_without_open_question_stays_at_base(self):
        pb = PhaseB(MagicMock())
        comments = self._comments([
            ("c1", None, "A first message"),
            ("c2", "c1", "ok sounds fine"),
            ("c3", "c2", "More text that does not ask anything"),
        ])
        limit, reason = pb._thread_depth_limit(comments[2], comments, "watchlist_author", True)
        assert limit == 4
        assert reason == "sin pregunta"

    def test_plain_author_keeps_base(self):
        pb = PhaseB(MagicMock())
        comments = self._comments([
            ("c1", None, "A first message with an open question?"),
            ("c2", "c1", "An answer with a brand new claim"),
        ])
        limit, reason = pb._thread_depth_limit(comments[1], comments, "user1", False)
        assert limit == 4
        assert reason is None
