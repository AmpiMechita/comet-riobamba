# -*- coding: utf-8 -*-
"""Detector de posts virales y oportunidades de karma."""
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict

VIRAL_THRESHOLD = 50  # Karma mínimo para considerar viral
HOT_WINDOW_HOURS = 2  # Ventana de tiempo para posts "calientes"

def analyze_post(post: Dict) -> Dict:
    """Analiza potencial viral de un post."""
    karma = post.get("karma", 0)
    comments = post.get("comments_count", 0)
    age_hours = post.get("age_hours", 24)

    # Score de viralidad
    viral_score = karma / max(age_hours, 1) + comments * 2
    is_viral = karma >= VIRAL_THRESHOLD and age_hours <= HOT_WINDOW_HOURS
    is_hot = age_hours <= HOT_WINDOW_HOURS and karma >= 10

    return {
        "post_id": post.get("id"),
        "karma": karma,
        "comments": comments,
        "age_hours": age_hours,
        "viral_score": viral_score,
        "is_viral": is_viral,
        "is_hot": is_hot,
        "recommendation": "comment" if is_hot else "skip"
    }

def get_opportunities(posts: List[Dict]) -> List[Dict]:
    """Obtiene oportunidades de karma (posts virales/calientes)."""
    analyses = [analyze_post(p) for p in posts]
    opportunities = [a for a in analyses if a.get("is_viral") or a.get("is_hot")]
    return sorted(opportunities, key=lambda x: x.get("viral_score", 0), reverse=True)

if __name__ == "__main__":
    # Test con datos dummy
    test_posts = [
        {"id": "1", "karma": 100, "comments_count": 20, "age_hours": 1},
        {"id": "2", "karma": 50, "comments_count": 10, "age_hours": 3},
        {"id": "3", "karma": 5, "comments_count": 2, "age_hours": 24},
    ]
    opps = get_opportunities(test_posts)
    print("Oportunidades de karma:")
    for o in opps:
        print(f"  Post {o['post_id']}: karma={o['karma']}, viral_score={o['viral_score']:.1f}, rec={o['recommendation']}")
