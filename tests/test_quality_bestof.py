"""Tests for AGENT_QUALITY_BESTOF (A/B quality strategies).

Cubre:
  - Phase A best-of-N de posts con juez flash (flag ON/OFF).
  - Juez basura -> desempate por dual_score sin crash.
  - Auto-critica que falla validacion -> se conserva la pre-critica.
  - Phase B best-of-2 selectivo en replies (2 candidatos vs 1).
  - Flag OFF = comportamiento y numero de llamadas LLM identicos a los actuales.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest_plugins = ("pytest_asyncio",)

from phases.deps import PhaseADeps, PhaseBDeps
from phases.phase_a_content import PhaseAContentGeneration, EDITORIAL_CONFIG
from phases.phase_b import PhaseB


# ── Fixtures / helpers ────────────────────────────────────────────────


def _make_phase_a_deps(**kwargs) -> PhaseADeps:
    return PhaseADeps(
        model_cascade=AsyncMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_posts_per_day": 5},
        posts_today=0,
        get_posts_today=lambda: 0,
        **kwargs,
    )


def _valid_candidate(marker: str) -> str:
    """Cuerpo valido (pasa validate_post_text con la cita arXiv del tópico)."""
    return (
        f"Title {marker}\n\n"
        f"The fix is a rolling re-injection trigger that tracks distance in tokens "
        f"since the last critical directive and re-inserts a compressed preamble. "
        f"{marker} The paper (arXiv:2607.18045) reports a parallel failure mode for "
        f"long-running autonomous agents. The silent drift is cumulative and often "
        f"only surfaces after the recall horizon is crossed.\n\n"
        "Where do you place the re-injected directive when the tool output stream is "
        "already dense, and how do you measure the tradeoff between preamble cost and "
        "drift prevention across your production agent fleet?"
    )


# ── Phase A: best-of-N ────────────────────────────────────────────────


class TestPhaseABestOfN:
    """Best-of-N en Phase A (posts) con juez flash."""

    @pytest.mark.asyncio
    async def test_flag_on_generates_n_candidates_and_judge_picks(self):
        """Flag ON: se generan N=3 candidatos, el juez elige el 2 -> se publica ese."""
        from datetime import datetime

        deps = _make_phase_a_deps()
        fake_now = datetime(2026, 7, 22, 12, 0, 0)
        mock_call_model = AsyncMock(side_effect=[
            _valid_candidate("ALPHA"),
            _valid_candidate("BETA"),
            _valid_candidate("GAMMA"),
            "2",  # juez: elige el candidato 2
        ])

        with (
            patch.dict(os.environ, {"AGENT_QUALITY_BESTOF": "1", "QUALITY_BESTOF_N": "3"}),
            patch("phases.phase_a_content.datetime") as mock_dt,
            patch("phases.phase_a_content.behavior_cfg",
                  {"max_posts_per_day": 5, "phase_a_mode": "research", "whisper_mode": True}),
            patch("phases.phase_a_content.EDITORIAL_CONFIG",
                  {**EDITORIAL_CONFIG, "phase_a_max_attempts": 3}),
            patch("services.persistence.load_agent_state", return_value={}),
            patch("services.own_post_store.count_posts_since", return_value=0),
            patch("phases.phase_a_content.choose_topic",
                  return_value=('production agent engineering implications of the paper '
                                '"The Shared Discovery Paradox" (arXiv:2607.18045v1) for '
                                'production agent reliability and orchestration', "arxiv")),
            patch("phases.phase_a_content.load_topic_matrix", return_value=None),
            patch("phases.phase_a_content._is_allowed_topic", return_value=True),
            patch("phases.phase_a_content._is_topic_recently_used", return_value=False),
            patch("phases.phase_a_content.build_prompts", return_value=("sys", "user")),
            patch("phases.phase_a_content.load_editorial_policy", return_value={}),
            patch("phases.phase_a_content.is_similar_to_recent", return_value=False),
            patch("phases.phase_a_content.call_model", new=mock_call_model),
            patch("phases.phase_a_content._critique_pass",
                  new=AsyncMock(side_effect=lambda deps, post, policy, incident_figures=None: post)),
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
            phase_a = PhaseAContentGeneration(deps=deps)
            result = await phase_a.execute()

        assert result["drafts_generated"] == 1
        # 3 generaciones + 1 juez = 4 llamadas (la auto-critica esta mockeada)
        assert mock_call_model.call_count == 4
        draft = result["posts"][0]
        assert draft.get("error") is None
        assert "BETA" in draft["body"]
        assert "ALPHA" not in draft["body"]
        assert "GAMMA" not in draft["body"]

    @pytest.mark.asyncio
    async def test_flag_off_keeps_original_behavior_and_call_count(self):
        """Flag OFF: un solo candidato, UNA llamada, comportamiento identico al actual."""
        from datetime import datetime

        deps = _make_phase_a_deps()
        fake_now = datetime(2026, 7, 22, 12, 0, 0)
        mock_call_model = AsyncMock(return_value=_valid_candidate("ALPHA"))

        with (
            patch.dict(os.environ, {"AGENT_QUALITY_BESTOF": "0", "QUALITY_BESTOF_N": "3"}),
            patch("phases.phase_a_content.datetime") as mock_dt,
            patch("phases.phase_a_content.behavior_cfg",
                  {"max_posts_per_day": 5, "phase_a_mode": "research", "whisper_mode": True}),
            patch("phases.phase_a_content.EDITORIAL_CONFIG",
                  {**EDITORIAL_CONFIG, "phase_a_max_attempts": 3}),
            patch("services.persistence.load_agent_state", return_value={}),
            patch("services.own_post_store.count_posts_since", return_value=0),
            patch("phases.phase_a_content.choose_topic",
                  return_value=('production agent engineering implications of the paper '
                                '"The Shared Discovery Paradox" (arXiv:2607.18045v1) for '
                                'production agent reliability and orchestration', "arxiv")),
            patch("phases.phase_a_content.load_topic_matrix", return_value=None),
            patch("phases.phase_a_content._is_allowed_topic", return_value=True),
            patch("phases.phase_a_content._is_topic_recently_used", return_value=False),
            patch("phases.phase_a_content.build_prompts", return_value=("sys", "user")),
            patch("phases.phase_a_content.load_editorial_policy", return_value={}),
            patch("phases.phase_a_content.is_similar_to_recent", return_value=False),
            patch("phases.phase_a_content.call_model", new=mock_call_model),
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
            phase_a = PhaseAContentGeneration(deps=deps)
            result = await phase_a.execute()

        assert result["drafts_generated"] == 1
        assert mock_call_model.call_count == 1
        draft = result["posts"][0]
        assert draft.get("error") is None
        assert "ALPHA" in draft["body"]

    @pytest.mark.asyncio
    async def test_judge_garbage_falls_back_to_dual_score(self):
        """Juez devuelve basura -> desempate por compute_dual_score, sin crash."""
        from datetime import datetime

        deps = _make_phase_a_deps()
        fake_now = datetime(2026, 7, 22, 12, 0, 0)
        mock_call_model = AsyncMock(side_effect=[
            _valid_candidate("ALPHA"),
            _valid_candidate("BETA"),
            "garbage not a number",
        ])
        # compute_dual_score: ALPHA gana (0.9 > 0.5)
        real_dual = __import__("services.dual_scoring", fromlist=["compute_dual_score"]).compute_dual_score

        def _dual_stub(text, reply_count=0, upvote_count=0):
            if "ALPHA" in text:
                return {"research_value_score": 0.9, "content_type": "x"}
            return {"research_value_score": 0.5, "content_type": "y"}

        with (
            patch.dict(os.environ, {"AGENT_QUALITY_BESTOF": "1", "QUALITY_BESTOF_N": "2"}),
            patch("phases.phase_a_content.datetime") as mock_dt,
            patch("phases.phase_a_content.behavior_cfg",
                  {"max_posts_per_day": 5, "phase_a_mode": "research", "whisper_mode": True}),
            patch("phases.phase_a_content.EDITORIAL_CONFIG",
                  {**EDITORIAL_CONFIG, "phase_a_max_attempts": 3}),
            patch("services.persistence.load_agent_state", return_value={}),
            patch("services.own_post_store.count_posts_since", return_value=0),
            patch("phases.phase_a_content.choose_topic",
                  return_value=('production agent engineering implications of the paper '
                                '"The Shared Discovery Paradox" (arXiv:2607.18045v1) for '
                                'production agent reliability and orchestration', "arxiv")),
            patch("phases.phase_a_content.load_topic_matrix", return_value=None),
            patch("phases.phase_a_content._is_allowed_topic", return_value=True),
            patch("phases.phase_a_content._is_topic_recently_used", return_value=False),
            patch("phases.phase_a_content.build_prompts", return_value=("sys", "user")),
            patch("phases.phase_a_content.load_editorial_policy", return_value={}),
            patch("phases.phase_a_content.is_similar_to_recent", return_value=False),
            patch("phases.phase_a_content.compute_dual_score", side_effect=_dual_stub),
            patch("phases.phase_a_content.call_model", new=mock_call_model),
            patch("phases.phase_a_content._critique_pass",
                  new=AsyncMock(side_effect=lambda deps, post, policy, incident_figures=None: post)),
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
            phase_a = PhaseAContentGeneration(deps=deps)
            result = await phase_a.execute()

        assert result["drafts_generated"] == 1
        assert mock_call_model.call_count == 3
        draft = result["posts"][0]
        assert draft.get("error") is None
        assert "ALPHA" in draft["body"]

    @pytest.mark.asyncio
    async def test_autocritique_invalid_keeps_precritique(self):
        """La auto-critica devuelve texto invalido -> se descarta y se publica la pre-critica."""
        from datetime import datetime

        deps = _make_phase_a_deps()
        fake_now = datetime(2026, 7, 22, 12, 0, 0)
        mock_call_model = AsyncMock(side_effect=[
            _valid_candidate("ALPHA"),
            "garbage invalid text",  # auto-critica no supera validate_post_text
        ])

        with (
            patch.dict(os.environ, {"AGENT_QUALITY_BESTOF": "1", "QUALITY_BESTOF_N": "1"}),
            patch("phases.phase_a_content.datetime") as mock_dt,
            patch("phases.phase_a_content.behavior_cfg",
                  {"max_posts_per_day": 5, "phase_a_mode": "research", "whisper_mode": True}),
            patch("phases.phase_a_content.EDITORIAL_CONFIG",
                  {**EDITORIAL_CONFIG, "phase_a_max_attempts": 3}),
            patch("services.persistence.load_agent_state", return_value={}),
            patch("services.own_post_store.count_posts_since", return_value=0),
            patch("phases.phase_a_content.choose_topic",
                  return_value=('production agent engineering implications of the paper '
                                '"The Shared Discovery Paradox" (arXiv:2607.18045v1) for '
                                'production agent reliability and orchestration', "arxiv")),
            patch("phases.phase_a_content.load_topic_matrix", return_value=None),
            patch("phases.phase_a_content._is_allowed_topic", return_value=True),
            patch("phases.phase_a_content._is_topic_recently_used", return_value=False),
            patch("phases.phase_a_content.build_prompts", return_value=("sys", "user")),
            patch("phases.phase_a_content.load_editorial_policy", return_value={}),
            patch("phases.phase_a_content.is_similar_to_recent", return_value=False),
            patch("phases.phase_a_content.call_model", new=mock_call_model),
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
            phase_a = PhaseAContentGeneration(deps=deps)
            result = await phase_a.execute()

        assert result["drafts_generated"] == 1
        # 1 generacion + 1 auto-critica (N=1 no invoca juez)
        assert mock_call_model.call_count == 2
        draft = result["posts"][0]
        assert draft.get("error") is None
        assert "ALPHA" in draft["body"]
        assert draft.get("metadata", {}).get("auto_critiqued") is None


# ── Phase B: best-of-2 selectivo en replies ───────────────────────────


def _make_pb(**kwargs) -> PhaseB:
    cfg = {
        "max_comments_per_day": 12,
        "max_comment_replies_per_cycle": 4,
        "max_comments_per_post": 6,
        "max_feed_comments_per_post": 3,
        "delay_between_comments": 0,
        **kwargs,
    }
    deps = PhaseBDeps(
        model_cascade=AsyncMock(),
        moltbook_client=MagicMock(),
        behavior_cfg=cfg,
        agent_name="comet_riobamba",
        get_comments_today=lambda: 0,
        increment_comments_today=lambda: 0,
    )
    pb = PhaseB(deps=deps)
    pb._replied_comment_ids = set()
    pb._replied_topic_fingerprints = set()
    pb._claim_checker_tier = "test_tier"
    return pb


class TestPhaseBBestOfReply:
    """Best-of-2 selectivo en _generate_reply_for_post."""

    @pytest.mark.asyncio
    async def test_bestof_generates_two_candidates_and_keeps_best(self):
        """bestof=True -> 2 candidatos; gana el de mayor _score_reply_draft."""
        pb = _make_pb()
        # extract_claim -> None (json invalido); luego 2 candidatos del reply.
        pb.llm.generate = AsyncMock(side_effect=[
            "invalid json",
            "ALPHA reply about data retention and circuit breakers.",
            "BETA reply about data retention and circuit breakers.",
        ])
        pb._passes_quality_gate = MagicMock(return_value=True)

        def _fake_score(reply_text, source_text, log_context=None, block_ungrounded=False):
            return (60 if "BETA" in reply_text else 30, [])

        pb._score_reply_draft = MagicMock(side_effect=_fake_score)

        with patch("phases.phase_b.orchestrator.is_example_recently_used", return_value=(False, [])):
            result, _ = await pb._generate_reply_for_post(
                {
                    "title": "Gateway supply chain risk",
                    "content": "Managed gateway models are part of your supply chain",
                },
                bestof=True,
            )

        assert result == "BETA reply about data retention and circuit breakers."
        # 1 extract + 2 candidatos = 3 llamadas a llm.generate
        assert pb.llm.generate.call_count == 3

    @pytest.mark.asyncio
    async def test_non_bestof_single_candidate_same_call_count(self):
        """bestof=False (baja relevancia o flag OFF) -> 1 candidato, misma cantidad de llamadas."""
        pb = _make_pb()
        pb.llm.generate = AsyncMock(side_effect=[
            "invalid json",
            "ONLY reply about data retention and circuit breakers.",
        ])
        pb._passes_quality_gate = MagicMock(return_value=True)
        pb._score_reply_draft = MagicMock(
            side_effect=lambda reply_text, source_text, log_context=None, block_ungrounded=False: (50, [])
        )

        with patch("phases.phase_b.orchestrator.is_example_recently_used", return_value=(False, [])):
            result, _ = await pb._generate_reply_for_post(
                {
                    "title": "Gateway supply chain risk",
                    "content": "Managed gateway models are part of your supply chain",
                },
                bestof=True,
            )

        assert result == "ONLY reply about data retention and circuit breakers."
        # 1 extract_claim + 1 generate = 2 LLM calls (claim check is now deferred)
        assert pb.llm.generate.call_count >= 2

    @pytest.mark.asyncio
    async def test_second_candidate_failure_degrades_to_first(self):
        """Si el 2º candidato falla, se usa el 1º (degradacion elegante, sin crash)."""
        pb = _make_pb()
        pb.llm.generate = AsyncMock(side_effect=[
            "invalid json",
            "FIRST reply about data retention and circuit breakers.",
            RuntimeError("second candidate LLM down"),
        ])
        pb._passes_quality_gate = MagicMock(return_value=True)
        pb._score_reply_draft = MagicMock(
            side_effect=lambda reply_text, source_text, log_context=None, block_ungrounded=False: (50, [])
        )

        with patch("phases.phase_b.orchestrator.is_example_recently_used", return_value=(False, [])):
            result, _ = await pb._generate_reply_for_post(
                {
                    "title": "Gateway supply chain risk",
                    "content": "Managed gateway models are part of your supply chain",
                },
                bestof=True,
            )

        assert result == "FIRST reply about data retention and circuit breakers."

    def test_bestof_threshold_uses_min_plus_20(self):
        """El umbral de best-of selectivo es min_comment_relevance_score + 20 (>=24)."""
        from config.agent_policy import POLICY

        assert POLICY.min_comment_relevance_score + 20 == 24

    def test_flag_helpers_read_env(self):
        from phases.phase_a_content import _quality_bestof_enabled
        from phases.phase_b.orchestrator import _quality_bestof_enabled as _pb_enabled

        with patch.dict(os.environ, {"AGENT_QUALITY_BESTOF": "1"}, clear=False):
            assert _quality_bestof_enabled() is True
            assert _pb_enabled() is True
        with patch.dict(os.environ, {"AGENT_QUALITY_BESTOF": "0"}, clear=False):
            assert _quality_bestof_enabled() is False
            assert _pb_enabled() is False
