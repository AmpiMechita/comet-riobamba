"""Trend watcher: feed scan, keyword clustering, agenda proposal.

Extracts keywords from post titles, clusters posts by shared keywords,
scores clusters by engagement (likes + comments), and proposes top N
clusters as research agenda topics with source="phase_c_trend".
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "this", "that", "these", "those", "and", "or", "but", "if",
    "because", "as", "until", "while", "of", "at", "by", "for", "with",
    "about", "against", "between", "into", "through", "during", "before",
    "after", "above", "below", "from", "up", "down", "in", "out", "on",
    "off", "over", "under", "again", "further", "then", "once", "here",
    "there", "when", "where", "why", "how", "all", "each", "every",
    "both", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "also", "now",
})


def extract_keywords(title: str, max_keywords: int = 3) -> List[str]:
    """Extract 2-3 keywords from a post title using stdlib only."""
    words = title.lower().split()
    keywords = [w for w in words if w not in STOPWORDS and len(w) > 3]
    seen = set()
    result = []
    for w in keywords:
        if w not in seen:
            seen.add(w)
            result.append(w)
    return result[:max_keywords]


def cluster_posts(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group posts by shared keywords. Returns list of cluster dicts
    sorted by cluster_score descending, each containing:
    {keyword, posts, score, post_count}.
    """
    clusters: Dict[str, Dict] = {}
    for post in posts:
        title = str(post.get("title") or "").strip()
        if not title:
            continue
        kws = extract_keywords(title)
        score_val = int(post.get("score") or post.get("likes") or 0) + int(post.get("comments_count") or 0)
        for kw in kws:
            if kw not in clusters:
                clusters[kw] = {"keyword": kw, "posts": [], "score": 0}
            clusters[kw]["posts"].append(post)
            clusters[kw]["score"] += score_val

    result = []
    for c in clusters.values():
        c["post_count"] = len(c["posts"])
        result.append(c)
    result.sort(key=lambda c: (-c["score"], -c["post_count"]))
    return result


def run_trend_watcher(
    api: Any,
    agenda: Any,
    feed_size: int = 50,
    top_n: int = 2,
    trends_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run one cycle of the trend watcher.

    Args:
        api: Moltbook API client with fetch_posts(limit) -> List[Dict].
        agenda: ResearchAgenda instance (from services.research_agenda).
        feed_size: Max posts to fetch (env TREND_WATCHER_FEED_SIZE).
        top_n: Number of top clusters to propose (env TREND_WATCHER_TOP_N).
        trends_path: Path for analytics_trends.jsonl output.

    Returns:
        {"posts_scanned": int, "clusters_found": int,
         "topics_proposed": int, "top_clusters": list, "posts": list}
    """
    try:
        posts = api.fetch_posts(limit=feed_size)
    except Exception as e:
        logger.warning("Phase C trend watcher: get_feed failed: %s", e)
        return {"posts_scanned": 0, "clusters_found": 0, "topics_proposed": 0, "top_clusters": [], "posts": []}

    if not posts:
        logger.warning("Phase C trend watcher: get_feed returned empty")
        return {"posts_scanned": 0, "clusters_found": 0, "topics_proposed": 0, "top_clusters": [], "posts": []}

    clusters = cluster_posts(posts)
    clusters_found = len(clusters)
    topics_proposed = 0
    top_clusters = clusters[:top_n]

    for c in top_clusters:
        top_keyword = c["keyword"]
        existing = {t["topic"] for t in agenda.pending_topics}
        if top_keyword in existing:
            logger.debug("Phase C trend watcher: keyword '%s' already in agenda, skipping", top_keyword)
            continue
        title = f"Trending: {top_keyword} — {c['post_count']} posts, score {c['score']}"
        agenda.add_topic(
            top_keyword,
            source="phase_c_trend",
            tags=list({kw for post in c["posts"] for kw in extract_keywords(str(post.get("title") or ""))}),
        )
        topics_proposed += 1
        logger.debug("Phase C trend watcher: proposed topic '%s' (score %d)", top_keyword, c["score"])

    logger.info(
        "Phase C trend watcher: scanned %d posts, found %d clusters, proposed %d new agenda topics.",
        len(posts), clusters_found, topics_proposed,
    )

    # Write analytics_trends.jsonl
    if trends_path is None:
        trends_path = Path("data/analytics_trends.jsonl")
    trends_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now().isoformat(),
        "posts_scanned": len(posts),
        "clusters_found": clusters_found,
        "topics_proposed": topics_proposed,
        "top_clusters": [
            {"keyword": c["keyword"], "score": c["score"], "post_count": c["post_count"]}
            for c in top_clusters
        ],
    }
    with open(trends_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {
        "posts_scanned": len(posts),
        "clusters_found": clusters_found,
        "topics_proposed": topics_proposed,
        "top_clusters": top_clusters,
        "posts": posts,
    }
