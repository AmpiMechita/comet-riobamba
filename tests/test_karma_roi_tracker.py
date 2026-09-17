# -*- coding: utf-8 -*-
"""Tests unitarios para karma_roi_tracker.

Usa la BD real data/karma_roi.db. Limpieza por test con fixture yield.
Compatibilidad hacia atrás con test_karma_tracking.py preservada.
"""

import json
import os
import sqlite3
from pathlib import Path

import pytest

import services.karma_roi_tracker as krt
from services.karma_roi_tracker import (
    track_action,
    update_karma,
    get_roi_summary,
    KARMA_TRACKER_FILE,
)


# ── Fixture: limpia BD y JSONL antes y después de cada test ──────────

@pytest.fixture(autouse=True)
def cleanup_after_test():
    """Limpia la BD y JSONL antes y después de cada test para aislamiento total."""
    # Limpiar BD antes
    db_path = krt.DB_PATH if isinstance(krt.DB_PATH, Path) else Path(krt.DB_PATH)
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        conn.execute("DELETE FROM comment_actions")
        conn.execute("DELETE FROM engagement_events")
        conn.execute("DELETE FROM daily_snapshots")
        conn.commit()
        conn.close()

    # Limpiar JSONL antes
    jsonl_path = Path(krt.KARMA_TRACKER_FILE)
    if jsonl_path.exists():
        jsonl_path.unlink(missing_ok=True)

    yield

    # Limpiar JSONL después (pequeño delay para asegurar escritura)
    import time
    time.sleep(0.1)

    jsonl_path = Path(krt.KARMA_TRACKER_FILE)
    if jsonl_path.exists():
        jsonl_path.unlink(missing_ok=True)

    # Limpiar BD después
    db_path = krt.DB_PATH if isinstance(krt.DB_PATH, Path) else Path(krt.DB_PATH)
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        conn.execute("DELETE FROM comment_actions")
        conn.execute("DELETE FROM engagement_events")
        conn.execute("DELETE FROM daily_snapshots")
        conn.commit()
        conn.close()


# ── 1. Inserción básica de acción ───────────────────────────────

def test_track_action_basic():
    """track_action debe guardar una entrada en la BD y JSONL."""
    track_action(
        action_type="post",
        moltbook_id="test_post_001",
        phase="A",
        cost_usd=0.001234,
        input_tokens=150,
        output_tokens=50,
        model="deepseek-v4-pro",
    )

    # Verificar JSONL
    assert Path(krt.KARMA_TRACKER_FILE).exists(), "JSONL file should exist"
    with open(str(krt.KARMA_TRACKER_FILE), "r", encoding="utf-8") as f:
        entry = json.loads(f.readline())
    assert entry["moltbook_id"] == "test_post_001"
    assert entry["phase"] == "A"
    assert entry["cost_usd"] == 0.001234

    # Verificar BD
    import sqlite3
    conn = sqlite3.connect(str(krt.DB_PATH))
    row = conn.execute(
        "SELECT cost_usd FROM comment_actions WHERE comment_id = 'test_post_001'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 0.001234


# ── 2. Actualizar karma ─────────────────────────────────────────

def test_update_karma():
    """update_karma debe actualizar upvotes y karma_score."""
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

    # Verificar JSONL
    with open(str(krt.KARMA_TRACKER_FILE), "r", encoding="utf-8") as f:
        entry = json.loads(f.readline())
    assert entry["upvotes_24h"] == 10
    assert entry["comments_received"] == 2
    assert entry["karma_score"] == 10

    # Verificar BD
    import sqlite3
    conn = sqlite3.connect(str(krt.DB_PATH))
    row = conn.execute(
        "SELECT score FROM comment_actions WHERE comment_id = 'karma_test'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 10


# ── 3. Resumen ROI básico ───────────────────────────────────────

def test_get_roi_summary_basic():
    """get_roi_summary debe devolver estructura correcta."""
    summary = get_roi_summary(hours=24)
    assert "period_hours" in summary
    assert "phase_a" in summary
    assert "phase_b" in summary
    assert "roi_ratio_a_vs_b" in summary
    assert "recommendation" in summary


# ── 4. Kompatibilidad: KARMA_TRACKER_FILE ────────────────────────

def test_kompatibilidad_jsonl():
    """KARMA_TRACKER_FILE debe ser legible por scripts existentes."""
    track_action(
        action_type="post",
        moltbook_id="compat_test",
        phase="A",
        cost_usd=0.005,
        input_tokens=100,
        output_tokens=25,
        model="deepseek-v4-flash",
    )

    original_jsonl = str(krt.KARMA_TRACKER_FILE)
    assert Path(original_jsonl).exists(), "JSONL file should exist"

    with open(original_jsonl, "r", encoding="utf-8") as f:
        entry = json.loads(f.readline())
    assert entry["moltbook_id"] == "compat_test"


# ── 5. Sin datos previos ────────────────────────────────────────

def test_sin_datos_previos():
    """Dashboard debe manejar gracefully cuando no hay datos."""
    summary = get_roi_summary(hours=24)
    assert summary["period_hours"] == 24
    assert summary["phase_a"]["count"] == 0
    assert summary["phase_b"]["count"] == 0
    assert summary["roi_ratio_a_vs_b"] == 0