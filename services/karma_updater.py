# services/karma_updater.py
"""Actualiza upvotes/karma reales desde Moltbook para el tracker ROI.

Camino B (P-079): este modulo ya NO reescribe el JSONL completo. Delega la
escritura al modulo canonico services.karma_roi_tracker.update_karma(), que
es la fuente de verdad (SQLite).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict

from services.karma_roi_tracker import update_karma as _canonical_update_karma

logger = logging.getLogger("services.karma_updater")

STATE_PATH = Path("data/karma_updater_last_run.json")
DEFAULT_INTERVAL_HOURS = float(os.getenv("KARMA_UPDATER_INTERVAL_HOURS", "6"))
KARMA_FETCH_MAX_PAGES = int(os.getenv("KARMA_FETCH_MAX_PAGES", "50"))


def _upvotes(d: Dict[str, Any]) -> int:
    for k in ("upvotes", "score", "karma", "upvote_count", "points", "votes", "net_votes"):
        v = d.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def load_tracker_entries(hours: int = 24) -> list:
    """Carga acciones recientes desde SQLite (ADR-004, P-083).

    El JSONL espejo fue retirado; SQLite es la unica fuente de verdad.
    """
    from services.karma_roi_tracker import load_recent_entries
    return load_recent_entries(hours=hours)


def update_karma_from_moltbook(moltbook_client, entry: dict) -> dict:
    """Obtiene upvotes y comentarios reales para una entry (post o comment).

    Devuelve {"upvotes": int, "comments": int, "success": bool}.
    """
    kind = entry.get("type")
    mid = entry.get("moltbook_id")
    if not mid:
        return {"upvotes": 0, "comments": 0, "success": False}

    try:
        if kind == "comment":
            thread = entry.get("thread_id")
            if not thread:
                return {"upvotes": 0, "comments": 0, "success": False}
            comments = moltbook_client.fetch_post_comments(
                thread, paginate=True, max_pages=KARMA_FETCH_MAX_PAGES
            ) or []
            target = next((c for c in comments if c.get("id") == mid), None)
            if target is None:
                return {"upvotes": 0, "comments": 0, "success": False}
            return {
                "upvotes": _upvotes(target),
                "comments": int(target.get("reply_count") or 0),
                "success": True,
            }
        if kind == "post":
            post = moltbook_client.get_post(mid)
            if post is None:
                return {"upvotes": 0, "comments": 0, "success": False}
            return {
                "upvotes": _upvotes(post),
                "comments": int(post.get("comment_count") or 0),
                "success": True,
            }
    except Exception as e:
        logger.debug("Error obteniendo karma para %s: %s", mid, e)
    return {"upvotes": 0, "comments": 0, "success": False}


def update_all_karma(moltbook_client, hours: int = 24) -> dict:
    """Actualiza karma de acciones recientes. Delega la escritura al canonico."""
    entries = load_tracker_entries(hours=hours)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()

    updated = 0
    failed = 0
    skipped = 0

    for entry in entries:
        try:
            entry_ts = datetime.fromisoformat(
                entry["generated_at"].replace("Z", "+00:00")
            ).timestamp()
        except Exception:
            skipped += 1
            continue

        if entry_ts < cutoff:
            skipped += 1
            continue

        result = update_karma_from_moltbook(moltbook_client, entry)
        if result["success"]:
            _canonical_update_karma(
                entry["moltbook_id"], result["upvotes"], result["comments"]
            )
            updated += 1
        else:
            failed += 1

    return {"updated": updated, "failed": failed, "skipped_window": skipped, "total": len(entries)}


def _load_last_run() -> float:
    try:
        if STATE_PATH.exists():
            data = json.loads(STATE_PATH.read_bytes().decode("utf-8"))
            return float(data.get("last_run", 0.0))
    except Exception:
        pass
    return 0.0


def _save_last_run(epoch: float) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_bytes(json.dumps({"last_run": epoch}).encode("utf-8"))
    except Exception as e:
        logger.warning("karma_updater: no se pudo guardar estado: %s", e)


def update_all_karma_guarded(
    moltbook_client,
    hours: int = 24,
    interval_hours: float = DEFAULT_INTERVAL_HOURS,
    respect_interval: bool = True,
) -> dict:
    """Wrapper con guard de frecuencia (patron refresh_topic_performance_guarded)."""
    if respect_interval:
        last = _load_last_run()
        if last > 0.0:
            elapsed = (time.time() - last) / 3600.0
            if elapsed < interval_hours:
                logger.debug(
                    "karma_updater: skipped (%.1fh < %.1fh)", elapsed, interval_hours
                )
                return {"skipped": True, "updated": 0, "failed": 0}

    result = update_all_karma(moltbook_client, hours=hours)
    _save_last_run(time.time())
    return {"skipped": False, **result}


if __name__ == "__main__":
    print("Karma Updater: requiere moltbook_client para funcionar")
