from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

_VALID_STATUSES = ("claimed", "disputed", "debunked")


class EnergyKnowledgeBase:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (Path(__file__).resolve().parents[1] / "data" / "energy_intel.db")
        self.available = False
        if not self.db_path.exists():
            return
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("SELECT 1 FROM claims LIMIT 1")
            uv = conn.execute("PRAGMA user_version").fetchone()[0]
            conn.close()
            if uv < 1:
                return
            self.available = True
        except (sqlite3.Error, OSError):
            self.available = False

    def get_recent_claims(self, limit: int = 5) -> List[Dict[str, Any]]:
        if not self.available:
            return []
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM claims WHERE technology != ? ORDER BY date_pub DESC LIMIT ?",
                ("other", limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        except sqlite3.Error:
            return []

    def get_claims_by_technology(self, tech: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not self.available:
            return []
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM claims WHERE technology = ? ORDER BY date_pub DESC LIMIT ?",
                (tech, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        except sqlite3.Error:
            return []

    def update_claim_status(self, claim_id: str, new_status: str) -> bool:
        if new_status not in _VALID_STATUSES:
            return False
        if not self.available:
            return False
        try:
            conn = sqlite3.connect(str(self.db_path))
            cur = conn.execute(
                "UPDATE claims SET status = ? WHERE id = ?",
                (new_status, claim_id),
            )
            conn.commit()
            affected = cur.rowcount > 0
            conn.close()
            return affected
        except sqlite3.Error:
            return False
