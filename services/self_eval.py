# -*- coding: utf-8 -*-
import json
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict

STATE_PATH = Path("data/self_eval_state.json")


def _today_key() -> str:
    today = datetime.now(UTC).date()
    return today.isoformat()


def load_state() -> Dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    return {}


def save_state(state: Dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8-sig")


def get_today_metrics() -> Dict:
    state = load_state()
    day = _today_key()
    return state.get(
        day,
        {
            "posts_published": 0,
            "comments_published": 0,
            "replies_received": 0,
            "spam_flags": 0,
            "upvotes_today": 0,
            "follows_today": 0,
            "semantic_searches_today": 0,
            "home_reads_today": 0,
        },
    )


def update_today_metrics(**kwargs) -> Dict:
    state = load_state()
    day = _today_key()
    metrics = get_today_metrics()

    for k, v in kwargs.items():
        if k in metrics:
            metrics[k] = metrics.get(k, 0) + int(v)

    state[day] = metrics
    save_state(state)
    return metrics


def compute_today_score() -> Dict:
    m = get_today_metrics()
    # Pesos simples; se pueden ajustar más adelante
    a = 1.0  # peso para comentarios hechos
    b = 2.0  # peso para respuestas recibidas
    c = 3.0  # penalización por spam

    score = (
        a * m.get("comments_published", 0)
        + b * m.get("replies_received", 0)
        - c * m.get("spam_flags", 0)
    )

    return {
        "metrics": m,
        "score": score,
    }
