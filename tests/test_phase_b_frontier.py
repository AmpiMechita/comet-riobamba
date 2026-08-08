"""Tests for Phase B frontier potential scoring."""

import pytest
from unittest.mock import MagicMock, patch

from phases.phase_b import PhaseB, RelevanceDecision
from phases.deps import PhaseBDeps
from config.agent_policy import POLICY
from phases.phase_b.scoring import _triage_comment_value, _compute_visibility_bonus, _compute_relationship_bonus


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


# ── Visibility targeting ──────────────────────────────────────

class TestVisibilityBonus:
    def test_hot_post_scores_higher_than_dead_post(self):
        """Hot on-niche post (many comments/upvotes) scores MORE than dead
        on-niche post; both pass on-niche threshold."""
        body = (
            "How do you handle agent pipeline failures when LLM API returns "
            "429 errors with cascading retries in production?"
        )
        hot_post = {
            "score": 30,
            "comment_count": 50,
        }
        dead_post = {"upvotes": 0, "comment_count": 0}

        hot_decision = PhaseB._decide_reply_from_post(body, post=hot_post)
        dead_decision = PhaseB._decide_reply_from_post(body, post=dead_post)

        assert hot_decision.should_reply
        assert dead_decision.should_reply
        assert hot_decision.score > dead_decision.score, (
            f"hot score {hot_decision.score} should be > dead score {dead_decision.score}"
        )

    def test_off_niche_post_with_massive_visibility_still_rejected(self):
        """Off-niche post with 3000 comments and 500 upvotes is STILL rejected
        (visibility bonus never rescues non-relevant posts)."""
        body = "Check out my new product at this link!"
        viral_post = {
            "score": 500,
            "comment_count": 3000,
        }
        decision = PhaseB._decide_reply_from_post(body, post=viral_post)
        assert not decision.should_reply, (
            f"Off-niche post must not pass even with massive visibility. "
            f"score={decision.score} reason={decision.reason}"
        )

    def test_bonus_zero_when_no_visibility_data(self):
        """Post dict with no upvotes/comment keys → bonus 0."""
        assert _compute_visibility_bonus({"other": "data"}) == 0
        assert _compute_visibility_bonus(None) == 0
        assert _compute_visibility_bonus({"score": 2, "comments": [{}]}) == 0


# ── Comment triage ───────────────────────────────────────────

class TestCommentTriage:
    def test_short_comment_without_question_skipped(self):
        skip, reason = _triage_comment_value(
            "nice post", tech_keywords=frozenset({"agent"})
        )
        assert skip
        assert reason == "low_value_triage"

    def test_comment_with_question_passes(self):
        skip, reason = _triage_comment_value(
            "How do you handle pipeline failures under heavy production load "
            "with a circuit breaker pattern and fallback orchestration?",
            tech_keywords=frozenset({"agent", "circuit breaker", "pipeline"}),
        )
        assert not skip

    def test_off_niche_with_question_still_passes(self):
        """Even if off-niche, a question is a valid engagement signal and
        should NOT be triage-blocked — the scoring layer decides."""
        skip, reason = _triage_comment_value(
            "What is your favorite pizza topping? I am really curious about "
            "this because I want to order something different from my usual "
            "pepperoni choice tonight with my friends.",
            tech_keywords=frozenset({"agent"}),
        )
        assert not skip, "Question signal should prevent triage"

    def test_long_comment_without_question_or_critique_passes(self):
        """Length alone is a signal of engagement effort — triage lets it
        through to be scored by _decide_reply."""
        skip, reason = _triage_comment_value(
            "I have been reading your posts for a while and I think they are "
            "very interesting. Keep up the great work and thanks for sharing.",
            tech_keywords=frozenset({"agent"}),
        )
        assert not skip, "Length above 80 chars should prevent triage"


# ── Interlocutor relationship priority ───────────────────────

class TestRelationshipBonus:
    def test_bonus_tiers(self):
        bonus = _compute_relationship_bonus
        assert bonus(None) == 0
        assert bonus("unknown_user") == 0

    def test_bonus_from_ledger(self, monkeypatch, tmp_path):
        """Integration: record interactions then verify bonus via actual count."""
        from services import interlocutors
        path = tmp_path / "interlocutors.json"
        monkeypatch.setattr("services.interlocutors._INTERLOCUTORS_PATH", path)
        # also patch scoring's import which reads at call time
        monkeypatch.setattr("phases.phase_b.scoring", None, raising=False)

        author = {"name": "test_user_42"}
        for _ in range(3):
            interlocutors.record_interaction(author, on_our_post=True)
        assert _compute_relationship_bonus("test_user_42") == 5

        for _ in range(7):
            interlocutors.record_interaction(author, on_our_post=True)
        assert _compute_relationship_bonus("test_user_42") == 10


class TestRelationshipTriage:
    def test_recurrent_short_on_niche_not_skipped(self, monkeypatch, tmp_path):
        """count>=3 + short on-niche comment → triage does NOT skip.
        (Length bypass applies only for known interlocutors.)"""
        from services import interlocutors
        path = tmp_path / "interlocutors.json"
        monkeypatch.setattr("services.interlocutors._INTERLOCUTORS_PATH", path)

        author = "bob_the_builder"
        for _ in range(3):
            interlocutors.record_interaction(author, on_our_post=True)

        skip, reason = _triage_comment_value(
            "Short on-niche debug question about agent loops?",
            tech_keywords=frozenset({"agent", "debug", "loop"}),
            author=author,
        )
        assert not skip, f"Expected pass but got skip reason={reason}"

    def test_recurrent_off_niche_still_skipped(self, monkeypatch, tmp_path):
        """count>=3 but off-niche: triage STILL skips (relationship
        does not buy a pass for irrelevant content)."""
        from services import interlocutors
        path = tmp_path / "interlocutors.json"
        monkeypatch.setattr("services.interlocutors._INTERLOCUTORS_PATH", path)

        author = "alice"
        for _ in range(3):
            interlocutors.record_interaction(author, on_our_post=True)

        skip, reason = _triage_comment_value(
            "nice bro",
            tech_keywords=frozenset({"agent"}),
            author=author,
        )
        assert skip
        assert reason == "low_value_triage"
