# -*- coding: utf-8 -*-
"""Tracker de agentes top en Moltbook para benchmarking."""
import requests
import os
import sys
from pathlib import Path
from typing import List, Dict

# P-048: bootstrap para ejecutar directo (python services/top_agents_tracker.py)
# o como modulo (python -m services.top_agents_tracker) desde la raiz del repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _get_moltbook_api_key() -> str:
    """Lee MOLTBOOK_API_KEY via wrapper unificado (P-048): DPAPI -> keyring -> env."""
    from config.credentials import _get_secret
    return _get_secret("moltbook_api_key", "")

MOLTBOOK_BASE_URL = os.getenv("MOLTBOOK_BASE_URL", "https://www.moltbook.com/api/v1")
MOLTBOOK_API_KEY = _get_moltbook_api_key()

def get_top_users(limit: int = 10) -> List[Dict]:
    """Obtiene top usuarios por karma."""
    headers = {"Authorization": f"Bearer {MOLTBOOK_API_KEY}"}
    try:
        r = requests.get(f"{MOLTBOOK_BASE_URL}/users/top?limit={limit}", headers=headers, timeout=10)
        if r.ok:
            return r.json().get("users", [])
    except Exception as e:
        print(f"Error fetching top users: {e}")
    return []

def analyze_top_agent(user_id: str) -> Dict:
    """Analiza perfil de agente top."""
    headers = {"Authorization": f"Bearer {MOLTBOOK_API_KEY}"}
    try:
        r = requests.get(f"{MOLTBOOK_BASE_URL}/users/{user_id}", headers=headers, timeout=10)
        if r.ok:
            data = r.json()
            return {
                "user_id": user_id,
                "karma": data.get("karma", 0),
                "posts_count": data.get("posts_count", 0),
                "comments_count": data.get("comments_count", 0),
                "avg_karma_per_post": data.get("karma", 0) / max(data.get("posts_count", 1), 1),
                "avg_karma_per_comment": data.get("karma", 0) / max(data.get("comments_count", 1), 1),
            }
    except Exception as e:
        print(f"Error analyzing user {user_id}: {e}")
    return {}

def get_benchmark() -> Dict:
    """Obtiene benchmark de agentes top."""
    top_users = get_top_users(10)
    if not top_users:
        return {"error": "No top users found"}

    analyses = [analyze_top_agent(u.get("id")) for u in top_users]
    analyses = [a for a in analyses if a.get("user_id")]

    if not analyses:
        return {"error": "No analyses completed"}

    avg_karma = sum(a.get("karma", 0) for a in analyses) / len(analyses)
    avg_posts = sum(a.get("posts_count", 0) for a in analyses) / len(analyses)
    avg_comments = sum(a.get("comments_count", 0) for a in analyses) / len(analyses)

    return {
        "top_agents_count": len(analyses),
        "avg_karma": avg_karma,
        "avg_posts": avg_posts,
        "avg_comments": avg_comments,
        "avg_karma_per_post": avg_karma / max(avg_posts, 1),
        "avg_karma_per_comment": avg_karma / max(avg_comments, 1),
        "recommendation": {
            "posts_per_day": avg_posts / 30,
            "comments_per_day": avg_comments / 30,
            "target_karma_per_post": avg_karma / max(avg_posts, 1) * 1.5,
        }
    }

if __name__ == "__main__":
    benchmark = get_benchmark()
    import json
    print(json.dumps(benchmark, indent=2))
