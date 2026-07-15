import tempfile
from pathlib import Path

import pytest

from core.claims_tracker import ClaimsTracker, Claim


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


# ---------------------------------------------------------------------------
# Test 1: Valid extraction — two technical sentences > 40 chars
# ---------------------------------------------------------------------------

def test_extract_valid_claims(tmp_dir):
    tracker = ClaimsTracker(tmp_dir)
    text = (
        "Circuit breaker patterns must isolate quota exhaustion from network failures. "
        "Agent loops require careful timeout management to avoid runaway costs. "
        "Short."
    )
    claims = tracker.extract_claims(text, "infrastructure")
    # Should extract at least the two long technical sentences
    assert len(claims) >= 2
    # Both should contain key terms from the original
    assert any("circuit" in c for c in claims)
    assert any("agent" in c for c in claims)
    # Normalization: should not start with "the " or "a "
    for c in claims:
        assert not c.startswith(("the ", "a ", "an ", "we ", "this ")), f"Claim not normalized: {c}"


# ---------------------------------------------------------------------------
# Test 2: Short sentence filter — sentence < 40 chars
# ---------------------------------------------------------------------------

def test_short_sentence_filter(tmp_dir):
    tracker = ClaimsTracker(tmp_dir)
    text = "Agent loops fail."  # 16 chars
    claims = tracker.extract_claims(text, "architecture")
    assert len(claims) == 0


# ---------------------------------------------------------------------------
# Test 3: No tech indicator — sentence lacks any tech keyword
# ---------------------------------------------------------------------------

def test_no_tech_indicator(tmp_dir):
    tracker = ClaimsTracker(tmp_dir)
    text = "The weather is nice today and the sun is shining brightly over the horizon."
    claims = tracker.extract_claims(text, "fringe")
    assert len(claims) == 0


# ---------------------------------------------------------------------------
# Test 4: Register new claim in empty tracker
# ---------------------------------------------------------------------------

def test_register_new_claim(tmp_dir):
    tracker = ClaimsTracker(tmp_dir)
    stats = tracker.register_claims(
        "Circuit breaker patterns must isolate quota exhaustion from network failures.",
        "infrastructure",
    )
    assert stats["new"] == 1
    assert stats["reinforced"] == 0
    assert stats["similar_found"] == []
    assert len(tracker._claims) == 1


# ---------------------------------------------------------------------------
# Test 5: Similar claim detection — reinforcement via Jaccard >= 0.6
# ---------------------------------------------------------------------------

def test_similar_claim_reinforcement(tmp_dir):
    tracker = ClaimsTracker(tmp_dir)
    # Register first claim
    tracker.register_claims(
        "Circuit breakers isolate quota exhaustion from network failures in production systems.",
        "infrastructure",
    )
    assert len(tracker._claims) == 1
    assert tracker._claims[0].reinforcement_count == 1

    # Register a semantically similar claim (high overlap -> Jaccard >= 0.6)
    stats = tracker.register_claims(
        "Circuit breakers isolate quota exhaustion from network failures in production.",
        "infrastructure",
    )
    assert stats["new"] == 0, f"Expected new=0, got {stats['new']}"
    assert stats["reinforced"] == 1, f"Expected reinforced=1, got {stats['reinforced']}"
    assert len(stats["similar_found"]) == 1
    # The existing claim should have been reinforced
    assert tracker._claims[0].reinforcement_count == 2
    assert tracker._claims[0].evolution_stage == "refined"


# ---------------------------------------------------------------------------
# Test 6: Context for reply — returns claims for matching cluster
# ---------------------------------------------------------------------------

def test_context_for_reply_matching_cluster(tmp_dir):
    tracker = ClaimsTracker(tmp_dir)
    tracker.register_claims(
        "Guardrails must prevent prompt injection in multi-agent runtimes.",
        "safety",
    )
    tracker.register_claims(
        "Sandboxing provides isolation between untrusted agent tool calls.",
        "safety",
    )
    tracker.register_claims(
        "Alignment locking prevents value drift in self-modifying agents.",
        "safety",
    )

    context = tracker.get_context_for_reply("safety")
    assert context != ""
    assert "YOUR PREVIOUS CLAIMS ON THIS TOPIC" in context
    assert "guardrails" in context.lower() or "Guardrails" in context
    assert "sandboxing" in context.lower() or "Sandboxing" in context
    assert "alignment" in context.lower() or "Alignment" in context

    # Non-matching cluster returns empty
    fringe_context = tracker.get_context_for_reply("fringe")
    assert fringe_context == ""


# ---------------------------------------------------------------------------
# Test 7: Persistence — claims survive tracker re-instantiation
# ---------------------------------------------------------------------------

def test_persistence(tmp_dir):
    tracker1 = ClaimsTracker(tmp_dir)
    tracker1.register_claims(
        "Tool-calling retry strategies must account for idempotency guarantees.",
        "architecture",
    )
    tracker1.register_claims(
        "Model cascade fallback improves reliability in multi-provider setups.",
        "architecture",
    )
    assert len(tracker1._claims) == 2

    # Re-instantiate with same directory
    tracker2 = ClaimsTracker(tmp_dir)
    assert len(tracker2._claims) == 2
    texts = [c.text for c in tracker2._claims]
    assert any("retry" in t for t in texts)
    assert any("fallback" in t for t in texts)
    context = tracker2.get_context_for_reply("architecture")
    assert "tool-calling" in context.lower() or "retry" in context.lower()


# ---------------------------------------------------------------------------
# Test 8: Empty tracker returns empty context
# ---------------------------------------------------------------------------

def test_empty_tracker_context(tmp_dir):
    tracker = ClaimsTracker(tmp_dir)
    assert tracker.get_context_for_reply("architecture") == ""


# ---------------------------------------------------------------------------
# Test 9: get_reply_depth_directive returns a valid mode string
# ---------------------------------------------------------------------------

def test_reply_depth_directive():
    from prompts.prompt_templates import get_reply_depth_directive, REPLY_DEPTH_DIRECTIVES
    directive = get_reply_depth_directive()
    assert isinstance(directive, str)
    assert len(directive) > 50
    assert "DEPTH MODE:" in directive
    # All modes should be represented over many calls
    modes_seen = set()
    for _ in range(40):
        d = get_reply_depth_directive()
        for key in REPLY_DEPTH_DIRECTIVES:
            if REPLY_DEPTH_DIRECTIVES[key] == d:
                modes_seen.add(key)
    assert modes_seen == set(REPLY_DEPTH_DIRECTIVES.keys()), f"Not all modes seen: {modes_seen}"
