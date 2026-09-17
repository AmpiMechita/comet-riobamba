# -*- coding: utf-8 -*-
"""Archive OFFLINE de namespaces de cache/histórico en comet_dedup.db (V2).

Mueve registros antiguos (created_at < NOW - N days) de namespaces
EXPLÍCITAMENTE PERMITIDOS a una tabla de archivo. Mantiene un mínimo
de K registros en la tabla principal.

NAMESPACES EXCLUIDOS (riesgo de duplicar contenido si se archivan):
  - commented_post: el agente re-publicaría en posts ya comentados
  - agent_comment:   el agente re-generaría comentarios ya publicados
  - followed_agent:  el agente re-seguiría agentes ya seguidos
  - replied_comment, topic_fingerprint, thread_author: dedup activo
    (estos namespaces pueden no existir hoy, pero los respetamos por si
    reaparecen en el futuro)

NAMESPACES PERMITIDOS (cache/histórico, archiving seguro):
  - agent_comment_text: texto cacheado de comments propios
  - upvoted_post:       registro histórico de upvotes

USO:
    python -m scripts.archive_dedup                      # apunta a data/comet_dedup.db
    python -m scripts.archive_dedup --db staging/comet_dedup.db
    python -m scripts.archive_dedup --days 30 --keep-min 10000

NO EJECUTAR MIENTRAS EL AGENTE CORRE: requiere conexión exclusiva a
comet_dedup.db para CREATE/INSERT/DELETE atómicos.
"""
import argparse
import logging
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import BASE_DIR

logger = logging.getLogger("scripts.archive_dedup")

# Namespaces CRÍTICOS: archiving causaría duplicación de contenido.
# No tocar salvo decisión explícita del operador.
EXCLUDED_NAMESPACES = frozenset({
    "commented_post",
    "agent_comment",
    "followed_agent",
    "replied_comment",
    "topic_fingerprint",
    "thread_author",
})

# Namespaces permitidos por defecto (cache/histórico, archiving seguro).
DEFAULT_ALLOWED = ("agent_comment_text", "upvoted_post")


def _setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def _table_for(ns: str) -> str:
    """Tabla de archivo derivada del namespace. Validada como SQL identifier."""
    safe = "".join(c for c in ns if c.isalnum() or c == "_")
    if not safe or safe != ns:
        raise ValueError(f"Namespace no es SQL-safe: {ns!r}")
    return f"archived_{safe}"


def _ensure_archive_table(conn: sqlite3.Connection, ns: str) -> str:
    table = _table_for(ns)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            namespace TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            created_at TEXT,
            archived_at TEXT NOT NULL,
            PRIMARY KEY (namespace, key)
        )
        """
    )
    conn.commit()
    return table


def _count_ns(conn: sqlite3.Connection, ns: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM dedup_store WHERE namespace = ?", (ns,)
    ).fetchone()
    return row[0] if row else 0


def _archive_namespace(
    conn: sqlite3.Connection,
    ns: str,
    cutoff_iso: str,
    keep_min: int,
) -> tuple[int, int]:
    """Archiva entries de `ns` con created_at < cutoff_iso. Retorna (movidos, restantes)."""
    table = _ensure_archive_table(conn, ns)

    total = _count_ns(conn, ns)
    if total <= keep_min:
        logger.info("SKIP %s: solo %d registros (keep_min=%d, no se toca)", ns, total, keep_min)
        return 0, total

    # Calcula cuántos archivar sin bajar de keep_min.
    cursor = conn.execute(
        """
        SELECT COUNT(*) FROM (
          SELECT 1 FROM dedup_store
          WHERE namespace = ? AND created_at < ?
          ORDER BY created_at ASC
          LIMIT ?
        )
        """,
        (ns, cutoff_iso, max(0, total - keep_min)),
    )
    archive_limit = cursor.fetchone()[0]
    if archive_limit == 0:
        logger.info("SKIP %s: nada que archivar bajo cutoff %s", ns, cutoff_iso)
        return 0, total

    # Selecciona los IDs a archivar (los más antiguos).
    rows = conn.execute(
        """
        SELECT namespace, key, value, created_at FROM dedup_store
        WHERE namespace = ? AND created_at < ?
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (ns, cutoff_iso, archive_limit),
    ).fetchall()

    archived_at = datetime.now(timezone.utc).isoformat()
    payload = [(r[0], r[1], r[2], r[3], archived_at) for r in rows]

    with conn:
        conn.executemany(
            f"INSERT OR IGNORE INTO {table} (namespace, key, value, created_at, archived_at) VALUES (?, ?, ?, ?, ?)",
            payload,
        )
        conn.executemany(
            "DELETE FROM dedup_store WHERE namespace = ? AND key = ?",
            [(r[0], r[1]) for r in rows],
        )

    remaining = total - len(rows)
    logger.info("ARCHIVADO %s: %d movidos, %d restantes", ns, len(rows), remaining)
    return len(rows), remaining


def archive_dedup(
    db_path: Path,
    days: int,
    keep_min: int,
    allowed: tuple[str, ...] = DEFAULT_ALLOWED,
) -> dict[str, tuple[int, int]]:
    """Archiva namespaces permitidos. Retorna dict {ns: (movidos, restantes)}."""
    db_path = db_path.resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"DB no encontrada: {db_path}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff.isoformat(sep=" ")
    logger.info("Cutoff: %s (days=%d, keep_min=%d)", cutoff_iso, days, keep_min)

    conn = sqlite3.connect(str(db_path))
    try:
        results: dict[str, tuple[int, int]] = {}
        for ns in allowed:
            if ns in EXCLUDED_NAMESPACES:
                logger.warning("SKIP %s: en EXCLUDED_NAMESPACES", ns)
                continue
            moved, remaining = _archive_namespace(conn, ns, cutoff_iso, keep_min)
            results[ns] = (moved, remaining)
        return results
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Archive offline de dedup cache/histórico.")
    parser.add_argument(
        "--db",
        type=Path,
        default=BASE_DIR / "data" / "comet_dedup.db",
        help="Path a comet_dedup.db (default: data/comet_dedup.db)",
    )
    parser.add_argument("--days", type=int, default=30, help="Días de antigüedad para archivar")
    parser.add_argument(
        "--keep-min", type=int, default=10_000,
        help="Mínimo de registros a mantener por namespace",
    )
    parser.add_argument(
        "--allow", nargs="+", default=list(DEFAULT_ALLOWED),
        help="Namespaces adicionales a permitir (default: agent_comment_text upvoted_post)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)
    logger.info("Iniciando archive. DB: %s", args.db)
    try:
        results = archive_dedup(args.db, args.days, args.keep_min, tuple(args.allow))
    except FileNotFoundError as e:
        logger.error(str(e))
        return 2
    total_moved = sum(m for m, _ in results.values())
    logger.info("Archive completo. Total movidos: %d. Por namespace: %s", total_moved, results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
