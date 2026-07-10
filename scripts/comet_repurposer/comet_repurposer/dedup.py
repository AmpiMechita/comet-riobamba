"""
SQLite-backed dedup store.

Mirrors the pattern comet_riobamba uses for ``data/comet_dedup.db``:
we hash ``(source_id, platform, language)`` and skip items we've already
repurposed, unless the user forces a re-run with ``--force``.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Optional


class DedupStore:
    """Tiny SQLite wrapper with two operations: ``seen?`` and ``mark``."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS repurpose_log (
                hash TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                language TEXT NOT NULL,
                output_path TEXT,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    @staticmethod
    def _hash(source_id: str, platform: str, language: str) -> str:
        raw = f"{source_id}|{platform}|{language}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def seen(self, source_id: str, platform: str, language: str) -> bool:
        h = self._hash(source_id, platform, language)
        cur = self._conn.execute(
            "SELECT 1 FROM repurpose_log WHERE hash = ? LIMIT 1", (h,)
        )
        return cur.fetchone() is not None

    def mark(
        self,
        source_id: str,
        platform: str,
        language: str,
        output_path: Optional[str] = None,
    ) -> None:
        h = self._hash(source_id, platform, language)
        self._conn.execute(
            """
            INSERT OR REPLACE INTO repurpose_log
                (hash, source_id, platform, language, output_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (h, source_id, platform, language, output_path, time.time()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
