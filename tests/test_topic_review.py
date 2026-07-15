"""Tests for Phase C topic review feedback loop."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from phases.phase_c_analytics import PhaseCAnalytics
from phases.deps import PhaseCDeps


def _make_deps(**kwargs) -> PhaseCDeps:
    deps = PhaseCDeps(
        model_cascade=kwargs.get("model_cascade", MagicMock()),
        moltbook_client=kwargs.get("moltbook_client", MagicMock()),
        write_policy=kwargs.get("write_policy", MagicMock()),
    )
    deps.behavior_cfg = kwargs.get("behavior_cfg", {})
    deps.telegram_client = kwargs.get("telegram_client", None)
    deps.get_comments_today = kwargs.get("get_comments_today", lambda: 0)
    deps.increment_comments_today = kwargs.get("increment_comments_today", lambda: 0)
    deps.max_phase_c_replies_per_day = kwargs.get("max_phase_c_replies_per_day", 10)
    deps.max_phase_c_replies_per_cycle = kwargs.get("max_phase_c_replies_per_cycle", 3)
    deps.cycle_count = kwargs.get("cycle_count", 1)
    return deps


# ---- _run_topic_review ----

@pytest.fixture(autouse=True)
def _clean_roadmap_files(tmp_path: Path) -> None:
    """Redirect roadmap paths to temp for each test."""
    import services.roadmap as rm_mod
    import services.persistence as per_mod

    orig_roadmap_path = rm_mod.DEFAULT_ROADMAP_PATH
    orig_pub_path = rm_mod.PUBLISHED_LOG_PATH

    rm_mod.DEFAULT_ROADMAP_PATH = tmp_path / "topic_roadmap.json"
    rm_mod.PUBLISHED_LOG_PATH = tmp_path / "published_posts.json"

    # Write a minimal roadmap with two series
    roadmap = {
        "series": [
            {"id": "agent_patterns", "weight": 3, "topics": [
                "ReAct patterns in Moltbook agents",
                "Planner-Executor comparison",
            ]},
            {"id": "guardrails", "weight": 2, "topics": [
                "Daily quota enforcement",
                "Duplicate detection strategies",
            ]},
        ]
    }
    rm_mod.DEFAULT_ROADMAP_PATH.write_text(
        json.dumps(roadmap, indent=2), encoding="utf-8"
    )

    yield

    rm_mod.DEFAULT_ROADMAP_PATH = orig_roadmap_path
    rm_mod.PUBLISHED_LOG_PATH = orig_pub_path


def test_topic_review_no_engagement_returns_zero() -> None:
    deps = _make_deps(behavior_cfg={"phase_c_analytics_interval": 0})
    c = PhaseCAnalytics(deps)
    # load_topic_engagement returns {} when table is empty
    with patch("phases.phase_c_analytics.load_topic_engagement", return_value={}):
        adj = c._run_topic_review()
    assert adj == 0


def test_topic_review_adjusts_weight_for_good_engagement() -> None:
    """Engagement > 1.0 should increase series weight."""
    deps = _make_deps(behavior_cfg={"phase_c_analytics_interval": 0})
    c = PhaseCAnalytics(deps)

    engagement = {
        "ReAct patterns in Moltbook agents": 2.5,
        "Planner-Executor comparison": 3.0,
    }

    with patch("phases.phase_c_analytics.load_topic_engagement", return_value=engagement):
        adj = c._run_topic_review()

    assert adj > 0, "Should adjust at least one series"

    # Reload roadmap and verify weight increased
    from services.roadmap import load_roadmap
    rm = load_roadmap()
    s = [s for s in rm.series if s.id == "agent_patterns"][0]
    assert s.weight > 3, "Weight should have increased"


def test_topic_review_decreases_weight_for_bad_engagement() -> None:
    """Engagement < 1.0 should decrease series weight."""
    deps = _make_deps(behavior_cfg={"phase_c_analytics_interval": 0})
    c = PhaseCAnalytics(deps)

    engagement = {
        "Daily quota enforcement": 0.3,
        "Duplicate detection strategies": 0.2,
    }

    with patch("phases.phase_c_analytics.load_topic_engagement", return_value=engagement):
        adj = c._run_topic_review()

    assert adj > 0

    from services.roadmap import load_roadmap
    rm = load_roadmap()
    s = [s for s in rm.series if s.id == "guardrails"][0]
    assert s.weight < 2, "Weight should have decreased"


def test_topic_review_ignores_small_deltas() -> None:
    """Engagement delta < 0.1 should not trigger adjustment."""
    deps = _make_deps(behavior_cfg={"phase_c_analytics_interval": 0})
    c = PhaseCAnalytics(deps)

    engagement = {
        "ReAct patterns in Moltbook agents": 1.1,  # delta = (1.1 - 1.0) * 0.5 = 0.05
    }

    with patch("phases.phase_c_analytics.load_topic_engagement", return_value=engagement):
        adj = c._run_topic_review()

    assert adj == 0, "Delta below threshold should not adjust"


def test_topic_review_no_crash_on_empty_roadmap() -> None:
    deps = _make_deps(behavior_cfg={"phase_c_analytics_interval": 0})
    c = PhaseCAnalytics(deps)

    # Empty the roadmap file
    from services.roadmap import DEFAULT_ROADMAP_PATH
    DEFAULT_ROADMAP_PATH.write_text(
        json.dumps({"series": []}), encoding="utf-8"
    )

    with patch("phases.phase_c_analytics.load_topic_engagement", return_value={"some topic": 3.0}):
        adj = c._run_topic_review()
    assert adj == 0
