import json
from pathlib import Path

import pytest

from core.agent_health import (
    generate_health_report,
    get_self_monitor_stats,
    get_topic_diversity_stats,
    get_claims_stats,
    get_dual_scoring_stats,
    compute_overall_status,
)


# ---------------------------------------------------------------------------
# Test 1: Empty / missing files
# ---------------------------------------------------------------------------

def test_missing_files(tmp_path: Path):
    report = generate_health_report(tmp_path)
    assert "timestamp" in report
    assert "self_monitor" in report
    assert "topic_diversity" in report
    assert "claims" in report
    assert "dual_scoring" in report
    assert report["self_monitor"]["insufficient_data"] is True
    assert report["topic_diversity"]["insufficient_data"] is True
    assert report["claims"]["insufficient_data"] is True
    assert report["dual_scoring"]["insufficient_data"] is True
    assert report["overall_status"] == "HEALTHY"


# ---------------------------------------------------------------------------
# Test 2: Dual scoring calculation
# ---------------------------------------------------------------------------

def test_dual_scoring_calculation(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    jsonl_path = data_dir / "dual_scores.jsonl"
    lines = []
    for _ in range(5):
        lines.append(json.dumps({"type": "metric_proposal", "research_value": 0.5, "engagement": 0.0}))
    for _ in range(5):
        lines.append(json.dumps({"type": "framework_proposal", "research_value": 1.0, "engagement": 0.0}))
    jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    stats = get_dual_scoring_stats(tmp_path)
    assert stats["insufficient_data"] is False
    assert stats["avg_research_value"] == 0.75
    assert stats["metric_proposal_ratio"] == 0.5


# ---------------------------------------------------------------------------
# Test 3: Topic diversity parsing
# ---------------------------------------------------------------------------

def test_topic_diversity_parsing(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    state = {
        "cluster_weights": {"infrastructure": 1.0, "architecture": 1.2},
            "topics": [
                {"id": "t1", "last_used": "2026-06-22T12:00:00+00:00", "use_count": 3, "cluster": "infrastructure"},
                {"id": "t2", "last_used": None, "use_count": 0, "cluster": "infrastructure"},
                {"id": "t3", "last_used": None, "use_count": 0, "cluster": "architecture"},
            ],
        "recent_choices": ["t1"],
        "rotation_window": 6,
    }
    (data_dir / "topic_matrix_state.json").write_text(json.dumps(state), encoding="utf-8")

    stats = get_topic_diversity_stats(tmp_path)
    assert stats["insufficient_data"] is False
    assert stats["cluster_balance"]["infrastructure"] == 1.0
    assert stats["active_cooldowns"] == 1
    assert stats["least_used_cluster"] == "architecture"


# ---------------------------------------------------------------------------
# Test 4: Claims stats
# ---------------------------------------------------------------------------

def test_claims_stats(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    claims = {
        "next_id": 4,
        "claims": [
            {"id": "c1", "text": "Circuit breakers isolate quota exhaustion.", "topic_cluster": "infra",
             "first_made": "2026-01-01", "last_reinforced": "2026-01-01", "reinforcement_count": 1,
             "evolution_stage": "initial"},
            {"id": "c2", "text": "Retry logic needs idempotency.", "topic_cluster": "arch",
             "first_made": "2026-01-02", "last_reinforced": "2026-01-02", "reinforcement_count": 1,
             "evolution_stage": "initial"},
            {"id": "c3", "text": "Guardrails prevent injection in multi-agent.", "topic_cluster": "safety",
             "first_made": "2026-01-03", "last_reinforced": "2026-01-05", "reinforcement_count": 3,
             "evolution_stage": "refined"},
        ],
    }
    (data_dir / "claims_tracker.json").write_text(json.dumps(claims), encoding="utf-8")

    stats = get_claims_stats(tmp_path)
    assert stats["insufficient_data"] is False
    assert stats["total"] == 3
    assert stats["evolution_stages"]["initial"] == 2
    assert stats["evolution_stages"]["refined"] == 1
    assert len(stats["top_reinforced"]) == 3
    assert stats["top_reinforced"][0][1] == 3


# ---------------------------------------------------------------------------
# Test 5: Status logic — INTERVENTION NEEDED for high metric ratio
# ---------------------------------------------------------------------------

def test_status_intervention_needed(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # Write dual_scores with metric_proposal_ratio 0.7 (> 0.6)
    lines = []
    for _ in range(7):
        lines.append(json.dumps({"type": "metric_proposal", "research_value": 0.5, "engagement": 0.0}))
    for _ in range(3):
        lines.append(json.dumps({"type": "framework_proposal", "research_value": 1.0, "engagement": 0.0}))
    (data_dir / "dual_scores.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = generate_health_report(tmp_path)
    assert report["overall_status"] == "INTERVENTION NEEDED"


# ---------------------------------------------------------------------------
# Test 6: Status logic — DEGRADING trend triggers INTERVENTION NEEDED
# ---------------------------------------------------------------------------

def test_status_degrading_trend(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    lines = []
    # Old half: no interventions
    for _ in range(5):
        lines.append(json.dumps({"intervention_required": False, "interventions": []}))
    # New half: all interventions
    for _ in range(5):
        lines.append(json.dumps({"intervention_required": True, "interventions": ["pattern_break"]}))
    (data_dir / "self_diagnosis.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = generate_health_report(tmp_path)
    assert report["self_monitor"]["trend"] == "DEGRADING"
    assert report["overall_status"] == "INTERVENTION NEEDED"


# ---------------------------------------------------------------------------
# Test 7: Status logic — ATTENTION for metric ratio > 0.4
# ---------------------------------------------------------------------------

def test_status_attention(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    lines = []
    for _ in range(5):
        lines.append(json.dumps({"type": "metric_proposal", "research_value": 0.5, "engagement": 0.0}))
    for _ in range(5):
        lines.append(json.dumps({"type": "framework_proposal", "research_value": 1.0, "engagement": 0.0}))
    (data_dir / "dual_scores.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = generate_health_report(tmp_path)
    assert report["dual_scoring"]["metric_proposal_ratio"] == 0.5
    assert report["overall_status"] == "ATTENTION"


# ---------------------------------------------------------------------------
# Test 8: compute_overall_status standalone
# ---------------------------------------------------------------------------

def test_compute_status_standalone():
    report = {
        "self_monitor": {"insufficient_data": True},
        "topic_diversity": {"insufficient_data": True},
        "claims": {"insufficient_data": True},
        "dual_scoring": {"insufficient_data": True},
    }
    assert compute_overall_status(report) == "HEALTHY"

    report["dual_scoring"] = {"insufficient_data": False, "metric_proposal_ratio": 0.7}
    assert compute_overall_status(report) == "INTERVENTION NEEDED"
