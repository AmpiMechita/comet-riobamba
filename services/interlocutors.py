# -*- coding: utf-8 -*-
"""Durable ledger of interlocutors (per-author interaction counter).

Trackea con quién hablamos, cuántas veces, y dónde. Usado para:
  1) Priorizar interlocutores recurrentes en el triage de comentarios.
  2) Registrar actividad (última interacción, on_our_posts vs in_feed).
  3) Poblá el campo user_id en value_log con el nombre del autor.

Storage: data/interlocutors.json
  = { author_name: {"count": n, "last_seen": iso,
                     "on_our_posts": n, "in_feed": n} }

Atomic writes (tmp + os.replace). Fail-open (errores → 0 / no-op).
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("services.interlocutors")

BASE_DIR = Path(__file__).resolve().parent.parent

# Read dynamically on every call so tests can reassign it.
_INTERLOCUTORS_PATH = BASE_DIR / "data" / "interlocutors.json"


# ── Author extraction helper ──────────────────────────────────

def _extract_author_name(author: Union[str, Dict[str, Any], None]) -> str:
    """Resolve author name from str or dict payload.

    Spec del usuario: 'author puede ser str o dict con name'. Tambien
    acepta los campos comunes del tracker (username, display_name, etc.)
    por compatibilidad."""
    if not author:
        return ""
    if isinstance(author, str):
        return author.strip()
    if isinstance(author, dict):
        for k in ("name", "username", "handle", "user_handle",
                  "display_name", "agent_name", "author"):
            v = author.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


# ── Load / save ────────────────────────────────────────────────

def _load(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    path = path or _INTERLOCUTORS_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            out: Dict[str, Dict[str, Any]] = {}
            for k, v in data.items():
                if not isinstance(v, dict):
                    continue
                name = str(k).strip()
                if not name:
                    continue
                out[name] = {
                    "count": int(v.get("count", 0) or 0),
                    "last_seen": str(v.get("last_seen", "") or ""),
                    "on_our_posts": int(v.get("on_our_posts", 0) or 0),
                    "in_feed": int(v.get("in_feed", 0) or 0),
                }
            return out
    except Exception:
        logger.warning("interlocutors: no se pudo cargar, iniciando vacío")
    return {}


def _save(ledger: Dict[str, Dict[str, Any]], path: Optional[Path] = None) -> None:
    path = path or _INTERLOCUTORS_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(path.name + ".tmp")
        tmp_path.write_text(
            json.dumps(ledger, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    except Exception as e:
        logger.warning("interlocutors: no se pudo guardar ledger: %s", e)


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── Public API ─────────────────────────────────────────────────

def record_interaction(author: Union[str, Dict[str, Any], None], *,
                        on_our_post: bool) -> bool:
    """Incrementa el contador del interlocutor y actualiza last_seen.

    Returns True si la interacción se registró, False si el autor
    estaba vacío o hubo un error (fail-open)."""
    name = _extract_author_name(author)
    if not name:
        return False
    try:
        ledger = _load()
        entry = ledger.get(name, {
            "count": 0, "last_seen": "",
            "on_our_posts": 0, "in_feed": 0,
        })
        entry["count"] = entry["count"] + 1
        entry["last_seen"] = _utc_now()
        if on_our_post:
            entry["on_our_posts"] = entry["on_our_posts"] + 1
        else:
            entry["in_feed"] = entry["in_feed"] + 1
        ledger[name] = entry
        _save(ledger)
        return True
    except Exception as e:
        logger.debug("interlocutors: record_interaction failed for %s: %s", name, e)
        return False


def get_interaction_count(author: Union[str, Dict[str, Any], None],
                          path: Optional[Path] = None) -> int:
    """Conteo durable de interacciones con este interlocutor. Fail-open (0)."""
    name = _extract_author_name(author)
    if not name:
        return 0
    try:
        return _load(path).get(name, {}).get("count", 0)
    except Exception as e:
        logger.debug("interlocutors: get_interaction_count failed for %s: %s", name, e)
        return 0


def top_interlocutors(n: int = 10,
                      path: Optional[Path] = None) -> List[Tuple[str, Dict[str, Any]]]:
    """Top-N interlocutores por count (desc). Lista de tuplas (name, info)."""
    try:
        ledger = _load(path)
        ranked = sorted(
            ledger.items(),
            key=lambda kv: (-int(kv[1].get("count", 0)), str(kv[0])),
        )
        return ranked[:max(0, int(n))]
    except Exception as e:
        logger.debug("interlocutors: top_interlocutors failed: %s", e)
        return []
