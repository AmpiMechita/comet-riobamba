import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

from config.topic_matrix import (
    Topic,
    TopicMatrix,
    DEFAULT_TOPICS,
    DEFAULT_CLUSTER_WEIGHTS,
    load_topic_matrix,
    save_topic_matrix,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_matrix():
    return TopicMatrix(
        topics=[Topic(id=t.id, label=t.label, cluster=t.cluster, angle=t.angle, keywords=list(t.keywords), cooldown_hours=t.cooldown_hours) for t in DEFAULT_TOPICS],
        cluster_weights=dict(DEFAULT_CLUSTER_WEIGHTS),
    )


@pytest.fixture
def tmp_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


# ---------------------------------------------------------------------------
# Test 1: Initialization — has all topics and clusters
# ---------------------------------------------------------------------------

def test_initialization_has_all_topics(fresh_matrix):
    assert len(fresh_matrix.topics) == 21
    clusters = set(t.cluster for t in fresh_matrix.topics)
    assert clusters == {"infrastructure", "architecture", "safety", "evaluation", "historical", "fringe"}
    assert fresh_matrix.rotation_window == 6
    assert fresh_matrix.recent_choices == []
    assert len(fresh_matrix.cluster_weights) == 6


# ---------------------------------------------------------------------------
# Test 2: Cooldown — topic unavailable after selection
# ---------------------------------------------------------------------------

def test_cooldown(fresh_matrix):
    t = fresh_matrix.select_topic()
    assert t is not None
    # Immediately after selection, the topic should be unavailable
    assert t.is_available() is False
    # Other topics should still be available
    available = [x for x in fresh_matrix.topics if x.is_available()]
    assert len(available) == len(fresh_matrix.topics) - 1


# ---------------------------------------------------------------------------
# Test 3: Diversity — 6 selections yield at least 3 different clusters
# ---------------------------------------------------------------------------

def test_diversity(fresh_matrix):
    selected_clusters = []
    for _ in range(6):
        t = fresh_matrix.select_topic()
        assert t is not None
        selected_clusters.append(t.cluster)
    # Should have at least 3 unique clusters (with 21 topics across 6 clusters)
    unique_clusters = set(selected_clusters)
    assert len(unique_clusters) >= 3, f"Only got {len(unique_clusters)} unique clusters: {selected_clusters}"
    # No duplicate topic IDs in 6 consecutive picks (rotation_window=6 prevents repeats)
    ids = fresh_matrix.recent_choices[-6:]
    assert len(set(ids)) == len(ids), f"Duplicate topic in recent choices: {ids}"


# ---------------------------------------------------------------------------
# Test 4: Force cluster — selection returns topic from correct cluster
# ---------------------------------------------------------------------------

def test_force_cluster(fresh_matrix):
    t = fresh_matrix.select_topic(force_cluster="safety")
    assert t is not None
    assert t.cluster == "safety"


# ---------------------------------------------------------------------------
# Test 5: Exhaustion — all topics on cooldown resets and returns a topic
# ---------------------------------------------------------------------------

def test_exhaustion_resets_cooldowns(fresh_matrix):
    # Mark every topic as just used (cooldown active)
    now = datetime.now(timezone.utc)
    for t in fresh_matrix.topics:
        t.last_used = now
    # All should be unavailable
    assert all(not t.is_available() for t in fresh_matrix.topics)
    # select_topic should reset all cooldowns and return a topic
    t = fresh_matrix.select_topic()
    assert t is not None
    # After reset, at least the selected topic should have a recent last_used
    # but others should be reset (last_used = None)
    reset_count = sum(1 for x in fresh_matrix.topics if x.last_used is None)
    # At least the 20 non-selected topics should have been reset
    assert reset_count >= len(fresh_matrix.topics) - 2


# ---------------------------------------------------------------------------
# Test 6: Persistence round-trip
# ---------------------------------------------------------------------------

def test_persistence(tmp_path):
    matrix = TopicMatrix(
        topics=[Topic(id=t.id, label=t.label, cluster=t.cluster, angle=t.angle, keywords=list(t.keywords), cooldown_hours=t.cooldown_hours) for t in DEFAULT_TOPICS],
        cluster_weights=dict(DEFAULT_CLUSTER_WEIGHTS),
    )
    # Make some selections to build state
    for _ in range(4):
        matrix.select_topic()
    assert len(matrix.recent_choices) == 4
    original_use_counts = {t.id: t.use_count for t in matrix.topics}

    state_file = tmp_path / "topic_matrix_state.json"
    save_topic_matrix(matrix, state_file)
    assert state_file.exists()

    loaded = load_topic_matrix(state_file)
    assert len(loaded.recent_choices) == 4
    assert loaded.rotation_window == 6
    # Verify use counts survived round-trip
    for t in loaded.topics:
        assert t.use_count == original_use_counts.get(t.id, 0), f"use_count mismatch for {t.id}"
    # Static fields (label, cluster, angle) should be intact
    arch_topic = next(t for t in loaded.topics if t.id == "arch-cascade")
    assert arch_topic.label == "Model cascade reliability and provider failover"
    assert arch_topic.cluster == "architecture"


# ---------------------------------------------------------------------------
# Test 7: Integration with self-diagnosis — force_cluster selects least-used
# ---------------------------------------------------------------------------

def test_force_cluster_from_diagnosis(fresh_matrix):
    # Simulate 4 selections on infrastructure (only 4 infra topics exist)
    for _ in range(4):
        fresh_matrix.select_topic(force_cluster="infrastructure")
    balance = fresh_matrix.get_cluster_balance()
    assert balance.get("infrastructure", 1.0) > 0.5  # majority were infra
    # The least-used cluster should not be infrastructure
    least = fresh_matrix.least_used_cluster()
    assert least is not None
    assert least != "infrastructure"

    # When diagnosis says stuck, force the least-used cluster
    diagnosis = {
        "intervention_required": True,
        "interventions": ["topic_rotation"],
        "topic_stuck": {"stuck": True, "dominant_topic": ["rate", "limit"], "concentration": 0.6},
    }

    force_cluster = None
    if diagnosis.get("topic_stuck", {}).get("stuck"):
        force_cluster = fresh_matrix.least_used_cluster()

    assert force_cluster is not None
    assert force_cluster != "infrastructure"
    selected = fresh_matrix.select_topic(force_cluster=force_cluster)
    assert selected is not None
    assert selected.cluster == force_cluster


# ---------------------------------------------------------------------------
# Test 8: Missing state file returns fresh matrix
# ---------------------------------------------------------------------------

def test_load_missing_file(tmp_path):
    missing = tmp_path / "nonexistent.json"
    matrix = load_topic_matrix(missing)
    assert len(matrix.topics) == 21
    assert matrix.recent_choices == []


# ---------------------------------------------------------------------------
# Test 9: Empty topics list in matrix returns None
# ---------------------------------------------------------------------------

def test_select_from_empty():
    matrix = TopicMatrix(topics=[], cluster_weights={})
    assert matrix.select_topic() is None


# ---------------------------------------------------------------------------
# Test 10: get_cluster_balance with no choices
# ---------------------------------------------------------------------------

def test_cluster_balance_empty(fresh_matrix):
    assert fresh_matrix.get_cluster_balance() == {}


# ---------------------------------------------------------------------------
# Test 11: least_used_cluster when no choices made
# ---------------------------------------------------------------------------

def test_least_used_no_choices(fresh_matrix):
    # When no history exists, should return the first cluster alphabetically or None
    result = fresh_matrix.least_used_cluster()
    # With no recent choices, all clusters have equal representation (0), so all are absent
    assert result is not None
    assert result in {"infrastructure", "architecture", "safety", "evaluation", "historical", "fringe"}


# ---------------------------------------------------------------------------
# Test 12: Corrupted state file falls back to fresh
# ---------------------------------------------------------------------------

def test_corrupted_state_file(tmp_path):
    state_file = tmp_path / "topic_matrix_state.json"
    state_file.write_text("not valid json", encoding="utf-8")
    matrix = load_topic_matrix(state_file)
    assert len(matrix.topics) == 21
    assert matrix.recent_choices == []
