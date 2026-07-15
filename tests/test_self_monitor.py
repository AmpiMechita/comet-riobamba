import json
import math
import tempfile
from pathlib import Path

import pytest

from core.self_monitor import SelfMonitor
from prompts.prompt_templates import inject_self_diagnosis


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _with_published_posts(tmp: Path, topics: list):
    data_dir = tmp / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    posts = [{"post_id": f"id-{i}", "topic": t, "published_at": "2026-06-22T00:00:00"} for i, t in enumerate(topics)]
    (data_dir / "published_posts.json").write_text(json.dumps(posts), encoding="utf-8")


def _with_trace(tmp: Path, contents: list):
    traces_dir = tmp / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for c in contents:
        lines.append(json.dumps({"span": "llm_generation", "content": c, "timestamp": "2026-06-22T00:00:00"}))
    (traces_dir / "phase_b_20260622.jsonl").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1: Healthy state — no data files at all
# ---------------------------------------------------------------------------

def test_healthy_state(empty_dir):
    monitor = SelfMonitor(empty_dir)
    result = monitor.run_diagnosis()

    assert result["intervention_required"] is False
    assert result["topic_stuck"]["stuck"] is False
    assert result["pattern_rigidity"]["rigid"] is False
    assert result["metric_recycling"]["recycling"] is False
    assert result["interventions"] == []
    assert "timestamp" in result


# ---------------------------------------------------------------------------
# Test 2: Topic stuck — 15 posts all about rate limiting / circuit breakers
# ---------------------------------------------------------------------------

def test_topic_stuck(empty_dir):
    # 15 posts heavily overlapping — each differs by only one word
    topics = [
        "rate limit circuit breaker agent system",
        "rate limit circuit breaker agent loop",
        "rate limit circuit breaker agent runtime",
        "rate limit circuit breaker agent architecture",
        "rate limit circuit breaker agent production",
        "rate limit circuit breaker agent deployment",
        "rate limit circuit breaker agent monitoring",
        "rate limit circuit breaker agent scaling",
        "rate limit circuit breaker agent failover",
        "rate limit circuit breaker agent routing",
        "rate limit circuit breaker agent timeout",
        "rate limit circuit breaker agent recovery",
        "rate limit circuit breaker agent testing",
        "rate limit circuit breaker agent observability",
        "rate limit circuit breaker agent security",
    ] + ["unrelated topic"]  # 16th = unrelated

    _with_published_posts(empty_dir, topics)
    monitor = SelfMonitor(empty_dir)
    result = monitor.run_diagnosis()

    ts = result["topic_stuck"]
    assert ts["stuck"] is True, f"Expected stuck=True, got concentration={ts['concentration']}"
    assert ts["concentration"] > 0.45, f"concentration={ts['concentration']} should be > 0.45"
    # dominant_topic should contain some circuit-breaker-related words
    dominant_str = " ".join(ts["dominant_topic"]).lower()
    assert "rate" in dominant_str or "circuit" in dominant_str or "breaker" in dominant_str


# ---------------------------------------------------------------------------
# Test 3: Pattern rigidity — 10 replies all starting with "A useful metric"
# ---------------------------------------------------------------------------

def test_pattern_rigidity(empty_dir):
    contents = [
        "A useful metric is the number of tool calls per second before timeout.",
        "A useful metric for rate limiting is the error rate.",
        "A useful metric to track is p99 latency.",
        "A useful metric in production systems is failure rate.",
        "A useful metric for circuit breakers is recovery time.",
        "A useful metric to monitor is throughput degradation.",
        "A useful metric in agent loops is idle timeout.",
        "A useful metric for observability is span latency.",
        "A useful metric is the ratio of successful to failed calls.",
        "A useful metric for autonomous agents is tool success rate.",
    ]
    _with_trace(empty_dir, contents)
    # Also create empty published_posts to keep topic stuck from masking
    _with_published_posts(empty_dir, ["rate limit", "circuit breaker"])

    monitor = SelfMonitor(empty_dir)
    result = monitor.run_diagnosis()

    pr = result["pattern_rigidity"]
    assert pr["rigid"] is True, f"Expected rigid=True, got entropy={pr['entropy']}"
    assert pr["entropy"] < 0.5, f"entropy={pr['entropy']} should be < 0.5"


# ---------------------------------------------------------------------------
# Test 4: Prompt injection — injects when intervention required, no-op otherwise
# ---------------------------------------------------------------------------

def test_prompt_injection_adds_block():
    diagnosis = {
        "intervention_required": True,
        "interventions": ["topic_rotation", "pattern_break", "metric_freshness"],
        "topic_stuck": {"dominant_topic": ["rate", "limit", "circuit"], "stuck": True, "concentration": 0.62},
        "pattern_rigidity": {"rigid": True, "entropy": 0.3, "dominant_openers": ["a useful metric"]},
        "metric_recycling": {"recycling": True, "repeated_metrics": ["percentage", "p95"]},
    }
    base = "Write a post about agent architecture."
    result = inject_self_diagnosis(base, diagnosis)

    assert "SELF-DIAGNOSIS INTERVENTION" in result
    assert "TOPIC ROTATION MANDATORY" in result
    assert "STRUCTURE BREAK MANDATORY" in result
    assert "METRIC FRESHNESS MANDATORY" in result
    assert "rate" in result
    assert "percentage" in result
    assert "p95" in result


def test_prompt_injection_returns_as_is_when_healthy():
    diagnosis = {
        "intervention_required": False,
        "interventions": [],
        "topic_stuck": {"stuck": False, "dominant_topic": [], "concentration": 0.0},
        "pattern_rigidity": {"rigid": False, "entropy": 0.9, "dominant_openers": []},
        "metric_recycling": {"recycling": False, "repeated_metrics": []},
    }
    base = "Write a post about agent architecture."
    result = inject_self_diagnosis(base, diagnosis)
    assert result == base
    assert "SELF-DIAGNOSIS INTERVENTION" not in result


def test_prompt_injection_partial_interventions():
    diagnosis = {
        "intervention_required": True,
        "interventions": ["topic_rotation"],
        "topic_stuck": {"dominant_topic": ["circuit", "breaker"], "stuck": True, "concentration": 0.55},
        "pattern_rigidity": {"rigid": False, "entropy": 0.8, "dominant_openers": []},
        "metric_recycling": {"recycling": False, "repeated_metrics": []},
    }
    base = "Write a post."
    result = inject_self_diagnosis(base, diagnosis)

    assert "SELF-DIAGNOSIS INTERVENTION" in result
    assert "TOPIC ROTATION MANDATORY" in result
    assert "STRUCTURE BREAK MANDATORY" not in result
    assert "METRIC FRESHNESS MANDATORY" not in result


# ---------------------------------------------------------------------------
# Test 5: Empty published_posts.json (empty list)
# ---------------------------------------------------------------------------

def test_empty_published_posts(empty_dir):
    data_dir = empty_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "published_posts.json").write_text("[]", encoding="utf-8")

    monitor = SelfMonitor(empty_dir)
    result = monitor.run_diagnosis()
    assert result["topic_stuck"]["stuck"] is False
    assert result["intervention_required"] is False


# ---------------------------------------------------------------------------
# Test 6: Published posts file with just 1 entry (not enough for comparison)
# ---------------------------------------------------------------------------

def test_single_post_not_stuck(empty_dir):
    _with_published_posts(empty_dir, ["rate limit circuit breaker"])
    monitor = SelfMonitor(empty_dir)
    result = monitor.run_diagnosis()
    assert result["topic_stuck"]["stuck"] is False


# ---------------------------------------------------------------------------
# Test 7: Diverse topics should produce low similarity (not stuck)
# ---------------------------------------------------------------------------

def test_diverse_topics_not_stuck(empty_dir):
    topics = [
        "agent memory persistence strategies",
        "model cascade failover reliability",
        "tool calling failure taxonomy",
        "self evaluation metrics for output quality",
        "observability gaps in agent loops",
        "guardrails for autonomous posting",
        "multi tenant rate limiting patterns",
        "prompt injection defense vectors",
        "context window compression techniques",
        "circuit breaker versus retry semantics",
        "agent loop termination guarantees",
        "config drift detection in production",
        "provider endpoint health monitoring",
        "semantic caching for llm responses",
        "session persistence across submolts",
    ]
    _with_published_posts(empty_dir, topics)
    monitor = SelfMonitor(empty_dir)
    result = monitor.run_diagnosis()
    # With diverse topics Jaccard should be low
    assert result["topic_stuck"]["stuck"] is False, f"Got concentration={result['topic_stuck']['concentration']}"
