import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

HISTORY_PATH = Path("data/post_history_guard.json")


def _load_history() -> Dict:
    if HISTORY_PATH.exists():
        try:
            return json.loads(HISTORY_PATH.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    return {"posts": []}


def _save_history(state: Dict):
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8-sig")


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def register_post(title: str, submolt: str | None) -> None:
    state = _load_history()
    posts: List[Dict] = state.get("posts", [])

    posts.append(
        {
            "title": title or "",
            "submolt": submolt or "m/agents",
            "created_at": _now_iso(),
        }
    )

    # Mantener el historial acotado (por tamaño y tiempo)
    cutoff = datetime.utcnow() - timedelta(days=14)
    pruned: List[Dict] = []
    for p in posts[-500:]:
        try:
            ts = datetime.fromisoformat(p.get("created_at", "1970-01-01T00:00:00"))
        except Exception:
            ts = cutoff
        if ts >= cutoff:
            pruned.append(p)

    state["posts"] = pruned
    _save_history(state)


def can_post_in_submolt(submolt: str, max_posts: int, window_hours: int) -> bool:
    """
    True si en la ventana de 'window_hours' no se ha excedido 'max_posts'
    en esa misma submolt.
    """
    state = _load_history()
    posts: List[Dict] = state.get("posts", [])

    now = datetime.utcnow()
    window_start = now - timedelta(hours=window_hours)
    count = 0
    sub = submolt or "m/agents"

    for p in posts:
        if p.get("submolt", "m/agents") != sub:
            continue
        try:
            ts = datetime.fromisoformat(p.get("created_at", "1970-01-01T00:00:00"))
        except Exception:
            continue
        if ts >= window_start:
            count += 1

    return count < max_posts


def is_title_duplicate(title: str, days: int = 7, similarity_threshold: float = 0.8) -> bool:
    """
    Devuelve True si el título es muy similar a alguno usado en los últimos 'days' días.
    Usamos comparación simple normalizada + umbral de coincidencia.
    """
    import difflib

    if not title:
        return False

    state = _load_history()
    posts: List[Dict] = state.get("posts", [])

    cutoff = datetime.utcnow() - timedelta(days=days)
    norm_new = title.strip().lower()

    for p in posts:
        try:
            ts = datetime.fromisoformat(p.get("created_at", "1970-01-01T00:00:00"))
        except Exception:
            continue
        if ts < cutoff:
            continue

        prev_title = (p.get("title") or "").strip().lower()
        if not prev_title:
            continue

        ratio = difflib.SequenceMatcher(None, norm_new, prev_title).ratio()
        if ratio >= similarity_threshold:
            return True

    return False
