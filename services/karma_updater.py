# services/karma_updater.py
"""
Actualiza automáticamente los upvotes/karma de posts y comments desde Moltbook API.
"""

import json
import os
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("services.karma_updater")

KARMA_TRACKER_FILE = Path("data/karma_roi_tracker.jsonl")


def load_tracker_entries() -> list:
    """Carga todas las entradas del tracker."""
    entries = []
    if KARMA_TRACKER_FILE.exists():
        with open(KARMA_TRACKER_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
    return entries


def save_tracker_entries(entries: list) -> None:
    """Guarda todas las entradas del tracker."""
    with open(KARMA_TRACKER_FILE, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def update_karma_from_moltbook(moltbook_client, moltbook_id: str) -> dict:
    """
    Obtiene upvotes y comentarios de un post/comment desde Moltbook API.
    Retorna dict con upvotes y comments_count.
    """
    try:
        # Intentar obtener info del post/comment
        # Ajustar según la API real de Moltbook
        info = moltbook_client.get_post_info(moltbook_id)  # o get_comment_info
        
        return {
            "upvotes": info.get("upvotes", 0),
            "comments": info.get("comments_count", 0),
            "success": True
        }
    except Exception as e:
        logger.debug("Error obteniendo karma para %s: %s", moltbook_id, e)
        return {
            "upvotes": 0,
            "comments": 0,
            "success": False
        }


def update_all_karma(moltbook_client, hours: int = 24) -> dict:
    """
    Actualiza karma de todas las acciones creadas en las últimas `hours` horas.
    Retorna estadísticas de actualización.
    """
    entries = load_tracker_entries()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
    
    updated = 0
    failed = 0
    skipped = 0
    
    for entry in entries:
        entry_ts = datetime.fromisoformat(entry["generated_at"].replace("Z", "+00:00")).timestamp()
        
        # Solo actualizar acciones recientes
        if entry_ts < cutoff:
            skipped += 1
            continue
        
        # Obtener karma actualizado
        result = update_karma_from_moltbook(moltbook_client, entry["moltbook_id"])
        
        if result["success"]:
            entry["upvotes_24h"] = result["upvotes"]
            entry["karma_score"] = result["upvotes"]  # karma = upvotes × 1.0
            entry["comments_received"] = result["comments"]
            entry["last_updated"] = datetime.now(timezone.utc).isoformat()
            updated += 1
        else:
            failed += 1
    
    save_tracker_entries(entries)
    
    return {
        "updated": updated,
        "failed": failed,
        "skipped": skipped,
        "total": len(entries)
    }


if __name__ == "__main__":
    # Test rápido
    print("Karma Updater: requiere moltbook_client para funcionar")
