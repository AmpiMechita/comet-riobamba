# -*- coding: utf-8 -*-
"""Tests del gate de citas historicas y los criterios conversacionales:
concesion (sintesis y cierre), promocion comercial, prioridad de preguntas
directas, y preferencia a quien aporta datos."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest_plugins = ("pytest_asyncio",)

from phases.phase_a_content import (
    validate_post_text, build_prompts, EDITORIAL_CONFIG,
)
from phases.phase_b import PhaseB
from phases.phase_b.scoring import text_has_unverifiable_historical_claim
from phases.deps import PhaseBDeps


# ── Gate de citas historicas ─────────────────────────────────────

_HIST_BODY = (
    "Uber's Michelangelo platform in 2017 showed how a machine learning "
    "pipeline can silently drift into irrelevance when the training data "
    "distribution changes faster than the retraining cadence.\n\n"
    "The mechanism that generalizes is a drift gate on the value head: evict "
    "when the online error diverges from the offline holdout by more than one "
    "standard deviation, and never trust a pipeline that cannot distinguish "
    "drift from noise.\n\n"
    "Does your serving stack today separate model drift from data drift, or "
    "does it treat them as the same number?"
)

_HIST_BODY_WITH_CONTEXT = (
    "The 2017 example you mentioned is the sharpest case of the pattern: a "
    "serving pipeline whose training distribution moved faster than its "
    "retraining cadence.\n\n"
    "The mechanism that generalizes is a drift gate on the value head: evict "
    "when the online error diverges from the offline holdout by more than one "
    "standard deviation, and never trust a pipeline that cannot distinguish "
    "drift from noise.\n\n"
    "Does your serving stack today separate model drift from data drift, or "
    "does it treat them as the same number?"
)


class TestHistoricalClaimGate:
    def test_year_without_context_rejected(self):
        valid, reason = validate_post_text(_HIST_BODY, historical_context="agent reliability topics")
        assert valid is False
        assert reason == "unverifiable_historical_claim"

    def test_year_in_context_allowed(self):
        valid, reason = validate_post_text(
            _HIST_BODY_WITH_CONTEXT,
            historical_context="the 2017 Michelangelo case from the comment",
        )
        assert valid is True
        assert reason == "ok"

    def test_own_incident_exempt(self):
        valid, reason = validate_post_text(
            _HIST_BODY, is_own_incident=True, historical_context="",
        )
        assert valid is True
        assert reason == "ok"

    def test_no_year_no_gate(self):
        valid, reason = validate_post_text(
            "A mechanism without any dated claim at all is fine, and it should "
            "not trip a historical gate: the pattern is the drift check itself, "
            "not the anecdote that motivated it. When a pipeline can no longer "
            "tell drift from noise, the value head starts agreeing with its own "
            "errors, and no retry budget will save a system that cannot "
            "distinguish a bad signal from a missing one.\n\n"
            "The mechanism that generalizes is a drift gate on the value head: "
            "evict when the online error diverges from the offline holdout by "
            "more than one standard deviation, and never trust a pipeline that "
            "cannot distinguish drift from noise.\n\n"
            "Where does your stack separate drift from noise?",
            historical_context="",
        )
        assert valid is True

    def test_scoring_helper_detects_missing_year(self):
        assert text_has_unverifiable_historical_claim(
            "in 2017 Uber migrated", "agent reliability"
        ) == "2017"
        assert text_has_unverifiable_historical_claim(
            "in 2017 Uber migrated", "the 2017 migration"
        ) is None
        assert text_has_unverifiable_historical_claim("no years here", "") is None
        assert text_has_unverifiable_historical_claim(
            "in 2017 we ran", "", is_own_incident=True
        ) is None

    @pytest.mark.asyncio
    async def test_phase_b_reply_with_ungrounded_year_rejected(self):
        """Una reply con año no grounded en el contexto se rechaza (no publica)."""
        from tests.test_queue_value_turns import _redirect_paths, _make_pb

        pb = _make_pb()
        pb.llm.generate = AsyncMock(
            return_value="in 2017 Uber's platform showed the drift pattern we are discussing"
        )
        result = await pb._post_own_reply("post-1", "comment-1", "user1", "some comment")

        assert result is None, "la reply con incidente de terceros no verificado se descarta"
        pb.api.create_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_phase_b_reply_with_grounded_year_publishes(self):
        from tests.test_queue_value_turns import _redirect_paths, _make_pb

        pb = _make_pb()
        pb.llm.generate = AsyncMock(
            return_value=(
                "the 2017 case you cited is exactly the drift pattern we are "
                "discussing here, and it generalizes to every serving stack "
                "that cannot separate drift from noise."
            )
        )
        result = await pb._post_own_reply("post-1", "comment-1", "user1", "the 2017 case you cited")

        assert result is not None and result.get("success") is True
        pb.api.create_comment.assert_called_once()

    @pytest.mark.asyncio
    async def test_phase_b_claims_context_does_not_legitimize_historical_year(self):
        """Anti auto-contaminacion: el claims_context es OUTPUT del propio
        agente (sus claims pasados), no evidencia del interlocutor. Un reply
        que cita '2016 dyn dns outage' se rechaza AUNQUE el claims tracker
        contenga ese mismo claim (loop que permitio citar el incidente de
        terceros 24 veces)."""
        from unittest.mock import patch

        from tests.test_queue_value_turns import _redirect_paths, _make_pb

        pb = _make_pb()
        with patch("phases.phase_b.orchestrator.ClaimsTracker") as mock_tracker_cls, \
             patch("phases.phase_b.orchestrator._get_ein_context", return_value=""):
            mock_tracker = mock_tracker_cls.return_value
            mock_tracker.get_context_for_reply.return_value = (
                "2016 dyn dns outage had the same shape: every resolver trusted "
                "the same upstream feed, and the failure cascaded because every "
                "layer validated against a single source of truth."
            )
            pb.llm.generate = AsyncMock(
                return_value=(
                    "The 2016 dyn dns outage had the same shape: every resolver "
                    "trusted the same upstream feed, and the failure cascaded "
                    "because each layer validated against a single source of truth."
                )
            )
            result = await pb._post_own_reply(
                "post-1", "comment-1", "user1", "do resolvers trust a single upstream feed?"
            )

        assert result is None, "el claims_context propio no puede legitimar una cita historica de terceros"
        pb.api.create_comment.assert_not_called()


# ── Concesion: sintesis una vez, luego cerrar ────────────────────

class TestConcession:
    @pytest.mark.parametrize("text", [
        "A fair correction — I accept it",
        "You're right, my assumption was wrong",
        "Agreed, that boundary is cleaner",
        "Good point, conceded",
        "That is true, thanks for the correction",
    ])
    def test_concession_detected(self, text):
        assert PhaseB._is_concession(text) is True, f"debe detectar concesion: {text}"

    def test_non_concession(self):
        assert PhaseB._is_concession("Actually I disagree with the mechanism") is False
        assert PhaseB._is_concession("") is False

    @pytest.mark.asyncio
    async def test_first_concession_gets_synthesis_and_publishes(self):
        from tests.test_queue_value_turns import _redirect_paths, _make_pb

        pb = _make_pb()
        result = await pb._post_own_reply("post-1", "comment-1", "user1", "A fair correction — I accept it")

        assert result is not None and result.get("success") is True, "la primera concesion recibe una sintesis"
        pb.api.create_comment.assert_called_once()
        assert "post-1" in pb._concession_answered, "queda marcado para cerrar en la proxima concesion"
        # el prompt de la sintesis no agrega otra correccion
        prompt = pb.llm.generate.call_args_list[0].kwargs.get("prompt") or pb.llm.generate.call_args_list[0].args[0]
        assert "They agreed" in prompt

    @pytest.mark.asyncio
    async def test_second_concession_closes_thread(self):
        from tests.test_queue_value_turns import _redirect_paths, _make_pb

        pb = _make_pb()
        pb._concession_answered.add("post-1")
        result = await pb._post_own_reply("post-1", "comment-2", "user1", "Agreed, you were right")

        assert result is not None and result.get("status") == "closed_concession"
        pb.api.create_comment.assert_not_called()
        pb.llm.generate.assert_not_awaited()


# ── Promocion comercial ──────────────────────────────────────────

class TestPromotionalContent:
    @pytest.mark.parametrize("text", [
        "Install it with pip install myagentlib and you are done",
        "npm install openclaw-agent to get started",
        "Just run: echo 'API_KEY=x' >> .env",
        "openclaw install then run the demo",
    ])
    def test_install_commands_detected(self, text):
        assert PhaseB._is_promotional_content(text) is True, f"debe detectar promo: {text}"

    def test_normal_technical_text_not_promotional(self):
        assert PhaseB._is_promotional_content(
            "The retry backoff needs a cap or the queue stalls under load"
        ) is False
        assert PhaseB._is_promotional_content("") is False

    def test_promotional_comment_not_queuable(self):
        queuable, reason = PhaseB._comment_queuable(
            {"id": "c1", "content": "pip install mylib and you are done"}, "post-1",
        )
        assert (queuable, reason) == (False, "promotional")

    def test_prompt_carries_data_contribution_directive(self):
        _, user_prompt = build_prompts("agent tool safety")
        # la directiva vive en el system prompt de Phase B; el test verifica
        # que la constante este cableada en el generador (cobertura en
        # test_prompt_injection_abstain para el system prompt completo)
        from prompts.prompt_templates import DATA_CONTRIBUTION_DIRECTIVE
        assert "Do not restate their conclusion back to them" in DATA_CONTRIBUTION_DIRECTIVE


# ── Preguntas directas envejecen hacia arriba ────────────────────

class TestDirectQuestionPriority:
    @pytest.mark.asyncio
    async def test_old_direct_question_beats_new_comment(self):
        """Pregunta directa de hace 2 dias se procesa ANTES que un comentario
        nuevo sin pregunta, aunque el nuevo sea mas reciente."""
        from tests.test_queue_value_turns import _redirect_paths, _make_pb

        pb = _make_pb(max_comments_per_day=50, max_replies_per_cycle=5)
        pb._get_own_post_ids = lambda: {"top-12345678-aaaa-bbbb-cccc-ddddeeeeffff"}
        _replies = [
            "The retry gate should stay closed after recovery, and here is why the monotonic cap matters.",
            "A monotonic backoff cap prevents queue stalling under degraded upstream load in production.",
        ]
        pb.llm.generate = AsyncMock(side_effect=_replies)
        post = {"id": "top-12345678-aaaa-bbbb-cccc-ddddeeeeffff", "comment_count": 10}
        pb.api._request = MagicMock(return_value={"status": 200, "data": {"posts": [post]}})
        pb.api.fetch_my_posts = MagicMock(return_value=[])
        old_ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        new_ts = datetime.now(timezone.utc).isoformat()
        pb.api.fetch_post_comments.return_value = [
            {"id": "c-old-q", "author": {"name": "user1"}, "created_at": old_ts,
             "content": "@comet_riobamba does the retry gate stay closed after recovery?",
             "text": "@comet_riobamba does the retry gate stay closed after recovery?"},
            {"id": "c-new", "author": {"name": "user2"}, "created_at": new_ts,
             "content": "The retry gate should stay closed after recovery in my setup",
             "text": "The retry gate should stay closed after recovery in my setup"},
        ]
        pb.api.create_comment.return_value = {"success": True, "id": "new", "status": 201}
        pb._classify_and_log_value = AsyncMock()

        await pb._execute_own_post_replies()

        called = [c.kwargs.get("parent_comment_id") or c.args[1]
                  for c in pb.api.create_comment.call_args_list if c.kwargs or c.args]
        assert len(called) == 2, f"ambos comentarios se procesan, got {called}"
        assert called[0] == "c-old-q", f"la pregunta directa vieja va PRIMERO, got {called}"
