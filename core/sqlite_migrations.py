# -*- coding: utf-8 -*-
"""Versionado de schema SQLite (ADR-005).

Contrato: cada DB declara SCHEMA_VERSION (int) y MIGRATIONS
[(target:int, fn:(conn)->None), ...] ordenado. apply_migrations()
compara PRAGMA user_version, aplica lo pendiente, y valida al final.
SCHEMA_SQL (CREATE ... IF NOT EXISTS) sigue siendo la foto actual.
"""
import logging
import sqlite3
from typing import Callable, List, Tuple

logger = logging.getLogger(__name__)

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
        logger.info("%s: aplicando migracion v%d", label, target)
        fn(conn)
        current = target
        conn.execute(f"PRAGMA user_version = {int(target)}")
        conn.commit()
    if current < schema_version:
        conn.execute(f"PRAGMA user_version = {int(schema_version)}")
        conn.commit()
        current = schema_version
    return current
