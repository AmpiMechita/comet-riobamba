# -*- coding: utf-8 -*-
"""
Topic Evolution Engine — transforms mature claims into post series.

Reads claims from ClaimsTracker, identifies those ready to evolve,
and generates topic proposals for Phase A that deepen rather than repeat.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("services.topic_evolution")

EVOLUTION_STATE_FILE = Path("data/topic_evolution_state.json")

# A claim is "mature" when it has been reinforced at least this many times
MATURITY_THRESHOLD = 3

# Maximum active series at once
MAX_ACTIVE_SERIES = 3


@dataclass
class SeriesEntry:
    """A single post in an evolution series."""
    title: str
    angle: str  # The specific angle/depth for this post
    status: str = "planned"  # planned, published, skipped
    published_at: Optional[str] = None
    post_id: Optional[str] = None


@dataclass
class TopicSeries:
    """A multi-post series that deepens a mature claim."""
    id: str
    source_claim_text: str
    source_claim_id: str
    topic_cluster: str
    created_at: str
    status: str = "active"  # active, completed, abandoned
    entries: List[SeriesEntry] = field(default_factory=list)


def _load_state() -> Dict:
    if not EVOLUTION_STATE_FILE.exists():
        return {"series": [], "last_computed": None}
    try:
        return json.loads(EVOLUTION_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"series": [], "last_computed": None}


def _save_state(state: Dict) -> None:
    EVOLUTION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    EVOLUTION_STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _generate_series_entries(claim_text: str, topic_cluster: str) -> List[SeriesEntry]:
    """Generate a 3-post evolution series from a mature claim.

    The series deepens progressively:
    1. Foundation: restate the claim with concrete evidence
    2. Stress-test: explore edge cases, failure modes, counter-examples
    3. Synthesis: propose a framework, metric, or design pattern
    """
    short_claim = claim_text[:60] + "..." if len(claim_text) > 60 else claim_text
    return [
        SeriesEntry(
            title=f"Evidence for: {short_claim}",
            angle="foundation",
        ),
        SeriesEntry(
            title=f"When does this break? Edge cases of: {short_claim}",
            angle="stress_test",
        ),
        SeriesEntry(
            title=f"A framework from: {short_claim}",
            angle="synthesis",
        ),
    ]


def identify_mature_claims(claims_tracker) -> List[Dict]:
    """Find claims that have been reinforced enough to warrant a series.

    Args:
        claims_tracker: ClaimsTracker instance with _claims attribute.

    Returns:
        List of claim dicts ready for evolution.
    """
    mature = []
    claims = getattr(claims_tracker, "_claims", [])
    for claim in claims:
        reinforcement = getattr(claim, "reinforcement_count", 0)
        if reinforcement >= MATURITY_THRESHOLD:
            stage = getattr(claim, "evolution_stage", "initial")
            if stage in ("initial", "refined"):
                mature.append({
                    "id": getattr(claim, "id", ""),
                    "text": getattr(claim, "text", ""),
                    "topic_cluster": getattr(claim, "topic_cluster", ""),
                    "reinforcement_count": reinforcement,
                })

    # Sort by reinforcement count (most reinforced first)
    mature.sort(key=lambda c: c["reinforcement_count"], reverse=True)
    return mature


def compute_evolution(claims_tracker) -> Dict:
    """Main entry point: identify mature claims and create/update series.

    Should be called from Phase C periodically.

    Returns:
        {"new_series": int, "active_series": int, "next_topics": [...]}
    """
    state = _load_state()
    existing_series = state.get("series", [])

    # Count active series
    active = [s for s in existing_series if s.get("status") == "active"]
    if len(active) >= MAX_ACTIVE_SERIES:
        logger.info("Topic evolution: max active series reached (%d)", len(active))
        return {
            "new_series": 0,
            "active_series": len(active),
            "next_topics": _get_next_topics(active),
        }

    # Find mature claims not already in a series
    existing_claim_ids = {s.get("source_claim_id") for s in existing_series}
    mature = identify_mature_claims(claims_tracker)
    candidates = [c for c in mature if c["id"] not in existing_claim_ids]

    new_series_count = 0
    slots = MAX_ACTIVE_SERIES - len(active)

    for claim in candidates[:slots]:
        entries = _generate_series_entries(claim["text"], claim["topic_cluster"])
        series = TopicSeries(
            id=f"series_{len(existing_series) + 1:04d}",
            source_claim_text=claim["text"],
            source_claim_id=claim["id"],
            topic_cluster=claim["topic_cluster"],
            created_at=datetime.now(timezone.utc).isoformat(),
            entries=entries,
        )
        existing_series.append(asdict(series))
        new_series_count += 1
        logger.info(
            "Topic evolution: new series '%s' from claim '%s' (%dx reinforced)",
            series.id, claim["text"][:50], claim["reinforcement_count"],
        )

    state["series"] = existing_series
    state["last_computed"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)

    active = [s for s in existing_series if s.get("status") == "active"]
    return {
        "new_series": new_series_count,
        "active_series": len(active),
        "next_topics": _get_next_topics(active),
    }


def _get_next_topics(active_series: List[Dict]) -> List[Dict]:
    """Get the next planned entry from each active series."""
    topics = []
    for s in active_series:
        entries = s.get("entries", [])
        for entry in entries:
            if entry.get("status") == "planned":
                topics.append({
                    "series_id": s["id"],
                    "title": entry["title"],
                    "angle": entry["angle"],
                    "source_claim": s.get("source_claim_text", "")[:80],
                    "topic_cluster": s.get("topic_cluster", ""),
                })
                break  # Only next planned from each series
    return topics


def get_next_evolution_topic() -> Optional[Dict]:
    """Get the single best next topic for Phase A to use.

    Returns None if no evolution topics are available.
    """
    state = _load_state()
    active = [s for s in state.get("series", []) if s.get("status") == "active"]
    topics = _get_next_topics(active)
    return topics[0] if topics else None


def mark_topic_published(series_id: str, angle: str, post_id: str) -> None:
    """Mark a series entry as published after Phase A uses it."""
    state = _load_state()
    for s in state.get("series", []):
        if s["id"] != series_id:
            continue
        entries = s.get("entries", [])
        all_done = True
        for entry in entries:
            if entry["angle"] == angle and entry["status"] == "planned":
                entry["status"] = "published"
                entry["published_at"] = datetime.now(timezone.utc).isoformat()
                entry["post_id"] = post_id
            if entry["status"] == "planned":
                all_done = False
        if all_done:
            s["status"] = "completed"
            logger.info("Topic evolution: series '%s' completed", series_id)
        break
    _save_state(state)
