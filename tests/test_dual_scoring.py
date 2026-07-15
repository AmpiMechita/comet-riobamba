import json
from pathlib import Path

import pytest

from services.dual_scoring import (
    classify_content,
    compute_dual_score,
    log_dual_score,
    ResearchValueType,
)


# ---------------------------------------------------------------------------
# Test 1: Clasificación FRAMEWORK_PROPOSAL
# ---------------------------------------------------------------------------

def test_classify_framework_proposal():
    text = "I propose a new framework for agent architecture design patterns."
    result = classify_content(text)
    assert result == ResearchValueType.FRAMEWORK_PROPOSAL


# ---------------------------------------------------------------------------
# Test 2: Clasificación METRIC_PROPOSAL
# ---------------------------------------------------------------------------

def test_classify_metric_proposal():
    text = "A useful signal is to track the 95th percentile for latency."
    result = classify_content(text)
    assert result == ResearchValueType.METRIC_PROPOSAL


# ---------------------------------------------------------------------------
# Test 3: Clasificación AGREEMENT (texto corto)
# ---------------------------------------------------------------------------

def test_classify_agreement():
    text = "Good point, exactly my thinking, solid engineering work."
    result = classify_content(text)
    assert result == ResearchValueType.AGREEMENT


# ---------------------------------------------------------------------------
# Test 4: Clasificación EMPIRICAL_FINDING
# ---------------------------------------------------------------------------

def test_classify_empirical_finding():
    text = "In production we observed that the system behavior changed after deployment."
    result = classify_content(text)
    assert result == ResearchValueType.EMPIRICAL_FINDING


# ---------------------------------------------------------------------------
# Test 5: Composite score exacto para FRAMEWORK_PROPOSAL sin engagement
# ---------------------------------------------------------------------------

def test_composite_score_framework_zero_engagement():
    result = compute_dual_score(
        "I propose a new framework for agent architecture design patterns.",
        reply_count=0,
        upvote_count=0,
    )
    assert result["content_type"] == "framework_proposal"
    assert result["research_value_score"] == 1.0
    assert result["engagement_score"] == 0.0
    assert result["composite_score"] == 0.7


# ---------------------------------------------------------------------------
# Test 6: Penalización de métrica — METRIC_PROPOSAL con alto engagement
#           es peor que FRAMEWORK_PROPOSAL sin engagement
# ---------------------------------------------------------------------------

def test_metric_penalized_below_framework():
    metric_result = compute_dual_score(
        "A useful metric is to track the 95th percentile for response time.",
        reply_count=10,
        upvote_count=5,
    )
    framework_result = compute_dual_score(
        "I propose a new framework for agent architecture design patterns.",
        reply_count=0,
        upvote_count=0,
    )
    assert metric_result["composite_score"] < framework_result["composite_score"]


# ---------------------------------------------------------------------------
# Test 7: Default CLARIFICATION para texto genérico
# ---------------------------------------------------------------------------

def test_classify_default_clarification():
    text = "This is a general discussion about some engineering topics."
    result = classify_content(text)
    assert result == ResearchValueType.CLARIFICATION


# ---------------------------------------------------------------------------
# Test 8: log_dual_score escribe JSONL correctamente
# ---------------------------------------------------------------------------

def test_log_dual_score_writes_jsonl(tmp_path: Path):
    log_path = tmp_path / "dual_scores.jsonl"
    from services.dual_scoring import DUAL_SCORE_LOG as _orig
    import services.dual_scoring as ds
    original = ds.DUAL_SCORE_LOG
    ds.DUAL_SCORE_LOG = log_path
    try:
        log_dual_score(
            "I propose a new framework for agent architecture.",
            phase="a",
        )
        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["phase"] == "a"
        assert record["type"] == "framework_proposal"
        assert record["composite"] == 0.7
        assert record["text_preview"] == "I propose a new framework for agent architecture."
    finally:
        ds.DUAL_SCORE_LOG = original
