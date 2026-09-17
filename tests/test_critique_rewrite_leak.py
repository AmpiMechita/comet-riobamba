# -*- coding: utf-8 -*-
"""Tests: el rewrite de la critica con prompt-leak conserva el borrador.

Hallazgo 24/08: el rewrite (tier free) a veces devolvia el razonamiento del
modelo ('We need to rewrite the draft fixing exactly...') en vez de la reply
revisada; ese meta-texto pasaba el check de longitud, reemplazaba al borrador
valido y el gate de publicacion lo bloqueaba -> reply perdida entera
(7 casos en un dia).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from phases.phase_b import PhaseB
from phases.deps import PhaseBDeps


def _make_pb():
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"delay_between_comments": 0},
        agent_name="COMET-RIOBAMBA",
    )
    pb = PhaseB(deps)
    pb.llm = MagicMock()
    return pb


DRAFT_OK = ("Replay fidelity beats trace volume: re-run from logged inputs "
            "and gate at per-step match rate of 0.9.")


class TestCritiqueRewriteLeakGuard:

    @pytest.mark.asyncio
    async def test_leaked_rewrite_keeps_original_draft(self):
        """Critic aprueba cambios, rewrite devuelve meta-texto -> draft original."""
        pb = _make_pb()
        # llamadas al llm: [0]=critic verdict ('needs fix'), [1]=rewrite (LEAK)
        verdict = "Mention the failure mode when inputs are truncated."
        leaked_rewrite = ("We need to rewrite the draft fixing exactly this: "
                          "the user says add truncation. First I will analyze "
                          "the draft, then produce the final answer text.")
        pb.llm.generate = AsyncMock(side_effect=[verdict, leaked_rewrite])
        reply, log = await pb._critique_quality_draft(DRAFT_OK, "SOURCE TEXT")
        assert reply == DRAFT_OK, f"debe conservar el borrador, got: {reply[:60]}"
        assert "prompt-leak" in log

    @pytest.mark.asyncio
    async def test_clean_rewrite_accepted(self):
        pb = _make_pb()
        verdict = "Add the threshold."
        clean_rewrite = ("Replay fidelity beats trace volume: re-run from logged "
                         "inputs and gate at per-step match rate of 0.9 under "
                         "truncation pressure.")
        pb.llm.generate = AsyncMock(side_effect=[verdict, clean_rewrite])
        reply, log = await pb._critique_quality_draft(DRAFT_OK, "SOURCE TEXT")
        assert reply == clean_rewrite
        assert "draft revised" in log

    @pytest.mark.asyncio
    async def test_critic_ok_keeps_draft_single_path(self):
        pb = _make_pb()
        pb.llm.generate = AsyncMock(return_value="OK")
        reply, log = await pb._critique_quality_draft(DRAFT_OK, "SOURCE TEXT")
        assert reply == DRAFT_OK
        assert "aprueba" in log
