# -*- coding: utf-8 -*-
"""Tests P-093: versionado de schema SQLite (ADR-005)."""
import sqlite3

import pytest

from core.sqlite_migrations import apply_migrations


def _uv(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def test_fresh_db_empty_migrations_baseline_jump(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "fresh.db"))
    conn.execute("CREATE TABLE t(x)")
    assert _uv(conn) == 0
    apply_migrations(conn, 1, [], label="fresh")
    assert _uv(conn) == 1
    apply_migrations(conn, 1, [], label="fresh")
    assert _uv(conn) == 1
    conn.close()


def test_fresh_db_with_migration_applies_and_changes_schema(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "m.db"))
    conn.execute("CREATE TABLE t(x)")

    def v1(c):
        c.execute("ALTER TABLE t ADD COLUMN y TEXT")

    apply_migrations(conn, 1, [(1, v1)], label="m")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(t)")]
    assert "y" in cols
    assert _uv(conn) == 1
    conn.close()


def test_migration_is_idempotent(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "id.db"))
    conn.execute("CREATE TABLE t(x)")
    calls = {"n": 0}

    def v1(c):
        calls["n"] += 1
        c.execute("ALTER TABLE t ADD COLUMN y TEXT")

    apply_migrations(conn, 1, [(1, v1)], label="id")
    apply_migrations(conn, 1, [(1, v1)], label="id")
    apply_migrations(conn, 1, [(1, v1)], label="id")
    assert calls["n"] == 1
    assert _uv(conn) == 1
    conn.close()


def test_user_version_newer_than_schema_raises(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "newer.db"))
    conn.execute("PRAGMA user_version = 5")
    with pytest.raises(RuntimeError, match="user_version=5"):
        apply_migrations(conn, 1, [], label="newer")
    conn.close()


def test_multi_step_migrations_run_in_order(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "multi.db"))
    conn.execute("CREATE TABLE t(x)")
    order = []

    def v1(c):
        order.append(1)
        c.execute("ALTER TABLE t ADD COLUMN a TEXT")

    def v2(c):
        order.append(2)
        c.execute("ALTER TABLE t ADD COLUMN b TEXT")

    apply_migrations(conn, 2, [(1, v1), (2, v2)], label="multi")
    assert order == [1, 2]
    cols = [r[1] for r in conn.execute("PRAGMA table_info(t)")]
    assert "a" in cols and "b" in cols
    assert _uv(conn) == 2
    conn.close()


def test_karma_roi_tracker_wires_to_helper(tmp_path):
    """Integracion: karma_roi_tracker expone SCHEMA_VERSION y MIGRATIONS."""
    from services import karma_roi_tracker as krt
    assert krt.SCHEMA_VERSION == 1
    assert isinstance(krt.MIGRATIONS, list)
    assert krt.MIGRATIONS[0][0] == 1
