# -*- coding: utf-8 -*-
"""
Purga del outbox: entradas con status='failed' por 404 "Parent comment not
found" (padre borrado — determinista, reintentar no sirve).

Ademas de descartar las entradas, marca los comment_id involucrados como
unrepliable en el namespace durable (reply_cap), para que la cola de Phase B
los descarte ANTES de generar (nunca mas LLM para un comentario muerto).

Seguridad:
  - Backup del data/comet_state.db ANTES de tocar nada (comet_state.db.backup-<ts>).
  - Sin --apply solo reporta (dry-run). Con --apply ejecuta la purga.
  - No toca entradas 'pending'/'published'/'needs_reconciliation'.

Uso:
  python -m scripts.purge_outbox                 # dry-run (reporta)
  python -m scripts.purge_outbox --apply         # backup + purga + reporta
"""

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import services.persistence as sp
from services import reply_cap

_PARENT404_LIKE = (
    "status = 'failed' "
    "AND last_error LIKE '%404%' "
    "AND last_error LIKE '%Parent comment not found%'"
)


def find_failed_parent404(conn: sqlite3.Connection) -> List[Tuple[int, str, int, str]]:
    """Entradas failed con 404 de padre inexistente: (id, payload_json, retry_attempt, last_error)."""
    cur = conn.execute(
        f"SELECT id, payload_json, retry_attempt, last_error FROM outbox WHERE {_PARENT404_LIKE} ORDER BY id"
    )
    return cur.fetchall()


def backup_db(db_path: Path) -> Optional[str]:
    """Copia del .db antes de purgar. Devuelve la ruta del backup o None."""
    try:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = db_path.with_name(f"{db_path.name}.backup-{stamp}")
        shutil.copy2(db_path, backup)
        return str(backup)
    except OSError as e:
        print(f"[PURGE] ERROR: no se pudo respaldar {db_path}: {e}")
        return None


def purge_failed_parent404(db_path: Optional[Path] = None, apply: bool = False) -> Dict[str, object]:
    """Encuentra (y opcionalmente descarta) las entradas 404-parent del outbox.

    Devuelve: {found, purged, unrepliable_marked, backup, skipped_non404}.
    Con apply=False no modifica nada (dry-run).
    """
    db_path = db_path or sp.DB_PATH
    backup = None
    if apply:
        backup = backup_db(db_path)
        if backup is None:
            return {"found": 0, "purged": 0, "unrepliable_marked": 0, "backup": None,
                    "skipped_non404": 0, "error": "backup_failed"}

    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        rows = find_failed_parent404(conn)
        unrepliable_marked = 0
        purged = 0
        for row_id, payload_json, _retry_attempt, last_error in rows:
            if not apply:
                continue
            payload = {}
            try:
                payload = json.loads(payload_json or "{}")
            except (json.JSONDecodeError, ValueError):
                pass
            post_id = str(payload.get("post_id") or "")
            parent_comment_id = payload.get("parent_comment_id")
            if post_id and parent_comment_id:
                if reply_cap.mark_unrepliable_comment(f"{post_id}:{parent_comment_id}"):
                    unrepliable_marked += 1
            conn.execute(
                "UPDATE outbox SET status = 'discarded', last_error = ?, updated_at = datetime('now') WHERE id = ?",
                (f"purged: {last_error}", row_id),
            )
            purged += 1
        if apply and purged:
            conn.commit()
        return {
            "found": len(rows),
            "purged": purged,
            "unrepliable_marked": unrepliable_marked,
            "backup": backup,
            "skipped_non404": 0,
        }
    finally:
        conn.close()


def report(result: Dict[str, object]) -> None:
    print(f"[PURGE] Entradas failed con 404 de padre inexistente: {result['found']}")
    print(f"[PURGE] Purged (status -> 'discarded'): {result['purged']}")
    print(f"[PURGE] Comment ids marcados unrepliable: {result['unrepliable_marked']}")
    if result.get("backup"):
        print(f"[PURGE] Backup: {result['backup']}")
    if result.get("error"):
        print(f"[PURGE] ERROR: {result['error']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="ejecuta la purga (por defecto: dry-run)")
    args = parser.parse_args()

    result = purge_failed_parent404(apply=args.apply)
    report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
