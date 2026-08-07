# -*- coding: utf-8 -*-
"""Authoritative monotonic per-post reply counter (anti-dogpile).

Shared by Phase B (phases/phase_b/orchestrator.py) and Phase C
(phases/engagement/responder.py) so every reply to a post draws from the
same budget, regardless of phase.

Data: data/replies_per_post.json = {post_id: count}. The path is read
dynamically on every call so tests can reassign it. Writes are atomic
(temp file + os.replace). The cap (AGENT_MAX_REPLIES_PER_POST, default 3)
is a hard guardrail: NOT in the auto-optimizer allowlist.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("services.reply_cap")

BASE_DIR = Path(__file__).resolve().parent.parent

# Read dynamically on every call so tests can reassign it.
_REPLIES_PER_POST_PATH = BASE_DIR / "data" / "replies_per_post.json"


def get_cap() -> int:
    """Hard per-post reply cap (env-only, NOT auto-optimizable)."""
    try:
        return int(os.getenv("AGENT_MAX_REPLIES_PER_POST", "3"))
    except (TypeError, ValueError):
        return 3


def _load(path: Optional[Path] = None) -> Dict[str, int]:
    path = path or _REPLIES_PER_POST_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            out: Dict[str, int] = {}
            for k, v in data.items():
                try:
                    out[str(k)] = int(v)
                except (TypeError, ValueError):
                    continue
            return out
    except Exception:
        logger.warning("reply_cap: no se pudo cargar replies_per_post, iniciando vacío")
    return {}


def _save(counts: Dict[str, int], path: Optional[Path] = None) -> None:
    """Persist the counter atomically (temp file + os.replace)."""
    path = path or _REPLIES_PER_POST_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(path.name + ".tmp")
        tmp_path.write_text(
            json.dumps(counts, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    except Exception as e:
        logger.warning("reply_cap: no se pudo guardar replies_per_post: %s", e)


def get_replies_for_post(post_id: str, path: Optional[Path] = None) -> int:
    """Monotonic counter value for a post (0 when missing). Fail-open."""
    try:
        return _load(path).get(str(post_id), 0)
    except Exception as e:
        logger.debug("reply_cap: read failed for %s: %s", post_id, e)
        return 0


def increment_replies_for_post(post_id: str, path: Optional[Path] = None) -> int:
    """Increment and atomically persist the counter. Never decremented."""
    try:
        counts = _load(path)
        key = str(post_id)
        counts[key] = counts.get(key, 0) + 1
        _save(counts, path)
        return counts[key]
    except Exception as e:
        logger.warning("reply_cap: increment failed for %s: %s", post_id, e)
        return -1
