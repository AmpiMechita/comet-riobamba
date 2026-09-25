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
def isolated_db(tmp_path, monkeypatch):
    """P-092: aislar la BD real; cada test usa un archivo temporal."""
    db = tmp_path / "karma_roi_test.db"
    monkeypatch.setattr(krt, "DB_PATH", db)
    yield db


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


def test_load_recent_entries_thread_id_is_post_id_for_comment_c2():
    """P-087: para type=comment thread_id debe ser post_id (no parent_comment_id)."""
    from services.karma_roi_tracker import (
        record_phase_b_comment,
        load_recent_entries,
    )

    # C2: reply anidado — parent_comment_id != post_id
    record_phase_b_comment(
        comment_id="c_c2_t1", post_id="p_root_t1",
        parent_comment_id="c_parent_t1", source="own_post_reply",
        target_author="alice", target_is_watchlist=0, score=None,
        model="m", tier="t", input_tokens=0, output_tokens=0,
        cost_usd=0.0, status="published",
    )
    # Post top-level
    track_action(action_type="post", moltbook_id="p_top_t1", phase="A",
                 cost_usd=0.001, input_tokens=1, output_tokens=1, model="m")

    entries = {e["moltbook_id"]: e for e in load_recent_entries(hours=24)}

    assert entries["c_c2_t1"]["type"] == "comment"
    assert entries["c_c2_t1"]["thread_id"] == "p_root_t1"
    assert entries["c_c2_t1"]["thread_id"] != "c_parent_t1"
    assert entries["p_top_t1"]["type"] == "post"
    assert entries["p_top_t1"]["thread_id"] is None



def test_track_action_post_no_se_marca_como_comment():
    """P-092: track_action(action_type='post') debe guardar action_type='post'."""
    track_action(
        action_type="post", moltbook_id="p_p092", phase="A",
        cost_usd=0.001, input_tokens=1, output_tokens=1, model="m",
    )
    conn = sqlite3.connect(str(krt.DB_PATH))
    row = conn.execute(
        "SELECT action_type FROM comment_actions WHERE comment_id = ?",
        ("p_p092",),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "post"


def test_track_action_comment_sigue_siendo_comment():
    """P-092: comentarios Phase B mantienen action_type='comment'."""
    track_action(
        action_type="comment", moltbook_id="c_p092", phase="B",
        thread_id="p_root", cost_usd=0.001, input_tokens=1,
        output_tokens=1, model="m", source="feed_reply",
    )
    conn = sqlite3.connect(str(krt.DB_PATH))
    row = conn.execute(
        "SELECT action_type FROM comment_actions WHERE comment_id = ?",
        ("c_p092",),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "comment"


def test_get_roi_summary_no_confunde_phase_a_con_b():
    """P-092: post -> phase_a; comment -> phase_b. No mezclar por source."""
    track_action(
        action_type="post", moltbook_id="p_sep", phase="A",
        cost_usd=0.01, input_tokens=1, output_tokens=1, model="m",
    )
    track_action(
        action_type="comment", moltbook_id="c_sep", phase="B",
        thread_id="p_sep", cost_usd=0.02, input_tokens=1,
        output_tokens=1, model="m", source="own_post_reply",
    )
    summary = get_roi_summary(hours=24)
    assert summary["phase_a"]["count"] == 1
    assert summary["phase_b"]["count"] == 1
    assert abs(summary["phase_a"]["total_cost"] - 0.01) < 1e-9
    assert abs(summary["phase_b"]["total_cost"] - 0.02) < 1e-9


def test_load_recent_entries_feed_reply_top_level_p090():
    """P-090: feed_reply top-level (parent NULL) debe clasificarse como comment,
    no como post (bug: get_post(comment_id) -> 404)."""
    from services.karma_roi_tracker import (
        record_phase_b_comment,
        load_recent_entries,
    )
    record_phase_b_comment(
        comment_id="c_fr_top", post_id="p_root_fr",
        parent_comment_id=None, source="feed_reply",
        target_author="bob", target_is_watchlist=0, score=None,
        model="m", tier="t", input_tokens=0, output_tokens=0,
        cost_usd=0.0, status="published",
    )
    entries = {e["moltbook_id"]: e for e in load_recent_entries(hours=24)}
    e = entries["c_fr_top"]
    assert e["type"] == "comment"
    assert e["thread_id"] == "p_root_fr"
