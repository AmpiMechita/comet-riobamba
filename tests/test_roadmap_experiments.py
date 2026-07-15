"""Tests for topic roadmap and experiment framework."""

from pathlib import Path
from typing import Dict, Any
import json
import pytest
import tempfile
import shutil

from services.roadmap import (
    Roadmap, Series, load_roadmap, save_roadmap,
    choose_topic_from_roadmap, update_series_weight,
)
from services.experiments import load_experiments, pick_variant


# ---- Fixtures ----

@pytest.fixture
def sample_roadmap() -> Roadmap:
    return Roadmap(series=[
        Series(id="arch", weight=3, topics=[
            "ReAct patterns in production",
            "Planner-Executor comparison",
        ]),
        Series(id="guardrails", weight=2, topics=[
            "Daily quotas for agents",
            "Duplicate detection strategies",
        ]),
    ])


@pytest.fixture
def sample_experiments() -> Dict[str, Any]:
    return {
        "phase_a_prompt_variant": {
            "enabled": True,
            "variants": [
                {"id": "baseline", "weight": 3},
                {"id": "more_concise", "weight": 2},
            ],
        },
    }


# ---- Roadmap: load / save ----

def test_load_roadmap_missing_file(tmp_path: Path) -> None:
    """Should return default roadmap when file doesn't exist."""
    rm = load_roadmap(tmp_path / "nonexistent.json")
    assert len(rm.series) >= 1
    assert any("quota" in t for s in rm.series for t in s.topics)


def test_load_roadmap_invalid_json(tmp_path: Path) -> None:
    """Should return default roadmap when JSON is corrupt."""
    f = tmp_path / "bad.json"
    f.write_text("{{invalid", encoding="utf-8")
    rm = load_roadmap(f)
    assert len(rm.series) >= 1


def test_save_and_reload_roadmap(tmp_path: Path, sample_roadmap: Roadmap) -> None:
    p = tmp_path / "roadmap.json"
    save_roadmap(sample_roadmap, p)
    assert p.exists()
    reloaded = load_roadmap(p)
    assert len(reloaded.series) == 2
    assert reloaded.series[0].id == "arch"
    assert reloaded.series[0].weight == 3


# ---- Roadmap: choose_topic_from_roadmap ----

def test_choose_topic_returns_valid_topic(sample_roadmap: Roadmap) -> None:
    topic = choose_topic_from_roadmap(sample_roadmap, recent_window=0)
    assert topic is not None
    assert isinstance(topic, str)
    assert len(topic) > 10


def test_choose_topic_all_topics_eventually_covered(sample_roadmap: Roadmap) -> None:
    all_topics = sample_roadmap.all_topics()
    seen: set = set()
    for _ in range(200):
        t = choose_topic_from_roadmap(sample_roadmap, recent_window=0)
        if t:
            seen.add(t)
    # With 200 draws, even low-weight series topics should appear
    for t in all_topics:
        assert t in seen, f"Topic '{t}' never chosen in 200 draws"


def test_choose_topic_anti_repetition(tmp_path: Path) -> None:
    """Should avoid recently published topics when possible."""
    # Create a roadmap where there's only 1 series with 3 topics
    rm = Roadmap(series=[
        Series(id="test", weight=5, topics=[
            "Topic A about agents",
            "Topic B about agents",
            "Topic C about agents",
        ]),
    ])
    # Simulate published history with Topic A and Topic B
    pub_path = Path("data/published_posts.json")
    pub_path.parent.mkdir(parents=True, exist_ok=True)
    pub_path.write_text(json.dumps([
        {"topic": "Topic A about agents"},
        {"topic": "Topic B about agents"},
    ]), encoding="utf-8")
    try:
        # Should pick Topic C (the only one not in recent history)
        t = choose_topic_from_roadmap(rm, recent_window=5)
        assert t == "Topic C about agents"
    finally:
        if pub_path.exists():
            pub_path.unlink()


def test_choose_topic_all_recent_falls_back(sample_roadmap: Roadmap) -> None:
    # If all topics are recent, it should still return something
    pub_path = Path("data/published_posts.json")
    pub_path.parent.mkdir(parents=True, exist_ok=True)
    all_topics = sample_roadmap.all_topics()
    pub_path.write_text(json.dumps([
        {"topic": t} for t in all_topics
    ]), encoding="utf-8")
    try:
        t = choose_topic_from_roadmap(sample_roadmap, recent_window=10)
        assert t is not None
        assert t in all_topics
    finally:
        if pub_path.exists():
            pub_path.unlink()


# ---- Roadmap: update_series_weight ----

def test_update_series_weight_positive(sample_roadmap: Roadmap) -> None:
    update_series_weight(sample_roadmap, "arch", 1)
    s = [s for s in sample_roadmap.series if s.id == "arch"][0]
    assert s.weight == 4  # 3 + 1


def test_update_series_weight_clamps_min(sample_roadmap: Roadmap) -> None:
    update_series_weight(sample_roadmap, "arch", -10)
    s = [s for s in sample_roadmap.series if s.id == "arch"][0]
    assert s.weight >= 1


def test_update_series_weight_clamps_max(sample_roadmap: Roadmap) -> None:
    update_series_weight(sample_roadmap, "arch", 20)
    s = [s for s in sample_roadmap.series if s.id == "arch"][0]
    assert s.weight <= 10


def test_update_series_weight_unknown_series(sample_roadmap: Roadmap) -> None:
    """Should not crash for unknown series_id."""
    update_series_weight(sample_roadmap, "nonexistent", 5)
    # Weights unchanged
    assert sample_roadmap.series[0].weight == 3
    assert sample_roadmap.series[1].weight == 2


# ---- Roadmap: topic_to_series ----

def test_topic_to_series(sample_roadmap: Roadmap) -> None:
    sid = sample_roadmap.topic_to_series("ReAct patterns in production")
    assert sid == "arch"


def test_topic_to_series_unknown(sample_roadmap: Roadmap) -> None:
    sid = sample_roadmap.topic_to_series("Nonexistent topic")
    assert sid is None


# ---- Experiments: load / pick ----

def test_load_experiments_missing(tmp_path: Path) -> None:
    cfg = load_experiments(tmp_path / "missing.json")
    assert cfg == {}


def test_load_experiments_invalid_json(tmp_path: Path) -> None:
    f = tmp_path / "bad.json"
    f.write_text("{{{", encoding="utf-8")
    cfg = load_experiments(f)
    assert cfg == {}


def test_pick_variant_returns_valid_id(sample_experiments: Dict[str, Any]) -> None:
    vid = pick_variant("phase_a_prompt_variant", sample_experiments)
    assert vid in ("baseline", "more_concise")


def test_pick_variant_disabled_returns_none(sample_experiments: Dict[str, Any]) -> None:
    cfg = dict(sample_experiments)
    cfg["phase_a_prompt_variant"]["enabled"] = False
    vid = pick_variant("phase_a_prompt_variant", cfg)
    assert vid is None


def test_pick_variant_unknown_key(sample_experiments: Dict[str, Any]) -> None:
    vid = pick_variant("nonexistent", sample_experiments)
    assert vid is None


def test_pick_variant_empty_variants() -> None:
    cfg = {"test_exp": {"enabled": True, "variants": []}}
    vid = pick_variant("test_exp", cfg)
    assert vid is None


def test_pick_variant_weight_distribution() -> None:
    """Baseline (weight 3) should appear ~3x more_concise (weight 1)."""
    cfg = {
        "exp": {
            "enabled": True,
            "variants": [
                {"id": "heavy", "weight": 99},
                {"id": "light", "weight": 1},
            ],
        },
    }
    results: Dict[str, int] = {"heavy": 0, "light": 0}
    for _ in range(1000):
        v = pick_variant("exp", cfg)
        if v:
            results[v] += 1
    assert results["heavy"] > results["light"] * 5  # 99:1 ratio
