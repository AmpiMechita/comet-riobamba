# -*- coding: utf-8 -*-
"""
Content Curator — evaluates post quality for external distribution.

Applies editorial standards to decide which posts are worth reformatting
for LinkedIn/Twitter. Acts as a quality gate between the agent's internal
Moltbook posts and external distribution channels.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("services.content_curator")


@dataclass
class CurationResult:
    """Result of evaluating a post for external distribution."""
    post_id: str
    title: str
    approved: bool
    score: float  # 0.0 to 1.0
    reasons: List[str]
    recommended_platforms: List[str]
    suggested_hook: Optional[str] = None


# Signals that a post has external value
_ACTIONABLE_SIGNALS = [
    "here's how", "the fix is", "we solved", "the pattern",
    "in practice", "the approach", "step 1", "the framework",
    "you should", "the rule is", "the lesson", "what works",
]

_METRIC_PATTERNS = [
    r'\d+%',           # percentages
    r'\d+ms',          # latencies
    r'p\d{2}',        # percentiles
    r'\d+x',          # multipliers
    r'\d+\.\d+',      # decimals
    r'\d+s\b',        # seconds
    r'\d+h\b',        # hours
]

_META_SIGNALS = [
    "my agent", "comet-riobamba", "this bot", "my system",
    "i built myself", "my workflow", "phase a", "phase b", "phase c",
]

_LINKEDIN_TOPICS = [
    "leadership", "team", "architecture", "production", "scale",
    "reliability", "observability", "cost", "capacity", "strategy",
    "resilience", "failure", "recovery", "planning", "automation",
]

_TWITTER_TOPICS = [
    "agent", "llm", "model", "tool", "prompt", "embedding",
    "circuit breaker", "cascade", "failover", "drift", "latency",
    "benchmark", "experiment", "open source", "paper",
]


def evaluate_post(post_id: str, title: str, body: str) -> CurationResult:
    """Evaluate a single post for external distribution worthiness."""
    reasons = []
    score = 0.5
    title_lower = title.lower()
    body_lower = body.lower()
    full_text = f"{title_lower} {body_lower}"

    # Length check
    if len(body) < 200:
        reasons.append("too_short")
        score -= 0.3
    elif len(body) > 500:
        score += 0.1
        reasons.append("good_length")

    # Actionable content
    actionable_count = sum(1 for s in _ACTIONABLE_SIGNALS if s in full_text)
    if actionable_count >= 2:
        score += 0.2
        reasons.append(f"actionable ({actionable_count} signals)")
    elif actionable_count == 0:
        score -= 0.1
        reasons.append("not_actionable")

    # Metrics/numbers
    metric_count = sum(1 for p in _METRIC_PATTERNS if re.search(p, body))
    if metric_count >= 2:
        score += 0.15
        reasons.append(f"has_metrics ({metric_count})")
    elif metric_count == 0:
        score -= 0.1
        reasons.append("no_metrics")

    # Meta/internal content
    if any(s in full_text for s in _META_SIGNALS):
        score -= 0.3
        reasons.append("meta_content")

    # Title quality
    if any(ord(c) > 127 for c in title):
        score -= 0.1
        reasons.append("emoji_title")
    if len(title) > 40 and any(w in title_lower for w in ["how", "why", "what", "pattern", "cost"]):
        score += 0.1
        reasons.append("strong_title")
    if len(title) < 20:
        score -= 0.1
        reasons.append("vague_title")

    # Platform fit
    platforms = []
    linkedin_fit = sum(1 for t in _LINKEDIN_TOPICS if t in full_text)
    twitter_fit = sum(1 for t in _TWITTER_TOPICS if t in full_text)
    if linkedin_fit >= 2:
        platforms.append("linkedin")
    if twitter_fit >= 2:
        platforms.append("twitter")
    if not platforms and (linkedin_fit + twitter_fit) >= 2:
        platforms.append("linkedin")

    # Generate hook
    hook = _generate_hook(title, body)

    # Final decision
    score = max(0.0, min(1.0, score))
    approved = score >= 0.6 and len(platforms) > 0 and "meta_content" not in reasons

    return CurationResult(
        post_id=post_id,
        title=title,
        approved=approved,
        score=round(score, 3),
        reasons=reasons,
        recommended_platforms=platforms,
        suggested_hook=hook,
    )


def _generate_hook(title: str, body: str) -> Optional[str]:
    """Generate a one-line hook from the post for social media."""
    sentences = re.split(r'(?<=[.!?])\s+', body)
    insight_signals = ["the real", "nobody", "most", "the hidden", "what actually", "the problem"]
    for s in sentences[:5]:
        s = s.strip()
        if len(s) > 40 and any(sig in s.lower() for sig in insight_signals):
            return s[:200]
    if sentences and len(sentences[0]) > 30:
        return sentences[0][:200]
    return None


def curate_batch(posts: List[Dict], fetch_body_fn=None) -> List[CurationResult]:
    """Evaluate a batch of posts."""
    results = []
    for post in posts:
        post_id = post.get("post_id", "")
        title = post.get("topic", "")
        body = ""
        if fetch_body_fn:
            try:
                body = fetch_body_fn(post_id) or ""
            except Exception:
                pass
        results.append(evaluate_post(post_id, title, body))
    return results


def get_approved_posts(posts: List[Dict], fetch_body_fn=None) -> List[CurationResult]:
    """Convenience: return only approved posts from a batch."""
    results = curate_batch(posts, fetch_body_fn)
    return [r for r in results if r.approved]
