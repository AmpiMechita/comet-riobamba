"""Tests de versionado schema repurposer (mirror ADR-005 / P-100a).

Run:  python -m pytest tests/test_migrations_repurposer.py -v
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from comet_repurposer.migrations import apply_migrations
from comet_repurposer.dedup import DedupStore
from comet_repurposer.semantic_dedup import SemanticDedup
from comet_repurposer.publishers.base import QueueStore


def _tmp_db() -> Path:
    d = Path(tempfile.mkdtemp(prefix="rep_p100a_"))
    return d / "t.db"


def test_baseline_jump_sets_user_version():
    c = sqlite3.connect(str(_tmp_db()))
    r = apply_migrations(c, 1, [], label="t")
    assert r == 1
    assert c.execute("PRAGMA user_version").fetchone()[0] == 1
    c.close()


def test_idempotent():
    p = _tmp_db()
    c1 = sqlite3.connect(str(p)); apply_migrations(c1, 1, [], label="t"); c1.close()
    c2 = sqlite3.connect(str(p)); r = apply_migrations(c2, 1, [], label="t"); c2.close()
    assert r == 1


def test_user_version_ahead_raises():
    p = _tmp_db()
    c = sqlite3.connect(str(p)); c.execute("PRAGMA user_version = 5"); c.commit()
    try:
        apply_migrations(c, 1, [], label="t")
        assert False, "debio lanzar RuntimeError"
    except RuntimeError as e:
        assert "user_version=5" in str(e)
    finally:
        c.close()


def test_multi_step_applies_in_order():
    p = _tmp_db()
    c = sqlite3.connect(str(p))
    log = []
    def v1(conn): log.append(1); conn.execute("CREATE TABLE a(x)")
    def v2(conn): log.append(2); conn.execute("ALTER TABLE a ADD COLUMN y TEXT")
    r = apply_migrations(c, 2, [(1, v1), (2, v2)], label="t")
    assert r == 2 and log == [1, 2]
    assert c.execute("PRAGMA user_version").fetchone()[0] == 2
    c.close()


def test_dedup_store_sets_uv():
    s = DedupStore(_tmp_db())
    assert s._conn.execute("PRAGMA user_version").fetchone()[0] == 1
    s._conn.close()


def test_semantic_dedup_sets_uv():
    s = SemanticDedup(_tmp_db(), embeddings_client=None)
    assert s._conn.execute("PRAGMA user_version").fetchone()[0] == 1
    s._conn.close()


def test_queue_store_sets_uv():
    s = QueueStore(_tmp_db())
    assert s._conn.execute("PRAGMA user_version").fetchone()[0] == 1
    s._conn.close()
