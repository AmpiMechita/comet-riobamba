"""Tests for Phase A research mode."""

import os
import pytest
from unittest.mock import patch, MagicMock

from phases.phase_a_content import (
    build_prompts, choose_topic, EDITORIAL_CONFIG,
    RESEARCH_CLOSING_TEMPLATES, _topic_with_matrix_fallback,
    compute_topic_weights,
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
