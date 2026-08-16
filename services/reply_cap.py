# -*- coding: utf-8 -*-
"""Authoritative monotonic per-post reply counter (anti-dogpile) and durable
per-comment reply dedup (cross-session, never reply to the same comment twice).

Shared by Phase B (phases/phase_b/orchestrator.py) and Phase C
(phases/engagement/responder.py) so every reply to a post draws from the
same budget, regardless of phase; and no comment_id receives more than one
reply, even across days or restarts.

Data:
  data/replies_per_post.json         = {post_id: count}
  data/replied_comment_ids_durable.json = {comment_id: 1, ...}
Paths are read dynamically on every call so tests can reassign them.
Writes are atomic (temp file + os.replace).
The cap (AGENT_MAX_REPLIES_PER_POST, default 3) is a hard guardrail:
NOT in the auto-optimizer allowlist.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional, Set

logger = logging.getLogger("services.reply_cap")

BASE_DIR = Path(__file__).resolve().parent.parent

# Read dynamically on every call so tests can reassign it.
_REPLIES_PER_POST_PATH = BASE_DIR / "data" / "replies_per_post.json"
_REPLIED_COMMENT_IDS_PATH = BASE_DIR / "data" / "replied_comment_ids_durable.json"
# Threaded follow-ups per post (conversación viva). Separate budget from the
# anti-dogpile top-level counter above: a live threaded conversation is NOT a
# dogpile, so it draws from its own cap (AGENT_MAX_FOLLOWUPS_PER_POST).
_FOLLOWUPS_PER_POST_PATH = BASE_DIR / "data" / "followups_per_post.json"
# Techo TOTAL por post-raiz: backstop duro que acota el TOTAL de replies del
# agente en un post (top-level + follow-ups + own-post sumados). Independiente
# de los contadores de forma (que siguen siendo sub-caps). Overridable por env
# TOTAL_REPLIES_PER_POST_PATH (patron captcha) para aislar tests.
_TOTAL_REPLIES_PER_POST_PATH = Path(
    os.environ.get(
        "TOTAL_REPLIES_PER_POST_PATH",
        str(BASE_DIR / "data" / "total_replies_per_post.json"),
    )
)
# Comentarios cuyo padre fue borrado (404 "Parent comment not found" al
# responder): determinista, NUNCA se podran publicar. Namespace separado del
# dedup de respuestas para que la cola los descarte sin re-generar contenido.
_UNREPLIABLE_IDS_PATH = BASE_DIR / "data" / "unrepliable_comment_ids.json"


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


# ═══════════════════════════════════════════════════════════════════════════
# Threaded follow-up counter (per-post, separate from anti-dogpile)
# ═══════════════════════════════════════════════════════════════════════════


def get_followups_cap() -> int:
    """Per-post cap on threaded follow-ups (env-only, NOT auto-optimizable)."""
    try:
        return int(os.getenv("AGENT_MAX_FOLLOWUPS_PER_POST", "3"))
    except (TypeError, ValueError):
        return 3


def get_total_cap(is_own: bool) -> int:
    """Techo TOTAL de replies del agente por post-raiz (env-only, NOT
    auto-optimizable). Post ajeno: AGENT_MAX_TOTAL_REPLIES_PER_POST_FOREIGN
    (default 6). Post propio: AGENT_MAX_TOTAL_REPLIES_PER_POST_OWN (default 20)."""
    env_name = (
        "AGENT_MAX_TOTAL_REPLIES_PER_POST_OWN"
        if is_own
        else "AGENT_MAX_TOTAL_REPLIES_PER_POST_FOREIGN"
    )
    default = 20 if is_own else 6
    try:
        return int(os.getenv(env_name, str(default)))
    except (TypeError, ValueError):
        return default


def get_total_replies_for_post(post_id: str, path: Optional[Path] = None) -> int:
    """Contador TOTAL de replies del agente en un post (0 si no existe). Fail-open."""
    path = path or _TOTAL_REPLIES_PER_POST_PATH
    try:
        return _load(path).get(str(post_id), 0)
    except Exception as e:
        logger.debug("reply_cap: total read failed for %s: %s", post_id, e)
        return 0


def increment_total_replies_for_post(post_id: str, path: Optional[Path] = None) -> int:
    """Incrementa y persiste atomicamente el contador TOTAL. Monotonico."""
    path = path or _TOTAL_REPLIES_PER_POST_PATH
    try:
        counts = _load(path)
        key = str(post_id)
        counts[key] = counts.get(key, 0) + 1
        _save(counts, path)
        return counts[key]
    except Exception as e:
        logger.warning("reply_cap: total increment failed for %s: %s", post_id, e)
        return -1


def get_followups_for_post(post_id: str, path: Optional[Path] = None) -> int:
    """Follow-up counter value for a post (0 when missing). Fail-open."""
    path = path or _FOLLOWUPS_PER_POST_PATH
    try:
        return _load(path).get(str(post_id), 0)
    except Exception as e:
        logger.debug("reply_cap: followups read failed for %s: %s", post_id, e)
        return 0


def increment_followups_for_post(post_id: str, path: Optional[Path] = None) -> int:
    """Increment and atomically persist the follow-up counter. Never decremented."""
    path = path or _FOLLOWUPS_PER_POST_PATH
    try:
        counts = _load(path)
        key = str(post_id)
        counts[key] = counts.get(key, 0) + 1
        _save(counts, path)
        return counts[key]
    except Exception as e:
        logger.warning("reply_cap: followups increment failed for %s: %s", post_id, e)
        return -1


# ═══════════════════════════════════════════════════════════════════════════
# Durable per-comment dedup (cross-session)
# ═══════════════════════════════════════════════════════════════════════════


def _load_comment_ids(path: Optional[Path] = None) -> Set[str]:
    path = path or _REPLIED_COMMENT_IDS_PATH
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return set(str(k) for k in data.keys())
    except Exception:
        logger.warning("reply_cap: no se pudo cargar replied_comment_ids_durable")
    return set()


def _save_comment_ids(ids: Set[str], path: Optional[Path] = None) -> None:
    path = path or _REPLIED_COMMENT_IDS_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: Dict[str, int] = {str(cid): 1 for cid in ids}
        tmp_path = path.with_name(path.name + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    except Exception as e:
        logger.warning("reply_cap: no se pudo guardar replied_comment_ids: %s", e)


def has_replied_to_comment(comment_id: str, path: Optional[Path] = None) -> bool:
    """True if this comment_id has already received a reply. Fail-open."""
    if not comment_id:
        return False
    try:
        return str(comment_id) in _load_comment_ids(path)
    except Exception as e:
        logger.debug("reply_cap: dedup check failed for %s: %s", comment_id, e)
        return False


def mark_replied_to_comment(comment_id: str, path: Optional[Path] = None) -> bool:
    """Persistently mark a comment_id as replied. Atomic write. Never unmarked."""
    if not comment_id:
        return False
    try:
        ids = _load_comment_ids(path)
        ids.add(str(comment_id))
        _save_comment_ids(ids, path)
        return True
    except Exception as e:
        logger.warning("reply_cap: dedup mark failed for %s: %s", comment_id, e)
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Unrepliable comments (parent deleted — 404 deterministic)
# ═══════════════════════════════════════════════════════════════════════════


def is_unrepliable_comment(comment_id: str, path: Optional[Path] = None) -> bool:
    """True si este comment_id ya se marco como unrepliable (padre borrado:
    responder devolvio 404 'Parent comment not found'). Nunca vuelve a la cola."""
    if not comment_id:
        return False
    try:
        return str(comment_id) in _load_comment_ids(path or _UNREPLIABLE_IDS_PATH)
    except Exception as e:
        logger.debug("reply_cap: unrepliable check failed for %s: %s", comment_id, e)
        return False


def mark_unrepliable_comment(comment_id: str, path: Optional[Path] = None) -> bool:
    """Marca un comment_id como unrepliable (padre inexistente). Atomic, idempotente."""
    if not comment_id:
        return False
    try:
        ids = _load_comment_ids(path or _UNREPLIABLE_IDS_PATH)
        ids.add(str(comment_id))
        _save_comment_ids(ids, path or _UNREPLIABLE_IDS_PATH)
        return True
    except Exception as e:
        logger.warning("reply_cap: unrepliable mark failed for %s: %s", comment_id, e)
        return False
