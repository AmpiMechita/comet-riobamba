import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from core.sqlite_migrations import apply_migrations

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS agent_memory (
    user_id        TEXT PRIMARY KEY,
    username       TEXT,
    summary        TEXT,
    last_interaction TIMESTAMP
)
"""

_UPSERT = """
INSERT OR REPLACE INTO agent_memory (user_id, username, summary, last_interaction)
VALUES (?, ?, ?, ?)
"""

_GET = "SELECT user_id, username, summary, last_interaction FROM agent_memory WHERE user_id = ?"

SCHEMA_VERSION = 1
MIGRATIONS = []


class MemoryStore:
    def __init__(self, db_path: str = "data/memory.db") -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        try:
            conn = self._get_conn()
            conn.execute(_CREATE_TABLE)
            apply_migrations(conn, SCHEMA_VERSION, MIGRATIONS, label="memory.db")
            conn.commit()
        except Exception as exc:
            logger.warning("MemoryStore: error inicializando DB: %s", exc)

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def get_memory(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            conn = self._get_conn()
            row = conn.execute(_GET, (user_id,)).fetchone()
            if row is None:
                return None
            return {
                "user_id": row["user_id"],
                "username": row["username"],
                "summary": row["summary"],
                "last_interaction": row["last_interaction"],
            }
        except Exception as exc:
            logger.warning("MemoryStore: error leyendo memoria de %s: %s", user_id, exc)
            return None

    def update_memory(self, user_id: str, username: str, summary: str) -> None:
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn = self._get_conn()
            conn.execute(_UPSERT, (user_id, username, summary, now))
            conn.commit()
        except Exception as exc:
            logger.warning("MemoryStore: error actualizando memoria de %s: %s", user_id, exc)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
