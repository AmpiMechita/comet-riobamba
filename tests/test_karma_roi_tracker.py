# -*- coding: utf-8 -*-
"""Tests unitarios para karma_roi_tracker.

Tras ADR-004 (P-083) el tracker usa solo SQLite; el espejo JSONL
fue retirado. Los tests verifican contra la BD real, con limpieza
por fixture.
"""

import sqlite3
from pathlib import Path

import pytest

import services.karma_roi_tracker as krt
from services.karma_roi_tracker import (
    track_action,
    update_karma,
    get_roi_summary,
)


@pytest.fixture(autouse=True)
def cleanup_after_test():
    """Limpia la BD antes y despues de cada test."""

    def _clean():
        p = krt.DB_PATH if isinstance(krt.DB_PATH, Path) else Path(krt.DB_PATH)
        if not p.exists():
            return
        conn = sqlite3.connect(str(p))
        conn.execute("DELETE FROM comment_actions")
        conn.execute("DELETE FROM engagement_events")
        conn.execute("DELETE FROM daily_snapshots")
        conn.commit()
        conn.close()

    _clean()
    yield
    _clean()


def test_track_action_basic():
    """track_action debe guardar una entrada en la BD."""
    track_action(
        action_type="post",
        moltbook_id="test_post_001",
        phase="A",
        cost_usd=0.001234,
        input_tokens=150,
        output_tokens=50,
        model="deepseek-v4-pro",
    )

    conn = sqlite3.connect(str(krt.DB_PATH))
    row = conn.execute(
        "SELECT cost_usd, model, status "
        "FROM comment_actions WHERE comment_id = 'test_post_001'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 0.001234
    assert row[1] == "deepseek-v4-pro"
    assert row[2] == "published"


def test_update_karma():
    """update_karma debe actualizar score y last_updated en SQLite."""
    track_action(
        action_type="post",
        moltbook_id="karma_test",
        phase="A",
        cost_usd=0.001,
        input_tokens=50,
        output_tokens=25,
        model="deepseek-v4-flash",
    )

    update_karma("karma_test", upvotes=10, comments=2)

    conn = sqlite3.connect(str(krt.DB_PATH))
    row = conn.execute(
        "SELECT score, last_updated "
        "FROM comment_actions WHERE comment_id = 'karma_test'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 10
    assert row[1] is not None


def test_get_roi_summary_basic():
    """get_roi_summary debe devolver estructura correcta."""
    summary = get_roi_summary(hours=24)
    assert "period_hours" in summary
    assert "phase_a" in summary
    assert "phase_b" in summary
    assert "roi_ratio_a_vs_b" in summary
    assert "recommendation" in summary


def test_sin_datos_previos():
    """Dashboard debe manejar gracefully cuando no hay datos."""
    summary = get_roi_summary(hours=24)
    assert summary["period_hours"] == 24
    assert summary["phase_a"]["count"] == 0
    assert summary["phase_b"]["count"] == 0
    assert summary["roi_ratio_a_vs_b"] == 0
