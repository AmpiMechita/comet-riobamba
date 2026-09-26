# -*- coding: utf-8 -*-
"""Versionado schema SQLite repurposer (mirror ADR-005).

Helper local: el repurposer es paquete standalone (ver README, requirements.txt);
no importa core/. Contrato identico a core/sqlite_migrations.py.
"""
import sqlite3
from typing import Callable, List, Tuple

Migration = Tuple[int, Callable[[sqlite3.Connection], None]]


def apply_migrations(conn, schema_version, migrations, label="db"):
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > schema_version:
        raise RuntimeError(f"{label}: user_version={current} > SCHEMA_VERSION={schema_version}")
    if current == schema_version:
        return current
    for target, fn in migrations:
        if target <= current:
            continue
        fn(conn)
        current = target
        conn.execute(f"PRAGMA user_version = {int(target)}")
        conn.commit()
    if current < schema_version:
        conn.execute(f"PRAGMA user_version = {int(schema_version)}")
        conn.commit()
        current = schema_version
    return current
