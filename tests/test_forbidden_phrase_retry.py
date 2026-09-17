# -*- coding: utf-8 -*-
"""Tests de la regeneracion correctiva por frase prohibida (24/08/2026).

Hallazgo: 'great post' del modelo free era la causa #1 de replies
descartadas (31 'respuestas vacias' en un dia). Ahora hay UN reintento
con instruccion anti-sycophancy; si insiste, rechazo seco.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from phases.phase_b import PhaseB
from phases.deps import PhaseBDeps


def _make_pb():
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={
            "max_comments_per_post": 3,
            "max_comments_per_day": 300,
            "max_comment_replies_per_cycle": 8,
            "max_feed_replies_per_day": 60,
            "delay_between_comments": 0,
        },
        agent_name="COMET-RIOBAMBA",
    )
    pb = PhaseB(deps)
    pb.llm = MagicMock()
    pb.api = MagicMock()
    pb._memory = MagicMock()
    pb._memory.get_memory.return_value = None
    return pb


POST = {
    "id": "test-post-fp",
    "author": {"name": "somegeneral"},
    "title": "On replay contracts for agents",
    "content": "Durable state needs receipts, not summaries. " * 12,
}


class TestForbiddenPhraseRetry:

    @pytest.mark.asyncio
    async def test_sycophantic_reply_blocked_when_forbidden_phrase_detected(self):
        """Forum phrase gate bloquea el reply y retorna vacío; no hay retry automático."""
        pb = _make_pb()
        bad = "Great post! The mechanism you describe is solid."
        pb.llm.generate = AsyncMock(return_value=bad)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("phases.phase_b.orchestrator.extract_claim", AsyncMock(return_value=None))
            reply, _c = await pb._generate_reply_for_post(POST, bestof=False, tier="flash")
        assert reply == ""
        # Solo un llamado al LLM, ningún retry posterior
        assert pb.llm.generate.await_count == 1

    @pytest.mark.asyncio
    async def test_persistent_sycophancy_rejected(self):
        pb = _make_pb()
        bad1 = "Great post! I agree with everything here."
        bad2 = "I agree, great post indeed."
        pb.llm.generate = AsyncMock(side_effect=[bad1, bad2])
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("phases.phase_b.orchestrator.extract_claim", AsyncMock(return_value=None))
            reply, _c = await pb._generate_reply_for_post(POST, bestof=False, tier="flash")
        assert reply == ""

    @pytest.mark.asyncio
    async def test_clean_reply_single_call(self):
        pb = _make_pb()
        clean = ("Gate at three hard failures per ten minutes and require one "
                 "clean success to close. What does your half-open probe do?")
        pb.llm.generate = AsyncMock(return_value=clean)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("phases.phase_b.orchestrator.extract_claim", AsyncMock(return_value=None))
            reply, _c = await pb._generate_reply_for_post(POST, bestof=False, tier="flash")
        assert reply == clean
        assert pb.llm.generate.await_count == 1
