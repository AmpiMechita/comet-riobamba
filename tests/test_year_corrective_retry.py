# -*- coding: utf-8 -*-
"""Tests de la regeneracion correctiva por año no verificable (24/08/2026).

Sintoma: el gate anti-fabricacion rechazaba la reply completa ('año 1989'),
quemaba un intento LLM y con MAX_LLM_ATTEMPTS=3 el ciclo moria sin
comentarios. Ahora hay UN reintento con instruccion correctiva; si el
modelo insiste en inventar cronologia, se rechaza igual.
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
    "id": "test-post-1",
    "author": {"name": "somegeneral"},
    "title": "On verification pipelines for agents",
    "content": "High-confidence model outputs need replay contracts. " * 10,
}


class TestYearCorrectiveRetry:

    @pytest.mark.asyncio
    async def test_bad_year_blocked_when_unverifiable_historical_claim(self):
        """Reply que contiene año no verificable es bloqueado; no hay retry."""
        pb = _make_pb()
        bad = "This mirrors the 1989 Dyn attack pattern applied to agent pipelines."
        pb.llm.generate = AsyncMock(return_value=bad)
        # sin best-of, sin claim checker, sin EIN
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("phases.phase_b.orchestrator.extract_claim", AsyncMock(return_value=None))
            reply, _claim = await pb._generate_reply_for_post(POST, bestof=False, tier="flash")
        assert reply == ""
        # Solo un llamado al LLM, ningún retry posterior
        assert pb.llm.generate.await_count == 1

    @pytest.mark.asyncio
    async def test_persistent_bad_year_rejected(self):
        """Si el modelo insiste con años inventados, se rechaza (anti-fabricacion)."""
        pb = _make_pb()
        bad1 = "Like the 1971 arpanet era routing tables, agents repeat this."
        bad2 = "As in 1957, the dashboard promised autonomy."
        pb.llm.generate = AsyncMock(side_effect=[bad1, bad2])
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("phases.phase_b.orchestrator.extract_claim", AsyncMock(return_value=None))
            reply, _claim = await pb._generate_reply_for_post(POST, bestof=False, tier="flash")
        assert reply == ""

    @pytest.mark.asyncio
    async def test_clean_reply_untouched_single_call(self):
        """Reply sin años: una sola llamada, cero friccion."""
        pb = _make_pb()
        clean = ("The mechanism is a replay contract: re-run from logged inputs and "
                 "gate at per-step match rate. What threshold would you enforce?")
        pb.llm.generate = AsyncMock(return_value=clean)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("phases.phase_b.orchestrator.extract_claim", AsyncMock(return_value=None))
            reply, _claim = await pb._generate_reply_for_post(POST, bestof=False, tier="flash")
        assert reply == clean
        assert pb.llm.generate.await_count == 1
