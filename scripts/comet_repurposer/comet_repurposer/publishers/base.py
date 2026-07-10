"""
Common publisher infrastructure: queue, kill switch, base interface.

The queue lives at ``data/publish_queue.db`` (SQLite) and stores every
pending publication across every platform. Each row is one
:class:`PublishJob`.

States::

    generated -> approved -> scheduled -> published
                                       |-> failed
        |-> rejected
        |-> cancelled

Transitions are explicit and one-way. The CLI enforces them.

Kill switch: a sentinel file at ``data/KILL_SWITCH`` (path configurable)
stops every publisher from actually hitting an API. Useful for emergencies
or while iterating on prompts.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class PublishStatus(str, Enum):
    GENERATED = "generated"     # ready for review, not yet approved
    APPROVED = "approved"       # user approved, waiting for schedule
    SCHEDULED = "scheduled"     # assigned a scheduled_at, waiting to fire
    PUBLISHED = "published"     # successfully posted
    FAILED = "failed"           # publish attempt failed (see error)
    REJECTED = "rejected"       # user rejected during review
    CANCELLED = "cancelled"     # user cancelled after approval


@dataclass
class PublishJob:
    """One unit of work for the publisher queue."""

    id: Optional[int] = None
    platform: str = ""                # 'linkedin' | 'twitter'
    source_id: str = ""               # original SourceItem id
    source_kind: str = ""
    title: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)  # platform-specific
    payload_text: str = ""            # pre-rendered text to post (for preview)
    status: PublishStatus = PublishStatus.GENERATED
    scheduled_at: Optional[float] = None  # epoch seconds
    published_at: Optional[float] = None
    platform_post_id: Optional[str] = None  # id returned by the platform
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_row(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["payload"] = json.dumps(self.payload, ensure_ascii=False)
        return d

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "PublishJob":
        return cls(
            id=row["id"],
            platform=row["platform"],
            source_id=row["source_id"],
            source_kind=row["source_kind"],
            title=row["title"],
            payload=json.loads(row["payload"] or "{}"),
            payload_text=row["payload_text"] or "",
            status=PublishStatus(row["status"]),
            scheduled_at=row["scheduled_at"],
            published_at=row["published_at"],
            platform_post_id=row["platform_post_id"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class PublishError(RuntimeError):
    """Base class for publisher errors."""


class AuthError(PublishError):
    """OAuth credentials missing or invalid."""


class RateLimitError(PublishError):
    """Platform returned a rate-limit response."""


# ---------------------------------------------------------------------------
# Queue store
# ---------------------------------------------------------------------------

class QueueStore:
    """SQLite-backed queue of :class:`PublishJob`."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS publish_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_kind TEXT NOT NULL,
        title TEXT NOT NULL,
        payload TEXT NOT NULL,
        payload_text TEXT NOT NULL,
        status TEXT NOT NULL,
        scheduled_at REAL,
        published_at REAL,
        platform_post_id TEXT,
        error TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_status ON publish_queue(status);
    CREATE INDEX IF NOT EXISTS idx_platform_status ON publish_queue(platform, status);
    CREATE INDEX IF NOT EXISTS idx_scheduled ON publish_queue(scheduled_at)
        WHERE status IN ('approved','scheduled');
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self.SCHEMA)
        self._conn.commit()

    def enqueue(self, job: PublishJob) -> int:
        row = job.to_row()
        cols = ", ".join(row.keys())
        placeholders = ", ".join(["?"] * len(row))
        cur = self._conn.execute(
            f"INSERT INTO publish_queue ({cols}) VALUES ({placeholders})",
            tuple(row.values()),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def get(self, job_id: int) -> Optional[PublishJob]:
        cur = self._conn.execute(
            "SELECT * FROM publish_queue WHERE id = ?", (job_id,)
        )
        row = cur.fetchone()
        return PublishJob.from_row(row) if row else None

    def list_by_status(
        self, status: Optional[PublishStatus] = None, platform: Optional[str] = None,
        limit: int = 100,
    ) -> List[PublishJob]:
        q = "SELECT * FROM publish_queue WHERE 1=1"
        params: List[Any] = []
        if status is not None:
            q += " AND status = ?"
            params.append(status.value)
        if platform is not None:
            q += " AND platform = ?"
            params.append(platform)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cur = self._conn.execute(q, params)
        return [PublishJob.from_row(r) for r in cur.fetchall()]

    def list_ready_to_publish(self, now: Optional[float] = None) -> List[PublishJob]:
        """Approved+scheduled jobs whose scheduled_at has elapsed."""
        now = now or time.time()
        cur = self._conn.execute(
            """
            SELECT * FROM publish_queue
            WHERE status IN ('approved','scheduled')
              AND (scheduled_at IS NULL OR scheduled_at <= ?)
            ORDER BY COALESCE(scheduled_at, 0) ASC
            """,
            (now,),
        )
        return [PublishJob.from_row(r) for r in cur.fetchall()]

    def update(self, job: PublishJob) -> None:
        job.updated_at = time.time()
        row = job.to_row()
        sets = ", ".join(f"{k} = ?" for k in row.keys() if k != "id")
        vals = [v for k, v in row.items() if k != "id"]
        vals.append(job.id)
        self._conn.execute(
            f"UPDATE publish_queue SET {sets} WHERE id = ?", vals
        )
        self._conn.commit()

    def count_by_status(self, platform: Optional[str] = None) -> Dict[str, int]:
        q = "SELECT status, COUNT(*) AS n FROM publish_queue"
        params: List[Any] = []
        if platform:
            q += " WHERE platform = ?"
            params.append(platform)
        q += " GROUP BY status"
        cur = self._conn.execute(q, params)
        return {r["status"]: r["n"] for r in cur.fetchall()}

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

def kill_switch_active(kill_switch_path: Path) -> bool:
    """Return True if the kill-switch sentinel file exists."""
    return Path(kill_switch_path).exists()


def activate_kill_switch(kill_switch_path: Path, reason: str = "") -> None:
    """Create the sentinel file. Subsequent publish calls will refuse to run."""
    kill_switch_path = Path(kill_switch_path)
    kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
    kill_switch_path.write_text(
        f"KILL_SWITCH activated at {time.time()}\nReason: {reason}\n",
        encoding="utf-8",
    )


def deactivate_kill_switch(kill_switch_path: Path) -> None:
    """Remove the sentinel file."""
    p = Path(kill_switch_path)
    if p.exists():
        p.unlink()


# ---------------------------------------------------------------------------
# Base publisher
# ---------------------------------------------------------------------------

class BasePublisher:
    """Interface every concrete publisher implements."""

    platform: str = "base"

    def __init__(self, credentials: Dict[str, str], dry_run: bool = True,
                 timeout: float = 30.0) -> None:
        self.credentials = credentials
        self.dry_run = dry_run
        self.timeout = timeout

    def validate_credentials(self) -> None:
        """Raise :class:`AuthError` if required credentials are missing."""
        raise NotImplementedError

    def publish(self, job: PublishJob) -> PublishJob:
        """Publish the job. Returns the updated job (with platform_post_id
        or error set). Honors ``self.dry_run`` and the kill switch."""
        raise NotImplementedError
