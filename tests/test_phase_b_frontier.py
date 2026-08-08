"""Tests for Phase B frontier potential scoring."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

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
        from phases.phase_b import COMMENT_STYLE_INSTRUCTIONS
        assert "APORTAR AL MENOS" in COMMENT_STYLE_INSTRUCTIONS
        assert "failure mode" in COMMENT_STYLE_INSTRUCTIONS
        assert "FORBIDDEN OPENERS" in COMMENT_STYLE_INSTRUCTIONS
        assert "Anchor-Pivot-Evidence" in COMMENT_STYLE_INSTRUCTIONS


# ── Visibility targeting (velocity-based) ─────────────────────

class TestVisibilityBonus:
    def test_young_high_velocity_beats_old_saturated(self):
        """Post joven (10 min, 8 comments) puntua MAS que uno viejo saturado
        (8 h, 800 comments) — la penalizacion por saturacion supera la
        velocidad bruta."""
        body = (
            "How do you handle agent pipeline failures when LLM API returns "
            "429 errors with cascading retries in production?"
        )
        now = datetime.now(timezone.utc)
        young_post = {
            "created_at": (now - timedelta(minutes=10)).isoformat(),
            "comment_count": 8,
        }
        old_saturated = {
            "created_at": (now - timedelta(hours=8)).isoformat(),
            "comment_count": 800,
        }

        young_decision = PhaseB._decide_reply_from_post(body, post=young_post)
        old_decision = PhaseB._decide_reply_from_post(body, post=old_saturated)

        assert young_decision.should_reply
        assert old_decision.should_reply
        assert young_decision.score > old_decision.score, (
            f"young score {young_decision.score} should be > old saturated score {old_decision.score}"
        )

    def test_saturated_post_receives_penalty(self):
        """Post con >400 comentarios recibe penalizacion (-20), el bonus
        resultante es 0 aunque la velocidad bruta de +15."""
        body = (
            "Check agent loop failures in production: how do you handle "
            "cascading retries when the LLM API returns 429 errors?"
        )
        now = datetime.now(timezone.utc)
        saturated_post = {
            "created_at": (now - timedelta(hours=1)).isoformat(),
            "comment_count": 500,
        }
        bonus = _compute_visibility_bonus(saturated_post)
        # velocity = 500/60 ≈ 8.3 → +15, age=60 > 30 → no early-bird,
        # comment_count=500 > 400 → -20 → total = -5 → clamped to 0
        assert bonus == 0, f"bonus should be 0 due to saturation penalty, got {bonus}"

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

    def test_bonus_zero_when_no_timestamp(self):
        """Post sin fecha → bonus 0, sin crash."""
        assert _compute_visibility_bonus({"comment_count": 50}) == 0

    def test_early_bird_bonus(self):
        """Post con menos de 30 minutos recibe +5 adicional."""
        body = (
            "Agent tool calling retry patterns: how do you handle cascading "
            "failures in production pipelines?"
        )
        now = datetime.now(timezone.utc)
        early_post = {
            "created_at": (now - timedelta(minutes=5)).isoformat(),
            "comment_count": 3,
        }
        # velocity = 3/5 = 0.6 → +10, age=5 <= 30 → +5 early-bird → total 15
        bonus = _compute_visibility_bonus(early_post)
        assert bonus == 15, f"expected +15 (velocity +10 + early-bird +5), got {bonus}"

    def test_off_niche_high_velocity_still_rejected(self):
        """Off-niche con velocidad altisima SIGUE rechazado."""
        body = "buy my nft collection now!!!"
        now = datetime.now(timezone.utc)
        fast_off_niche = {
            "created_at": (now - timedelta(minutes=2)).isoformat(),
            "comment_count": 50,
            "score": 300,
        }
        decision = PhaseB._decide_reply_from_post(body, post=fast_off_niche)
        assert not decision.should_reply, (
            f"Off-niche post must not pass even with high velocity. "
            f"score={decision.score} reason={decision.reason}"
        )


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
