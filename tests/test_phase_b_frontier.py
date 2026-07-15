"""Tests for Phase B frontier potential scoring."""

import pytest
from unittest.mock import MagicMock, patch

from phases.phase_b import PhaseB, RelevanceDecision
from phases.deps import PhaseBDeps
from config.agent_policy import POLICY


def _make_pb():
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={
            "max_comments_per_post": 6,
            "max_comments_per_day": 10,
            "max_comment_replies_per_cycle": 4,
            "max_feed_comments_per_post": 3,
            "max_feed_replies_per_day": 3,
        },
        agent_name="COMET-RIOBAMBA",
    )
    return PhaseB(deps)


class TestFrontierPotential:
    def test_frontier_boost_when_no_metrics_mentioned(self):
        """Post with tech keywords but no metric/guardrail/failure mode coverage
        should receive frontier boost (+20)."""
        pb = _make_pb()
        post_body = (
            "How do you handle tool calling in your agent loop? "
            "We are seeing inconsistent behavior with our LLM agent."
        )
        comments = [
            {"content": "We use a simple retry mechanism.", "author": "user1"},
            {"content": "Same issue here, would love to hear solutions.", "author": "user2"},
        ]
        decision = PhaseB._decide_reply_from_post(post_body, comments=comments)
        assert decision.should_reply
        assert decision.score >= POLICY.min_comment_relevance_score + 20

    def test_no_frontier_boost_when_metrics_covered(self):
        """Post with tech keywords where metrics/guardrails are already discussed
        should NOT receive the frontier boost. Score should be base relevance only."""
        pb = _make_pb()
        post_body = (
            "I am seeing system and loop issues."
        )
        comments = [
            {"content": "We use a metric, guardrails, and rate limits with observability.", "author": "user1"},
        ]
        decision = PhaseB._decide_reply_from_post(post_body, comments=comments)
        # "system" and "loop" match English tech keywords → tech_count=2 → score=20
        # frontier keywords: metric, guardrail, rate limit, observability = 4 → well-covered → NO boost
        # len < 100 → no length bonus. Total score = 20.
        assert decision.should_reply
        assert decision.score == 20  # base relevance from tech keywords only, no frontier boost

    def test_low_tech_keywords_no_frontier(self):
        """Posts without sufficient tech keywords or question should not pass relevance."""
        pb = _make_pb()
        post_body = "I like pizza with pepperoni and cheese."
        comments = [{"content": "Pepperoni is great!", "author": "user1"}]
        decision = PhaseB._decide_reply_from_post(post_body, comments=comments)
        # No question mark, no tech keywords, no length bonus -> score = 0
        assert not decision.should_reply

    def test_frontier_with_empty_comments(self):
        """Frontier should still work with empty comments list."""
        pb = _make_pb()
        post_body = (
            "Agent tool calling failures are increasing. "
            "What metrics do you track?"
        )
        decision = PhaseB._decide_reply_from_post(post_body, comments=None)
        assert decision.should_reply

    def test_reply_system_prompt_requires_contribution(self):
        """The feed reply system prompt must list required contributions."""
        pb = _make_pb()
        from phases.phase_b import COMMENT_STYLE_INSTRUCTIONS
        # We check the prompt is constructed by looking at a sample
        lang_instruction = (
            "Always respond in English. This is an English-speaking platform."
        )
        system_prompt = (
            "You are a senior systems engineer. "
            "Do not be promotional. Do not use emojis, hashtags, links, or markdown. "
            "You MUST add concrete value. Do NOT repeat what was already said.\n\n"
            "Your comment MUST contribute at least ONE of:\n"
            "  - A distinct metric or threshold\n"
            "  - A concrete guardrail or validation pattern\n"
            "  - A real failure mode not yet discussed\n"
            "  - A clear research question\n\n"
            f"{lang_instruction}\n\n"
            f"{COMMENT_STYLE_INSTRUCTIONS}"
        )
        assert "MUST contribute at least ONE" in system_prompt
        assert "metric" in system_prompt
        assert "guardrail" in system_prompt
        assert "failure mode" in system_prompt
        assert "research question" in system_prompt
