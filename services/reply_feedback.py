# -*- coding: utf-8 -*-
"""
Reply Feedback Loop — consume dual_scores.jsonl to inform reply strategy.

Reads historical scores, identifies which content_types generate the highest
engagement, and produces a strategy hint for Phase B prompt construction.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("services.reply_feedback")

DUAL_SCORE_LOG = Path("data/dual_scores.jsonl")
STRATEGY_HINT_FILE = Path("data/reply_strategy_hint.json")


def _load_recent_scores(days: int = 7) -> List[Dict]:
    """Load dual scores from the last N days."""
    if not DUAL_SCORE_LOG.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    scores = []
    try:
        with open(DUAL_SCORE_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    ts = record.get("timestamp", "")
                    if ts:
                        ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if ts_dt >= cutoff:
                            scores.append(record)
                except (json.JSONDecodeError, ValueError):
                    continue
    except Exception as e:
        logger.warning("Failed to load dual scores: %s", e)
    return scores


def compute_strategy_hint(days: int = 7) -> Dict[str, Any]:
    """Analyze recent scores and produce a strategy hint.

    Returns a dict like:
    {
        "best_types": ["empirical_finding", "critique_with_alternative"],
        "worst_types": ["agreement", "repetition"],
        "avg_engagement_by_type": {...},
        "recommendation": "Focus on empirical findings and critiques.",
        "sample_size": 42,
        "computed_at": "2026-06-25T..."
    }
    """
    scores = _load_recent_scores(days)

    if len(scores) < 5:
        return {
            "best_types": [],
            "worst_types": [],
            "avg_engagement_by_type": {},
            "recommendation": "Insufficient data (need at least 5 scored replies).",
            "sample_size": len(scores),
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    # Group by content_type
    by_type: Dict[str, List[float]] = defaultdict(list)
    for s in scores:
        ctype = s.get("type", "clarification")
        composite = s.get("composite", 0.0)
        by_type[ctype].append(composite)

    # Compute averages
    avg_by_type = {
        ctype: round(sum(vals) / len(vals), 4)
        for ctype, vals in by_type.items()
        if vals
    }

    # Sort by average composite score
    sorted_types = sorted(avg_by_type.items(), key=lambda x: x[1], reverse=True)
    best_types = [t[0] for t in sorted_types[:2]] if len(sorted_types) >= 2 else [t[0] for t in sorted_types]
    worst_types = [t[0] for t in sorted_types[-2:]] if len(sorted_types) >= 3 else []

    # Generate recommendation text
    if best_types:
        best_labels = ", ".join(best_types).replace("_", " ")
        recommendation = f"Focus on {best_labels}. These types scored highest in the last {days} days."
    else:
        recommendation = "No clear pattern yet. Continue diversifying reply types."

    if worst_types:
        worst_labels = ", ".join(worst_types).replace("_", " ")
        recommendation += f" Avoid {worst_labels} (lowest engagement)."

    hint = {
        "best_types": best_types,
        "worst_types": worst_types,
        "avg_engagement_by_type": avg_by_type,
        "recommendation": recommendation,
        "sample_size": len(scores),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }

    # Persist hint for Phase B to read
    try:
        STRATEGY_HINT_FILE.parent.mkdir(parents=True, exist_ok=True)
        STRATEGY_HINT_FILE.write_text(
            json.dumps(hint, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("Failed to write strategy hint: %s", e)

    return hint


def get_strategy_hint() -> Optional[Dict]:
    """Read the latest strategy hint (written by compute_strategy_hint)."""
    if not STRATEGY_HINT_FILE.exists():
        return None
    try:
        return json.loads(STRATEGY_HINT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_strategy_prompt_injection() -> str:
    """Return a string to inject into the reply system prompt based on feedback data.

    If no data or insufficient data, returns empty string (no effect on prompt).
    """
    hint = get_strategy_hint()
    if not hint or hint.get("sample_size", 0) < 5:
        return ""

    best = hint.get("best_types", [])
    worst = hint.get("worst_types", [])
    lines = []

    if best:
        best_labels = ", ".join(t.replace("_", " ") for t in best)
        lines.append(f"STRATEGY NOTE: Your highest-performing reply types are: {best_labels}. Lean into these.")

    if worst:
        worst_labels = ", ".join(t.replace("_", " ") for t in worst)
        lines.append(f"Avoid: {worst_labels} (low engagement in recent data).")

    return "\n".join(lines)
