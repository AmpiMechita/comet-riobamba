# -*- coding: utf-8 -*-
"""Tests del cierre de hilo (sintesis / let_stand / pregunta directa) y del
borrador + revision solo para replies de alta exposicion (tier_quality)."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest_plugins = ("pytest_asyncio",)

from phases.phase_b import PhaseB


def _make_pb():
    from tests.test_queue_value_turns import _make_pb as _base
    return _base()


@pytest.fixture
def _redirect_paths(tmp_path):
    """Redirect file paths a tmp (mismo patron que test_phase_b_own_post_engagement)."""
    import services.conversation_state as cs
    import services.dedup_store as ds
    import services.research_agenda as ra
    import phases.phase_b as pb_mod
    import services.reply_cap as rcap_mod

    orig_cs = cs.CONVERSATIONS_PATH
    orig_rep = pb_mod._REPLIED_IDS_PATH
    orig_com = pb_mod._COMMENTED_POSTS_PATH
    orig_agc = pb_mod._AGENT_COMMENT_IDS_PATH
    orig_upv = pb_mod._UPVOTED_POST_IDS_PATH
    orig_fol = pb_mod._FOLLOWED_AGENTS_PATH
    orig_rpp = rcap_mod._REPLIES_PER_POST_PATH
    orig_dedup = ds.DedupStore._default_db_path
    orig_agenda = ra.AGENDA_PATH
    cs.CONVERSATIONS_PATH = tmp_path / "conversations.json"
    pb_mod._REPLIED_IDS_PATH = tmp_path / "replied_comment_ids.json"
    pb_mod._COMMENTED_POSTS_PATH = tmp_path / "commented_post_ids.json"
    pb_mod._AGENT_COMMENT_IDS_PATH = tmp_path / "agent_comment_ids.json"
    pb_mod._UPVOTED_POST_IDS_PATH = tmp_path / "upvoted_post_ids.json"
    pb_mod._FOLLOWED_AGENTS_PATH = tmp_path / "followed_agents.json"
    rcap_mod._REPLIES_PER_POST_PATH = tmp_path / "replies_per_post.json"
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
    pb_mod._REPLIED_IDS_PATH = orig_rep
    pb_mod._COMMENTED_POSTS_PATH = orig_com
    pb_mod._AGENT_COMMENT_IDS_PATH = orig_agc
    pb_mod._UPVOTED_POST_IDS_PATH = orig_upv
    pb_mod._FOLLOWED_AGENTS_PATH = orig_fol
    rcap_mod._REPLIES_PER_POST_PATH = orig_rpp
    ds.DedupStore._default_db_path = orig_dedup
    ra.AGENDA_PATH = orig_agenda

    for _jpath, _data in _orig_json_files.items():
        Path(_jpath).write_bytes(_data)


# ── Cierre de hilo: sintesis o let_stand ─────────────────────────

class TestCloseThreadDecision:
    @pytest.mark.asyncio
    async def test_close_output_means_let_stand(self, _redirect_paths):
        """El modelo devuelve CLOSE (sin insight unificador): NO se publica
        nada; el hilo se cierra con el ultimo punto parado."""
        pb = _make_pb()
        pb.llm.generate = AsyncMock(return_value="CLOSE")
        comment = {"id": "c2", "parent_id": "c1", "content": "fair enough"}
        comments = [
            {"id": "c1", "content": "first message"},
            {"id": "c2", "parent_id": "c1", "content": "fair enough"},
        ]
        pb._memory = MagicMock()

        result = await pb._close_thread_decision("post-1", comment, comments, "user1", "tope")

        assert result == "let_stand"
        pb.api.create_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrap_up_never_published(self, _redirect_paths):
        pb = _make_pb()
        pb.llm.generate = AsyncMock(return_value="Great discussion, thanks for the debate everyone.")
        comment = {"id": "c2", "parent_id": "c1", "content": "agreed"}
        comments = [
            {"id": "c1", "content": "first message"},
            {"id": "c2", "parent_id": "c1", "content": "agreed"},
        ]

        result = await pb._close_thread_decision("post-1", comment, comments, "user1", "tope")

        assert result == "let_stand"
        pb.api.create_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_genuine_insight_is_published(self, _redirect_paths):
        pb = _make_pb()
        pb.llm.generate = AsyncMock(
            return_value=(
                "The unstated boundary is that both designs assume a monotonic "
                "failure rate, and neither survives a cliff."
            )
        )
        comment = {"id": "c2", "parent_id": "c1", "content": "you are right"}
        comments = [
            {"id": "c1", "content": "first message"},
            {"id": "c2", "parent_id": "c1", "content": "you are right"},
        ]

        result = await pb._close_thread_decision("post-1", comment, comments, "user1", "tope")

        assert result == "synthesized"
        pb.api.create_comment.assert_called_once()


# ── Pregunta directa: nunca cerrar sin responderla ───────────────

class TestDirectQuestionClose:
    @pytest.mark.parametrize("text", [
        "@comet_riobamba does the retry gate stay closed?",
        "Does your gate stay closed after recovery?",
    ])
    def test_direct_question_detected(self, text):
        assert PhaseB._is_direct_question(text) is True

    def test_non_question_not_detected(self):
        assert PhaseB._is_direct_question("the retry gate stays closed") is False
        assert PhaseB._is_direct_question("") is False
        assert PhaseB._is_direct_question(None) is False

    @pytest.mark.asyncio
    async def test_own_post_concession_without_insight_lets_stand(self, _redirect_paths):
        """Primera concesion cuyo cierre devuelve CLOSE: no se publica sintesis
        de relleno (let_stand)."""
        pb = _make_pb()
        pb.llm.generate = AsyncMock(return_value="CLOSE")
        result = await pb._post_own_reply("post-1", "comment-1", "user1", "A fair correction — I accept it")

        assert result is not None and result.get("status") == "closed_concession"
        pb.api.create_comment.assert_not_called()
        assert pb.llm.generate.await_count >= 1, "la sintesis se intento"


# ── Borrador + revision SOLO en tier_quality ─────────────────────

class TestQualityDraftCritique:
    @pytest.mark.asyncio
    async def test_flawed_draft_is_revised(self, _redirect_paths):
        pb = _make_pb()
        pb.llm.generate = AsyncMock(side_effect=[
            "does not add anything new, it paraphrases the other side",
            "The sharper point is that the backoff cap changes the failure mode entirely, and neither side named it.",
        ])
        final, log = await pb._critique_quality_draft("a mediocre paraphrase draft", "the original point")

        assert log.startswith("draft revised")
        assert "sharper point" in final
        assert pb.llm.generate.await_count == 2, "critica + revision"

    @pytest.mark.asyncio
    async def test_solid_draft_kept_without_revision(self, _redirect_paths):
        pb = _make_pb()
        pb.llm.generate = AsyncMock(return_value="OK")
        final, log = await pb._critique_quality_draft("a solid reply with a new mechanism", "source")

        assert log == "draft kept (critica aprueba)"
        assert final == "a solid reply with a new mechanism"
        assert pb.llm.generate.await_count == 1, "sin revision si aprueba"

    @pytest.mark.asyncio
    async def test_worse_revision_keeps_draft(self, _redirect_paths):
        pb = _make_pb()
        pb.llm.generate = AsyncMock(side_effect=[
            "does not answer the specific point",
            "too vague",  # revision peor: corta
        ])
        draft = "The mechanism is a monotonic cap on the backoff window that forces the queue to drain."
        final, log = await pb._critique_quality_draft(draft, "source")

        assert log.startswith("draft kept (revision peor")
        assert final == draft

    @pytest.mark.asyncio
    async def test_normal_reply_skips_critique(self, _redirect_paths):
        """Reply con tier flash (volumen general): SIN paso de critica."""
        pb = _make_pb()
        pb._critique_quality_draft = AsyncMock(return_value=("x", "n/a"))
        await pb._generate_own_post_reply("user1", "a comment", tier="flash")
        pb._critique_quality_draft.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_quality_reply_goes_through_critique(self, _redirect_paths):
        """Reply tier_quality (referente): SI pasa por critica."""
        pb = _make_pb()
        pb._critique_quality_draft = AsyncMock(return_value=("revised text", "draft revised (x)"))
        await pb._generate_own_post_reply("wl_author", "a comment", tier="quality")
        pb._critique_quality_draft.assert_awaited_once()
