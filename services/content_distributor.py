# -*- coding: utf-8 -*-
"""
Content Distributor — selects best daily content and triggers repurposing.

Runs once per day (from Phase C). Selects the top posts by engagement potential,
feeds them to comet_repurposer pipeline, and enqueues for LinkedIn/Twitter.
"""

import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("services.content_distributor")

STATE_FILE = Path("data/content_distributor_state.json")
PUBLISHED_POSTS_FILE = Path("data/published_posts.json")


def should_run_distribution() -> bool:
    """True if distribution hasn't run in the last 20 hours."""
    if not STATE_FILE.exists():
        return True
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        last = datetime.fromisoformat(data["last_run"])
        now = datetime.now(timezone.utc)
        return (now - last).total_seconds() > 72000  # 20h
    except Exception:
        return True


def _get_recent_posts(hours: int = 24) -> List[Dict]:
    """Load posts published in the last N hours."""
    if not PUBLISHED_POSTS_FILE.exists():
        return []
    try:
        posts = json.loads(PUBLISHED_POSTS_FILE.read_text(encoding="utf-8"))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent = []
        for p in posts:
            pub_at = p.get("published_at", "")
            try:
                dt = datetime.fromisoformat(pub_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= cutoff:
                    recent.append(p)
            except (ValueError, TypeError):
                continue
        return recent
    except Exception as e:
        logger.warning("content_distributor: failed to load posts: %s", e)
        return []


def _score_post_for_distribution(post: Dict) -> float:
    """Score a post for external distribution potential."""
    title = post.get("topic", "")
    score = 0.5

    if any(ord(c) > 127 for c in title):
        score -= 0.2

    vague_signals = ["neural persistence", "silicon archive", "system analogies", "communication layer"]
    if any(v in title.lower() for v in vague_signals):
        score -= 0.3

    good_signals = [
        "how", "why", "pattern", "framework", "production", "cost",
        "strategy", "resilience", "observability", "capacity", "error",
        "failure", "scaling", "architecture", "agent",
    ]
    matches = sum(1 for s in good_signals if s in title.lower())
    score += min(0.4, matches * 0.1)

    if len(title) > 40:
        score += 0.1

    return max(0.0, min(1.0, score))


def select_best_posts(top_n: int = 3) -> List[Dict]:
    """Select the best N posts from the last 24h for distribution (with curation)."""
    recent = _get_recent_posts(hours=24)
    if not recent:
        return []

    # Try content curation if available
    try:
        from services.content_curator import curate_batch

        def _fetch_body(post_id: str) -> str:
            for p in recent:
                if p.get("post_id") == post_id:
                    return p.get("body", "")
            return ""

        results = curate_batch(recent, fetch_body_fn=_fetch_body)
        approved = [(r, p) for r, p in zip(results, recent) if r.approved]
        approved.sort(key=lambda x: x[0].score, reverse=True)
        selected = [p for _, p in approved[:top_n]]
        if selected:
            logger.info(
                "content_distributor: %d/%d posts approved by curator (scores: %s)",
                len(selected), len(recent),
                [f"{r.score:.2f}" for r, _ in approved[:top_n]],
            )
            return selected
    except ImportError:
        pass
    except Exception as e:
        logger.warning("content_distributor: curator failed, using title scoring: %s", e)

    # Fallback to title-only scoring
    scored = [(p, _score_post_for_distribution(p)) for p in recent]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [p for p, s in scored[:top_n] if s > 0.5]


def run_distribution() -> Dict:
    """Main entry point: select best posts and trigger repurposer."""
    if not should_run_distribution():
        return {"selected": 0, "enqueued": 0, "skipped": True}

    posts = select_best_posts(top_n=3)
    if not posts:
        logger.info("content_distributor: no posts qualify for distribution")
        _save_state()
        return {"selected": 0, "enqueued": 0, "errors": []}

    logger.info("content_distributor: %d posts selected for distribution", len(posts))

    # Write selected posts for the repurposer
    selection_file = Path("data/distribution_queue.json")
    selection_file.parent.mkdir(parents=True, exist_ok=True)
    selection_file.write_text(
        json.dumps({
            "selected_at": datetime.now(timezone.utc).isoformat(),
            "posts": posts,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Try to run the repurposer pipeline
    errors = []
    enqueued = 0
    repurposer_path = Path("scripts/comet_repurposer")
    if repurposer_path.exists():
        try:
            project_root = Path(__file__).resolve().parents[1]
            result = subprocess.run(
                [sys.executable, "-m", "comet_repurposer", "generate",
                 "--source", "distribution_queue",
                 "--platforms", "linkedin,twitter",
                 "--project-root", str(project_root),
                 "--limit", str(len(posts))],
                cwd=str(repurposer_path),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                enqueued = len(posts)
                logger.info("content_distributor: repurposer generated %d drafts", enqueued)
            else:
                errors.append(f"repurposer exit code {result.returncode}: {result.stderr[:200]}")
                logger.warning("content_distributor: repurposer failed: %s", result.stderr[:200])
        except subprocess.TimeoutExpired:
            errors.append("repurposer timed out (120s)")
        except Exception as e:
            errors.append(str(e))
            logger.warning("content_distributor: repurposer error: %s", e)
    else:
        logger.info("content_distributor: repurposer not found, posts saved to distribution_queue.json")
        enqueued = len(posts)

    _save_state()
    return {"selected": len(posts), "enqueued": enqueued, "errors": errors}


def _save_state() -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"last_run": datetime.now(timezone.utc).isoformat()}),
        encoding="utf-8",
    )
