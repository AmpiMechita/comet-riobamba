# -*- coding: utf-8 -*-
"""
COMET-RIOBAMBA v5.0 — Módulo de persistencia

Responsabilidades:
- Estado del agente (ciclos, posts_today, versión)
- Registro de acciones (auditoría de lo que hace el agente)
- Outbox de publicaciones pendientes
- (Extensible) métricas de engagement, embeddings, flags de sistema

Diseñado para uso en un solo nodo local con un único proceso escritor.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "comet_state.db"


@contextmanager
def get_conn():
    """
    Devuelve una conexión SQLite con WAL y synchronous=FULL para buena durabilidad
    en un escenario single-node, single-writer.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        # WAL + FULL para equilibrar durabilidad y rendimiento.[web:48][web:50]
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=FULL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """
    Inicializa el esquema de base de datos si no existe.
    Idempotente: se puede llamar múltiples veces sin efectos secundarios.
    """
    with get_conn() as conn:
        # Estado del agente (una única fila id=1)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                cycle INTEGER NOT NULL,
                posts_today INTEGER NOT NULL,
                comments_today INTEGER NOT NULL DEFAULT 0,
                last_post_date TEXT,
                last_post_timestamp TEXT,
                last_value_review TEXT,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                last_cycle_at TEXT,
                version TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO agent_state (id, cycle, posts_today, comments_today, last_post_date, last_post_timestamp, last_value_review, consecutive_failures, last_cycle_at, version)
            VALUES (1, 0, 0, 0, NULL, NULL, NULL, 0, NULL, '5.0')
            """
        )

        # Migrations for existing databases that lack newer columns
        for col, col_type in [("last_post_date", "TEXT"), ("comments_today", "INTEGER NOT NULL DEFAULT 0"),
                              ("last_value_review", "TEXT"), ("consecutive_failures", "INTEGER NOT NULL DEFAULT 0"),
                              ("retry_attempt", "INTEGER NOT NULL DEFAULT 0"), ("next_retry_at", "TEXT"),
                              ("last_post_timestamp", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE agent_state ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass

        # Registro de acciones (auditoría)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle INTEGER NOT NULL,
                phase TEXT NOT NULL,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                latency_ms REAL,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )

        # Outbox de pendientes
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,          -- 'post' | 'comment' | etc.
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,        -- 'pending' | 'published' | 'failed' | 'needs_reconciliation'
                last_error TEXT,
                retry_attempt INTEGER NOT NULL DEFAULT 0,
                next_retry_at TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )

        # Métricas de engagement (opcional, para Fase C)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS engagement (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT NOT NULL,
                kind TEXT NOT NULL,          -- 'post' | 'comment'
                topic TEXT,
                template TEXT,
                likes INTEGER,
                comments INTEGER,
                shares INTEGER,
                impressions INTEGER,
                created_at TEXT,
                collected_at TEXT DEFAULT (datetime('now'))
            )
            """
        )

        # Embeddings/text-hash (para deduplicación ligera)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS post_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT,
                text_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )

        # Flags de sistema (circuit breakers, toggles, etc.)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_flags (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )


# ============================================================
# Estado del agente
# ============================================================

def load_agent_state() -> Dict[str, Any]:
    """
    Carga el estado del agente desde la tabla agent_state.
    """
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT cycle, posts_today, comments_today, last_post_date, last_post_timestamp, last_value_review, consecutive_failures, last_cycle_at, version FROM agent_state WHERE id = 1"
        ).fetchone()
    if row is None:
        return {
            "cycle": 0,
            "posts_today": 0,
            "comments_today": 0,
            "last_post_date": None,
            "last_post_timestamp": None,
            "last_value_review": None,
            "consecutive_failures": 0,
            "last_cycle_at": None,
            "version": "5.0",
        }
    return {
        "cycle": row[0],
        "posts_today": row[1],
        "comments_today": row[2] if row[2] is not None else 0,
        "last_post_date": row[3],
        "last_post_timestamp": row[4],
        "last_value_review": row[5],
        "consecutive_failures": row[6] if row[6] is not None else 0,
        "last_cycle_at": row[7],
        "version": row[8],
    }


def save_agent_state(state: Dict[str, Any]) -> None:
    """
    Actualiza el estado del agente en la tabla agent_state.
    """
    init_db()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE agent_state
            SET cycle = ?, posts_today = ?, comments_today = ?, last_post_date = ?,
                last_post_timestamp = ?, last_value_review = ?, consecutive_failures = ?,
                last_cycle_at = ?, version = ?
            WHERE id = 1
            """,
            (
                int(state.get("cycle", 0)),
                int(state.get("posts_today", 0)),
                int(state.get("comments_today", 0)),
                state.get("last_post_date"),
                state.get("last_post_timestamp"),
                state.get("last_value_review"),
                int(state.get("consecutive_failures", 0)),
                state.get("last_cycle_at"),
                state.get("version", "5.0"),
            ),
        )


# ============================================================
# Acciones (auditoría)
# ============================================================

def record_action(
    cycle: int,
    phase: str,
    action_type: str,
    payload: Dict[str, Any],
    status: str,
    latency_ms: Optional[float] = None,
) -> None:
    """
    Registra una acción del agente (create_post, reply_comment, insight, etc.).
    """
    init_db()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO actions (cycle, phase, type, payload_json, status, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                cycle,
                phase,
                action_type,
                json.dumps(payload, ensure_ascii=False),
                status,
                latency_ms,
            ),
        )


# ============================================================
# Outbox
# ============================================================

def enqueue_outbox(kind: str, payload: Dict[str, Any]) -> None:
    """
    Encola una nueva entrada en outbox (pendiente de publicación).
    kind: 'post', 'comment', etc.
    """
    init_db()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO outbox (kind, payload_json, status, retry_attempt)
            VALUES (?, ?, 'pending', 0)
            """,
            (kind, json.dumps(payload, ensure_ascii=False)),
        )


def _sqlite_ts(dt: datetime) -> str:
    """Formatea un datetime al formato que SQLite datetime('now') produce: YYYY-MM-DD HH:MM:SS."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _compute_next_retry_at(retry_attempt: int, min_backoff: int = 60, max_backoff: int = 3600) -> str:
    """
    Exponential backoff formula: delay = min(max_backoff, min_backoff * 2^retry_attempt).
    Returns SQLite-compatible timestamp (UTC) for next allowed retry.
    Uses UTC to stay aligned with SQLite's datetime('now') which is UTC.
    """
    from datetime import timedelta, timezone
    delay = min(max_backoff, min_backoff * (2 ** retry_attempt))
    return _sqlite_ts(datetime.now(timezone.utc) + timedelta(seconds=delay))


def fetch_pending_outbox(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Obtiene hasta 'limit' elementos pendientes del outbox cuyo next_retry_at
    ya haya vencido (o no tenga fecha), en orden FIFO.
    """
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, kind, payload_json, retry_attempt
            FROM outbox
            WHERE status = 'pending'
              AND (next_retry_at IS NULL OR datetime(next_retry_at) <= datetime('now'))
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result: List[Dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "id": row[0],
                "kind": row[1],
                "payload": json.loads(row[2]),
                "retry_attempt": row[3],
            }
        )
    return result


def mark_outbox(outbox_id: int, status: str, last_error: Optional[str] = None) -> None:
    """
    Actualiza el estado de un item en outbox.
    status: 'pending' | 'published' | 'failed' | 'needs_reconciliation'
    """
    init_db()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE outbox
            SET status = ?, last_error = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (status, last_error, outbox_id),
        )


def update_outbox_backoff(outbox_id: int, last_error: str, retry_attempt: int,
                          min_backoff: int = 60, max_backoff: int = 3600) -> None:
    """
    Incrementa retry_attempt, establece next_retry_at con backoff exponencial,
    y mantiene status='pending'.
    """
    next_at = _compute_next_retry_at(retry_attempt, min_backoff, max_backoff)
    init_db()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE outbox
            SET retry_attempt = ?,
                next_retry_at = ?,
                last_error = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (retry_attempt, next_at, last_error, outbox_id),
        )


# ============================================================
# Engagement (para Fase C)
# ============================================================

def record_engagement(
    post_id: str,
    kind: str,
    topic: Optional[str],
    template: Optional[str],
    likes: int,
    comments: int,
    shares: int,
    impressions: int,
    created_at: str,
) -> None:
    """
    Registra métricas de engagement para un contenido (post/comment).
    """
    init_db()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO engagement (
                post_id, kind, topic, template,
                likes, comments, shares, impressions,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post_id,
                kind,
                topic,
                template,
                likes,
                comments,
                shares,
                impressions,
                created_at,
            ),
        )


def load_topic_engagement(window_days: int = 30) -> Dict[str, float]:
    """
    Devuelve engagement promedio por topic en la ventana de window_days.
    Engagement = likes + comments + shares (promedio por post).
    """
    init_db()
    query = """
        SELECT topic,
               AVG(COALESCE(likes,0) + COALESCE(comments,0) + COALESCE(shares,0)) AS engagement
        FROM engagement
        WHERE created_at >= datetime('now', ?)
          AND topic IS NOT NULL
        GROUP BY topic
    """
    values = [f"-{window_days} days"]
    stats: Dict[str, float] = {}
    with get_conn() as conn:
        for topic, engagement in conn.execute(query, values):
            stats[topic] = engagement or 0.0
    return stats


# ============================================================
# Deduplicación ligera (hash de texto)
# ============================================================

import hashlib


def text_hash(text: str) -> str:
    """
    Calcula un hash SHA-256 del texto (para deduplicación básica).
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_similar_to_recent(text: str, window_days: int = 7) -> bool:
    """
    Indica si el texto ya fue visto en la ventana reciente (misma hash).
    Es una deduplicación muy simple (idéntico texto).
    """
    init_db()
    h = text_hash(text)
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM post_embeddings
            WHERE text_hash = ?
              AND created_at >= datetime('now', ?)
            LIMIT 1
            """,
            (h, f"-{window_days} days"),
        ).fetchone()
    return row is not None


def store_post_hash(post_id: Optional[str], text: str) -> None:
    """
    Guarda el hash del texto publicado para futuras comprobaciones de similitud.
    """
    init_db()
    h = text_hash(text)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO post_embeddings (post_id, text_hash)
            VALUES (?, ?)
            """,
            (post_id, h),
        )


# ============================================================
# Flags de sistema (circuit breakers, toggles)
# ============================================================

def set_flag(key: str, value: Dict[str, Any]) -> None:
    """
    Guarda o actualiza un flag de sistema en formato JSON.
    Ejemplo: {"open": true, "reason": "too_many_errors"}.
    """
    init_db()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO system_flags (key, value_json, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False)),
        )


def get_flag(key: str) -> Optional[Dict[str, Any]]:
    """
    Obtiene el flag de sistema (o None si no existe).
    """
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value_json FROM system_flags WHERE key = ?",
            (key,),
        ).fetchone()
    if not row:
        return None
    return json.loads(row[0])