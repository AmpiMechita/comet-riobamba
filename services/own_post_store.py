# -*- coding: utf-8 -*-
"""
Durable store for own-post IDs with fallback resolution.

Sources (in order of preference):
  1. data/published_posts.json   — full records written by Phase A on publish
  2. data/own_post_ids.json      — lightweight secondary store (always kept in sync)

Both are written atomically so the agent can always discover its own posts
even if one file is missing or corrupted.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def _is_valid_post_id(post_id: str) -> bool:
    return bool(UUID_RE.match(post_id))


def is_valid_post_id(post_id: str) -> bool:
    return _is_valid_post_id(post_id)

PUBLISHED_LOG_PATH = Path("data/published_posts.json")
OWN_POST_IDS_PATH = Path("data/own_post_ids.json")


# ── Public API ───────────────────────────────────────────────────

def load_all_own_post_ids() -> List[str]:
    """Return the complete registered set of own post IDs (no recency cap)."""
    return _load_own_post_ids()


def load_own_posts(limit: int = 10) -> List[Dict[str, Any]]:
    """Return recent own posts from the best available source.
    Each dict has at least an 'id' key.
    """
    posts = _load_published_log()
    if posts:
        logger.info("own_post_store: %d posts from published_posts.json", len(posts))
        # Normalize post_id → id for downstream consumers (fetch_my_posts)
        normalized = []
        for p in posts[-limit:]:
            normalized.append({
                "id": p["post_id"],
                "topic": p.get("topic", ""),
            })
        return normalized

    ids = _load_own_post_ids()
    if ids:
        logger.info("own_post_store: %d posts from own_post_ids.json (fallback)", len(ids))
        return [{"id": pid} for pid in ids[-limit:]]

    logger.info("own_post_store: no own-post sources found")
    return []


def register_post(post_id: str, topic: str = "", body: str = "") -> None:
    """Persist a post ID to all stores for redundancy."""
    if not _is_valid_post_id(post_id):
        logger.warning("own_post_store: rejected invalid post_id=%r (not a UUID) — ignoring", post_id)
        return
    _append_to_published_log(post_id, topic, body)
    _append_to_own_post_ids(post_id)


def count_posts_since(days: int) -> int:
    """Cuenta posts publicados con published_at dentro de los ultimos `days` dias.
    Usa published_posts.json (tiene timestamp real por post via register_post)."""
    posts = _load_published_log()
    if not posts:
        return 0
    cutoff = datetime.now() - timedelta(days=days)
    count = 0
    for p in posts:
        ts_raw = p.get("published_at")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(ts_raw)
        except Exception:
            continue
        if ts >= cutoff:
            count += 1
    return count


# ── Internal: published_posts.json ───────────────────────────────

def _load_published_log() -> List[Dict[str, Any]]:
    if not PUBLISHED_LOG_PATH.exists():
        return []
    try:
        data = json.loads(PUBLISHED_LOG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            result = []
            for p in data:
                pid = p.get("post_id")
                if pid and _is_valid_post_id(str(pid).strip()):
                    result.append(p)
                elif pid:
                    logger.debug("own_post_store: skipping invalid post_id=%r in published log", str(pid).strip())
            return result
        return []
    except Exception as e:
        logger.warning("own_post_store: error reading %s: %s", PUBLISHED_LOG_PATH, e)
        return []


def _append_to_published_log(post_id: str, topic: str, body: str = "") -> None:
    try:
        PUBLISHED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        history = _load_published_log()
        for p in history:
            if p.get("post_id") == post_id:
                if topic and not p.get("topic"):
                    p["topic"] = topic
                return  # ya registrado: no duplicar (evita inflar count_posts_since)
        record = {
            "post_id": post_id,
            "topic": topic,
            "published_at": datetime.now().isoformat(),
        }
        if body:
            record["body"] = body[:2000]  # Cap at 2000 chars
        history.append(record)
        from utils.file_helpers import write_json_atomic
        write_json_atomic(PUBLISHED_LOG_PATH, history, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning("own_post_store: error writing %s: %s", PUBLISHED_LOG_PATH, e)


# ── Internal: own_post_ids.json (lightweight fallback) ───────────

def _load_own_post_ids() -> List[str]:
    if not OWN_POST_IDS_PATH.exists():
        return []
    try:
        data = json.loads(OWN_POST_IDS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            ids = data.get("post_ids", [])
        elif isinstance(data, list):
            ids = data
        else:
            ids = []
        result = []
        for pid in ids:
            pid_str = str(pid).strip()
            if _is_valid_post_id(pid_str):
                result.append(pid_str)
            else:
                logger.debug("own_post_store: skipping invalid post_id=%r (not a UUID)", pid_str)
        return result
    except Exception as e:
        logger.warning("own_post_store: error reading %s: %s", OWN_POST_IDS_PATH, e)
        return []


def _append_to_own_post_ids(post_id: str) -> None:
    try:
        OWN_POST_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        ids = _load_own_post_ids()
        if post_id not in ids:
            ids.append(post_id)
        from utils.file_helpers import write_json_atomic
        write_json_atomic(OWN_POST_IDS_PATH, {"post_ids": ids}, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning("own_post_store: error writing %s: %s", OWN_POST_IDS_PATH, e)
