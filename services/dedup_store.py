"""
DedupStore — centralized dedup persistence backed by SQLite.
Phase B uses this for all dedup sets/dicts.

Migrates from legacy JSON files on first run (idempotent).
JSON files are NOT deleted — read-only compatibility preserved.
"""

import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger("services.dedup_store")

# Valid Moltbook post_id = UUID. The post-keyed namespaces (agent_comment,
# commented_post) must never persist synthetic/test keys like 'p1' or
# 'new_post': they pollute parent_id matching used by thread follow-ups.
_POST_ID_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def _is_valid_post_key(key) -> bool:
    return isinstance(key, str) and bool(_POST_ID_UUID_RE.match(key))

_JSON_NAMESPACES: List[tuple] = [
    # (namespace, json_path, format_type)
    # format_type: "set" -> list of strings
    #              "commented_post" -> dict post_id:timestamp (or legacy list)
    #              "agent_comment" -> dict post_id:[comment_ids]
    #              "followed_agent" -> dict {following:[], unfollowed:[]} or list
    ("replied_comment", "data/replied_comment_ids.json", "set"),
    ("commented_post", "data/commented_post_ids.json", "commented_post"),
    ("agent_comment", "data/agent_comment_ids.json", "agent_comment"),
    ("thread_author", "data/replied_thread_authors.json", "set"),
    ("topic_fingerprint", "data/replied_topic_fingerprints.json", "set"),
    ("upvoted_post", "data/upvoted_post_ids.json", "set"),
    ("followed_agent", "data/followed_agents.json", "followed_agent"),
]


class DedupStore:
    _default_db_path: Path = Path("data/comet_dedup.db")

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or self._default_db_path)
        self._init_db()
        self._migrate_from_json()
        self._startup_cleanup()

    def _startup_cleanup(self) -> None:
        """Run TTL cleanup on init to prevent stale rows from accumulating across restarts."""
        deleted = self.cleanup(older_than_hours=24)
        if deleted:
            logger.info("DedupStore startup cleanup: purged %d stale rows", deleted)

    @contextmanager
    def _get_conn(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=FULL;")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dedup_store (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (namespace, key)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dedup_ns ON dedup_store(namespace)"
            )

    def _migrate_from_json(self) -> None:
        with self._get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM dedup_store"
            ).fetchone()[0]
            if count > 0:
                logger.info(
                    "DedupStore has %d rows — skipping JSON migration", count
                )
                return

        total = 0
        for namespace, path_str, fmt in _JSON_NAMESPACES:
            path = Path(path_str)
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                n = self._migrate_one(namespace, data, fmt)
                total += n
                logger.info(
                    "Migrated %d entries from %s → dedup_store [%s]",
                    n, path.name, namespace,
                )
            except Exception as e:
                logger.warning(
                    "Could not migrate %s [%s]: %s", path.name, namespace, e
                )

        if total:
            logger.info(
                "JSON migration complete: %d total entries", total
            )

    def _migrate_one(self, namespace: str, data, fmt: str) -> int:
        now_iso = datetime.now().isoformat()
        entries: List[tuple] = []

        if fmt == "set":
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        entries.append((namespace, item, None))
                    elif isinstance(item, (int, float)):
                        entries.append((namespace, str(item), None))
            elif isinstance(data, dict):
                for k, v in data.items():
                    entries.append((namespace, str(k), str(v) if v is not None else None))

        elif fmt == "commented_post":
            if isinstance(data, list):
                for pid in data:
                    if isinstance(pid, str):
                        entries.append((namespace, pid, now_iso))
            elif isinstance(data, dict):
                for pid, ts in data.items():
                    if isinstance(pid, str):
                        entries.append((
                            namespace, pid,
                            ts if isinstance(ts, str) else now_iso,
                        ))

        elif fmt == "agent_comment":
            if isinstance(data, dict):
                for pid, cids in data.items():
                    if isinstance(cids, list):
                        entries.append((
                            namespace, str(pid),
                            json.dumps([str(x) for x in cids], ensure_ascii=False),
                        ))

        elif fmt == "followed_agent":
            if isinstance(data, dict):
                names = data.get("following", [])
                if isinstance(names, list):
                    for name in names:
                        if isinstance(name, str):
                            entries.append((namespace, name, None))
            elif isinstance(data, list):
                for name in data:
                    if isinstance(name, str):
                        entries.append((namespace, name, None))

        if not entries:
            return 0

        with self._get_conn() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO dedup_store (namespace, key, value) VALUES (?, ?, ?)",
                entries,
            )
        return len(entries)

    # ── Generic helpers ──────────────────────────────────────

    def _has(self, namespace: str, key: str) -> bool:
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT 1 FROM dedup_store WHERE namespace=? AND key=?",
                (namespace, key),
            ).fetchone() is not None

    def _add(self, namespace: str, key: str, value: Optional[str] = None) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO dedup_store (namespace, key, value) VALUES (?, ?, ?)",
                (namespace, key, value),
            )

    def _remove(self, namespace: str, key: str) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM dedup_store WHERE namespace=? AND key=?",
                (namespace, key),
            )

    def _get_all(self, namespace: str) -> Dict[str, Optional[str]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT key, value FROM dedup_store WHERE namespace=?",
                (namespace,),
            ).fetchall()
            return {row[0]: row[1] for row in rows}

    def _get_set(self, namespace: str) -> Set[str]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT key FROM dedup_store WHERE namespace=?",
                (namespace,),
            ).fetchall()
            return {row[0] for row in rows}

    def _sync_set(self, namespace: str, ids: Set[str]) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM dedup_store WHERE namespace=?", (namespace,)
            )
            conn.executemany(
                "INSERT INTO dedup_store (namespace, key) VALUES (?, ?)",
                [(namespace, k) for k in ids],
            )

    # ── Replied comments (critical atomic path) ──────────────

    def mark_replied(self, dedup_key: str) -> None:
        """Atomic write: record that we replied to this comment."""
        self._add("replied_comment", dedup_key)

    def has_replied(self, dedup_key: str) -> bool:
        return self._has("replied_comment", dedup_key)

    def get_replied_comment_ids(self) -> Set[str]:
        return self._get_set("replied_comment")

    def sync_replied_comment_ids(self, ids: Set[str]) -> None:
        self._sync_set("replied_comment", ids)

    # ── Commented posts (permanent — no expiry) ──────────────

    def set_commented_post(self, post_id: str) -> None:
        self._add("commented_post", post_id, datetime.now().isoformat())

    def is_commented_post(self, post_id: str) -> bool:
        return self._has("commented_post", post_id)

    def get_commented_post_ids(self) -> Dict[str, str]:
        """Return ALL commented post IDs — permanent dedup, no age filter."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT key, value, created_at FROM dedup_store "
                "WHERE namespace='commented_post'"
            ).fetchall()
            result: Dict[str, str] = {}
            for row in rows:
                val = row[1] or row[2] or datetime.now().isoformat()
                result[row[0]] = val
            return result

    def remove_commented_post(self, post_id: str) -> None:
        self._remove("commented_post", post_id)

    def sync_commented_post_ids(self, ids: Dict[str, str]) -> None:
        # Filtra claves con post_id inválido (no-UUID) para que datos de test
        # como 'new_post' no vuelvan a persistirse en el store real.
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM dedup_store WHERE namespace='commented_post'"
            )
            conn.executemany(
                "INSERT INTO dedup_store (namespace, key, value) VALUES ('commented_post', ?, ?)",
                [(k, v) for k, v in ids.items() if _is_valid_post_key(k)],
            )

    # ── Agent own comment IDs ────────────────────────────────

    def add_agent_comment(self, post_id: str, comment_id: str) -> None:
        existing = self.get_agent_comment_ids().get(post_id, [])
        if comment_id not in existing:
            existing.append(comment_id)
            self._add(
                "agent_comment", post_id,
                json.dumps(existing, ensure_ascii=False),
            )

    def get_agent_comment_ids(self) -> Dict[str, list]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT key, value FROM dedup_store WHERE namespace='agent_comment'"
            ).fetchall()
            result: Dict[str, list] = {}
            for key, val in rows:
                try:
                    result[key] = json.loads(val) if val else []
                except (json.JSONDecodeError, TypeError):
                    result[key] = []
            return result

    def sync_agent_comment_ids(self, data: Dict[str, list]) -> None:
        # Filtra claves con post_id inválido (no-UUID): datos de test como 'p1'
        # ensucian el matching de parent_id del seguimiento de hilos.
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM dedup_store WHERE namespace='agent_comment'"
            )
            conn.executemany(
                "INSERT INTO dedup_store (namespace, key, value) VALUES ('agent_comment', ?, ?)",
                [(k, json.dumps(v, ensure_ascii=False)) for k, v in data.items() if _is_valid_post_key(k)],
            )

    # ── Agent comment TEXTS (contenido por post, cross-ciclo/restart) ──
    # Solo IDs no alcanzan: el guard de repeticion por post necesita el
    # CONTENIDO de nuestros comentarios previos en el thread para comparar
    # parafrasis del mismo argumento. Namespace preservado en cleanup
    # (misma politica que agent_comment).

    def set_agent_comment_text(self, post_id: str, comment_id: str, text: str) -> None:
        """Persiste el TEXTO de un comentario propio (fail-open: un error de
        escritura jamas debe romper el flujo de publicacion)."""
        if not _is_valid_post_key(post_id) or not comment_id or not text:
            return
        try:
            self._add("agent_comment_text", f"{post_id}:{comment_id}", text)
        except Exception as e:
            logger.warning("dedup_store: set_agent_comment_text failed: %s", e)

    def get_agent_comment_text(self, post_id: str, comment_id: str) -> Optional[str]:
        """Texto del comentario propio (post_id, comment_id) o None."""
        if not comment_id:
            return None
        try:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT value FROM dedup_store "
                    "WHERE namespace='agent_comment_text' AND key=?",
                    (f"{post_id}:{comment_id}",),
                ).fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.warning("dedup_store: get_agent_comment_text failed: %s", e)
            return None

    def get_agent_comment_texts_for_post(self, post_id: str) -> List[str]:
        """Todos los textos de comentarios propios en un post (orden de insercion)."""
        try:
            with self._get_conn() as conn:
                rows = conn.execute(
                    "SELECT value FROM dedup_store "
                    "WHERE namespace='agent_comment_text' AND key LIKE ?",
                    (f"{post_id}:%",),
                ).fetchall()
                return [r[0] for r in rows if r[0]]
        except Exception as e:
            logger.warning("dedup_store: get_agent_comment_texts_for_post failed: %s", e)
            return []

    # ── Thread authors ───────────────────────────────────────

    def mark_thread_author(self, author_id: str) -> None:
        self._add("thread_author", author_id)

    def get_replied_thread_authors(self) -> Set[str]:
        return self._get_set("thread_author")

    def sync_replied_thread_authors(self, ids: Set[str]) -> None:
        self._sync_set("thread_author", ids)

    # ── Topic fingerprints ───────────────────────────────────

    def mark_topic_fingerprint(self, fingerprint: str) -> None:
        self._add("topic_fingerprint", fingerprint)

    def has_topic_fingerprint(self, fingerprint: str) -> bool:
        return self._has("topic_fingerprint", fingerprint)

    def get_replied_topic_fingerprints(self) -> Set[str]:
        return self._get_set("topic_fingerprint")

    def sync_replied_topic_fingerprints(self, ids: Set[str]) -> None:
        self._sync_set("topic_fingerprint", ids)

    # ── Upvoted posts ────────────────────────────────────────

    def mark_upvoted(self, post_id: str) -> None:
        self._add("upvoted_post", post_id)

    def is_upvoted(self, post_id: str) -> bool:
        return self._has("upvoted_post", post_id)

    def get_upvoted_post_ids(self) -> Set[str]:
        return self._get_set("upvoted_post")

    def sync_upvoted_post_ids(self, ids: Set[str]) -> None:
        self._sync_set("upvoted_post", ids)

    # ── Followed agents ──────────────────────────────────────

    def mark_followed(self, agent_id: str) -> None:
        self._add("followed_agent", agent_id)

    def is_followed(self, agent_id: str) -> bool:
        return self._has("followed_agent", agent_id)

    def get_followed_agents(self) -> Set[str]:
        return self._get_set("followed_agent")

    def sync_followed_agents(self, ids: Set[str]) -> None:
        self._sync_set("followed_agent", ids)

    # ── TTL cleanup ──────────────────────────────────────────

    def cleanup(self, older_than_hours: int = 24) -> int:
        """Remove fingerprints and dedup entries older than `older_than_hours`.

        Should be called at the start of each cycle to prevent unbounded growth.
        Namespaces cleaned: replied_comment, topic_fingerprint, thread_author.
        Namespaces preserved: commented_post (has its own 7-day logic),
                              agent_comment (needed for per-post limit tracking),
                              upvoted_post, followed_agent (permanent state).
        Returns the number of rows deleted.
        """
        cutoff = (datetime.now() - timedelta(hours=older_than_hours)).isoformat()
        namespaces_to_clean = ("replied_comment", "topic_fingerprint", "thread_author")
        total_deleted = 0
        with self._get_conn() as conn:
            for ns in namespaces_to_clean:
                cursor = conn.execute(
                    "DELETE FROM dedup_store WHERE namespace=? AND created_at < ?",
                    (ns, cutoff),
                )
                total_deleted += cursor.rowcount
        if total_deleted > 0:
            logger.info(
                "DedupStore.cleanup: removed %d expired entries (older than %dh)",
                total_deleted, older_than_hours,
            )
        return total_deleted
