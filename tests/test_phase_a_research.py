"""Tests for Phase A research mode."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytest_plugins = ("pytest_asyncio",)

from phases.phase_a_content import (
    build_prompts, choose_topic, EDITORIAL_CONFIG,
    RESEARCH_CLOSING_TEMPLATES, _topic_with_matrix_fallback,
    compute_topic_weights, _looks_low_quality,
)


class TestResearchMode:
    def test_research_prompt_contains_problem_section(self):
        """Research mode prompt must mention PROBLEM section."""
        sys_prompt, user_prompt = build_prompts("agent tool safety", mode="research")
        assert "PROBLEM" in user_prompt
        assert "PROPOSAL" in user_prompt
        assert "RESEARCH QUESTION" in user_prompt

    def test_expository_prompt_does_not_contain_research_sections(self):
        """Expository mode must NOT contain research-specific sections."""
        sys_prompt, user_prompt = build_prompts("agent tool safety", mode="expository")
        assert "PROBLEM" not in user_prompt
        assert "RESEARCH QUESTION" not in user_prompt

    def test_research_mode_allows_question_ending(self):
        """Research mode should set question_ending_allowed=True."""
        sys_prompt, user_prompt = build_prompts("test topic", mode="research")
        assert "Question ending allowed: True" in sys_prompt

    def test_expository_mode_disallows_question_ending(self):
        """Expository mode should set question_ending_allowed=False."""
        sys_prompt, user_prompt = build_prompts("test topic", mode="expository")
        assert "Question ending allowed: False" in sys_prompt

    def test_research_closing_templates_are_defined(self):
        """There must be at least 3 research closing templates."""
        assert len(RESEARCH_CLOSING_TEMPLATES) >= 3

    def test_research_closing_templates_contain_question(self):
        """Each closing template must end with a question mark."""
        for tmpl in RESEARCH_CLOSING_TEMPLATES:
            assert "?" in tmpl, f"Template '{tmpl}' must contain a question"

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_reads_agenda_in_research_mode(self, mock_load):
        """In research mode, choose_topic should read from agenda first."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "agenda topic 1", "source": "test"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert topic == "agenda topic 1"
        assert source == "test"
        mock_agenda.get_uncovered_topics.assert_called_once_with(limit=50)

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_falls_back_when_agenda_empty(self, mock_load):
        """When agenda is empty, choose_topic should fallback to roadmap/static."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = []
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert isinstance(topic, str) and isinstance(source, str)
        assert len(topic) > 0

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_filters_phase_b_feed_by_default(self, mock_load):
        """Topic with source='phase_b_feed' is excluded from Phase A by default."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "feed artifact", "source": "phase_b_feed"},
        ]
        mock_load.return_value = mock_agenda
        # All topics filtered → falls through to roadmap/static fallback
        topic, source = choose_topic(mode="research")
        assert isinstance(topic, str) and isinstance(source, str)
        assert len(topic) > 0
        assert topic != "feed artifact"

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_includes_phase_b_feed_when_env_set(self, mock_load):
        """Topic with source='phase_b_feed' IS included when ALLOW_PHASE_B_FEED_TOPICS=true."""
        os.environ["ALLOW_PHASE_B_FEED_TOPICS"] = "true"
        try:
            mock_agenda = MagicMock()
            mock_agenda.get_uncovered_topics.return_value = [
                {"topic": "feed artifact", "source": "phase_b_feed"},
            ]
            mock_load.return_value = mock_agenda
            topic, source = choose_topic(mode="research")
            assert topic == "feed artifact"
            assert source == "phase_b_feed"
        finally:
            os.environ.pop("ALLOW_PHASE_B_FEED_TOPICS", None)

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_includes_human_seeded(self, mock_load):
        """Topic with source='human_seeded' is always included."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "legit topic", "source": "human_seeded"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert topic == "legit topic"
        assert source == "human_seeded"

    # ── Orden por recencia (choose_topic) ─────────────────────────

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_prioritizes_most_recent_created_at(self, mock_load):
        """choose_topic elige el topic con created_at mas reciente, no el primero de la lista."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "old topic", "source": "agenda", "created_at": "2026-07-01"},
            {"topic": "new topic", "source": "agenda", "created_at": "2026-07-20"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert topic == "new topic"
        assert source == "agenda"

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_missing_created_at_treated_as_oldest(self, mock_load):
        """Sin created_at (None/empty) el topic no debe ganarle a uno con fecha."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "no date", "source": "agenda"},
            {"topic": "has date", "source": "agenda", "created_at": "2026-07-15"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert topic == "has date"
        assert source == "agenda"

    # ── Orden por recencia (_topic_with_matrix_fallback) ──────────

    @patch("phases.phase_a_content.load_agenda")
    def test_topic_with_matrix_fallback_prioritizes_most_recent(self, mock_load):
        """_topic_with_matrix_fallback tambien ordena por created_at descendente."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "old matrix", "source": "agenda", "created_at": "2026-07-01"},
            {"topic": "new matrix", "source": "agenda", "created_at": "2026-07-20"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = _topic_with_matrix_fallback(mode="research", matrix=None)
        assert topic == "new matrix"
        assert source == "agenda"

    @patch("phases.phase_a_content.load_agenda")
    def test_topic_with_matrix_fallback_missing_created_at_oldest(self, mock_load):
        """_topic_with_matrix_fallback trata created_at ausente como el mas antiguo."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "no date matrix", "source": "agenda"},
            {"topic": "has date matrix", "source": "agenda", "created_at": "2026-07-15"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = _topic_with_matrix_fallback(mode="research", matrix=None)
        assert topic == "has date matrix"
        assert source == "agenda"

    # ── Filtro phase_b_feed con UUID (bug real en produccion) ────

    @patch("phases.phase_a_content.load_agenda")
    def test_choose_topic_filters_phase_b_feed_with_uuid_suffix(self, mock_load):
        """source='phase_b_feed:<uuid>' debe filtrarse igual que 'phase_b_feed' pelado."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "feed uuid", "source": "phase_b_feed:84303887-3f7c-4e51-863b-79b3344bf790",
             "created_at": "2026-07-20"},
            {"topic": "agenda topic", "source": "agenda", "created_at": "2026-07-01"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = choose_topic(mode="research")
        assert topic == "agenda topic"
        assert source == "agenda"

    @patch("phases.phase_a_content.load_agenda")
    def test_topic_with_matrix_fallback_filters_phase_b_feed_with_uuid(self, mock_load):
        """_topic_with_matrix_fallback tambien filtra source='phase_b_feed:<uuid>'."""
        mock_agenda = MagicMock()
        mock_agenda.get_uncovered_topics.return_value = [
            {"topic": "feed uuid", "source": "phase_b_feed:84303887-3f7c-4e51-863b-79b3344bf790",
             "created_at": "2026-07-20"},
            {"topic": "agenda topic", "source": "agenda", "created_at": "2026-07-01"},
        ]
        mock_load.return_value = mock_agenda
        topic, source = _topic_with_matrix_fallback(mode="research", matrix=None)
        assert topic == "agenda topic"
        assert source == "agenda"


# ── Fix 1: Pacing check antes del loop de generación ────────────

@pytest.mark.asyncio
async def test_execute_pacing_blocks_before_model_call():
    """Pacing check debe ejecutarse ANTES de llamar al modelo (no gasta LLM si no se puede publicar)."""
    from datetime import datetime, timedelta
    from phases.deps import PhaseADeps
    from phases.phase_a_content import PhaseAContentGeneration

    deps = PhaseADeps(
        model_cascade=AsyncMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_posts_per_day": 5},
        posts_today=0,
        get_posts_today=lambda: 0,
    )

    fake_now = datetime(2026, 7, 22, 12, 0, 0)

    with (
        patch("phases.phase_a_content.datetime") as mock_dt,
        patch("phases.phase_a_content.behavior_cfg", {"max_posts_per_day": 5, "phase_a_mode": "research"}),
        patch("services.persistence.load_agent_state") as mock_state,
        patch("phases.phase_a_content.choose_topic", return_value=("test topic", "agenda")),
        patch("phases.phase_a_content._is_allowed_topic", return_value=True),
        patch("phases.phase_a_content._is_topic_recently_used", return_value=False),
        patch("phases.phase_a_content.build_prompts", return_value=("sys", "user")),
        patch("phases.phase_a_content.load_editorial_policy", return_value={}),
        patch("phases.phase_a_content.call_model") as mock_call_model,
    ):
        mock_dt.now.return_value = fake_now
        mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
        mock_state.return_value = {"last_post_timestamp": (fake_now - timedelta(minutes=3)).isoformat()}
        phase_a = PhaseAContentGeneration(deps=deps)
        result = await phase_a.execute()

        mock_call_model.assert_not_called()
        assert any(p.get("error") == "pacing_blocked" for p in result.get("posts", []))


# ── Gate de quality_filters en _looks_low_quality (menciones + min score) ──

class TestLooksLowQualityPolicyGate:
    """El parametro policy de _looks_low_quality debe aplicar quality_filters."""

    POLICY = {
        "quality_filters": {
            "reject_if_mentions_moltbook": True,
            "reject_if_mentions_llm": True,
            "min_quality_score": 0.72,
        }
    }

    @staticmethod
    def _pad(text: str) -> str:
        """Rellena hasta min_length_chars sin agregar señales de scoring."""
        filler = " The team keeps refining this idea with careful attention to the craft."
        while len(text) < EDITORIAL_CONFIG["min_length_chars"]:
            text += filler
        return text

    def test_mentions_moltbook_rejected(self):
        text = self._pad(
            "Our experience posting on Moltbook shaped how we think about community norms."
        )
        low, reason = _looks_low_quality(text, self.POLICY)
        assert low is True
        assert reason == "mentions_moltbook"

    def test_mentions_llm_rejected(self):
        text = self._pad(
            "Relying on an LLM to draft replies changes the economics of moderation work."
        )
        low, reason = _looks_low_quality(text, self.POLICY)
        assert low is True
        assert reason == "mentions_llm"

    def test_pure_agreement_below_min_score_rejected(self):
        text = "Good point, exactly. You're right, solid engineering all around. " * 6
        assert len(text.strip()) >= EDITORIAL_CONFIG["min_length_chars"]
        low, reason = _looks_low_quality(text, self.POLICY)
        assert low is True
        assert reason.startswith("below_min_quality_score")

    def test_empirical_text_passes_gate(self):
        text = (
            "After migrating the ingestion service, we observed a marked drop in tail "
            "spikes once the retry queue was isolated from the hot path. In production "
            "the change held up during peak traffic, and when we deployed the same "
            "isolation to the batch workers the failure cascades stopped entirely. The "
            "lesson: separating concerns at the queue boundary matters more than tuning."
        )
        assert len(text) >= EDITORIAL_CONFIG["min_length_chars"]
        low, reason = _looks_low_quality(text, self.POLICY)
        assert low is False
        assert reason == ""
