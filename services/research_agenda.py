# -*- coding: utf-8 -*-
"""
Research Agenda — Trend watcher and memory for COMET-RIOBAMBA.

Maintains a structured store of open questions, pending topics, experiments,
high-impact threads, and new terms.  Fed by Phase C (analytics) and consumed
by Phase A (topic selection) and Phase B (frontier-aware replies).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

AGENDA_PATH = Path("data/research_agenda.json")
ARCHIVE_PATH = Path("data/research_agenda_archive.json")

# ── Retention policy (env-overridable) ────────────────────────────
# TTL for covered topics: once a topic was posted, it need not linger in the
# active agenda. Uncovered topics are not purged by age; they are ARCHIVED
# (moved, not deleted) after a longer window, since a topic ignored for months
# is likely stale but worth keeping as history. A hard cap on active entries is
# the safety net if the TTL sweep does not run (crash/deploy).
COVERED_TTL_DAYS = int(os.getenv("AGENDA_COVERED_TTL_DAYS", "14"))
UNCOVERED_ARCHIVE_DAYS = int(os.getenv("AGENDA_UNCOVERED_ARCHIVE_DAYS", "60"))
MAX_ACTIVE_TOPICS = int(os.getenv("AGENDA_MAX_ACTIVE_TOPICS", "150"))

# ── Prune frequency guard ─────────────────────────────────────────
# prune_agenda() is safe to call every Phase C cycle: an internal guard tracks
# the last run in data/prune_agenda_last_run.json and no-ops silently if the
# configured interval has not elapsed. Same persistence pattern as
# degraded_mode_state.json (gitignored).
PRUNE_STATE_PATH = Path("data/prune_agenda_last_run.json")
PRUNE_INTERVAL_HOURS = float(os.getenv("PRUNE_INTERVAL_HOURS", "24"))


@dataclass
class ResearchAgenda:
    open_questions: List[Dict] = field(default_factory=list)
    pending_topics: List[Dict] = field(default_factory=list)
    experiments: List[Dict] = field(default_factory=list)
    high_impact_threads: List[Dict] = field(default_factory=list)
    new_terms: List[Dict] = field(default_factory=list)

    # ── Open questions ────────────────────────────────────────────

    def add_question(self, question: str, source: str = "", tags: Optional[List[str]] = None) -> None:
        self.open_questions.append({
            "question": question,
            "source": source,
            "tags": tags or [],
            "status": "open",
            "created_at": _now_iso(),
        })

    def mark_answered(self, question: str) -> bool:
        for q in self.open_questions:
            if q["question"] == question and q["status"] == "open":
                q["status"] = "answered"
                return True
        return False

    def get_open_questions(self, limit: int = 5) -> List[Dict]:
        return [q for q in self.open_questions if q["status"] == "open"][:limit]

    # ── Pending topics ───────────────────────────────────────────

    def add_topic(self, topic: str, source: str = "", tags: Optional[List[str]] = None) -> None:
        existing = {t["topic"] for t in self.pending_topics}
        if topic not in existing:
            self.pending_topics.append({
                "topic": topic,
                "source": source,
                "tags": tags or [],
                "covered": False,
                "created_at": _now_iso(),
            })

    def mark_covered(self, topic: str) -> bool:
        for t in self.pending_topics:
            if t["topic"] == topic and not t["covered"]:
                t["covered"] = True
                return True
        return False

    def get_uncovered_topics(self, limit: int = 5) -> List[Dict]:
        return [t for t in self.pending_topics if not t["covered"]][:limit]

    # ── Experiments ──────────────────────────────────────────────

    def add_experiment(self, title: str, description: str = "", tags: Optional[List[str]] = None) -> None:
        self.experiments.append({
            "title": title,
            "description": description,
            "tags": tags or [],
            "status": "proposed",
            "created_at": _now_iso(),
        })

    # ── High-impact threads ──────────────────────────────────────

    def add_high_impact_thread(self, thread_id: str, title: str = "",
                               engagement: int = 0, tags: Optional[List[str]] = None) -> None:
        existing = {t["thread_id"] for t in self.high_impact_threads}
        if thread_id not in existing:
            self.high_impact_threads.append({
                "thread_id": thread_id,
                "title": title,
                "engagement": engagement,
                "tags": tags or [],
                "created_at": _now_iso(),
            })

    # ── New terms ────────────────────────────────────────────────

    def add_new_term(self, term: str, context: str = "", source: str = "") -> None:
        existing = {t["term"].lower() for t in self.new_terms}
        if term.lower() not in existing:
            self.new_terms.append({
                "term": term,
                "context": context,
                "source": source,
                "created_at": _now_iso(),
            })

    # ── Serialization ────────────────────────────────────────────

    def to_dict(self) -> Dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict) -> ResearchAgenda:
        return ResearchAgenda(
            open_questions=data.get("open_questions", []),
            pending_topics=data.get("pending_topics", []),
            experiments=data.get("experiments", []),
            high_impact_threads=data.get("high_impact_threads", []),
            new_terms=data.get("new_terms", []),
        )


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def load_agenda() -> ResearchAgenda:
    if not AGENDA_PATH.exists():
        logger.debug("Research agenda file %s not found, starting empty.", AGENDA_PATH)
        return ResearchAgenda()
    try:
        data = json.loads(AGENDA_PATH.read_text(encoding="utf-8"))
        return ResearchAgenda.from_dict(data)
    except Exception as e:
        logger.warning("Could not load research agenda from %s: %s", AGENDA_PATH, e)
        return ResearchAgenda()


def save_agenda(agenda: ResearchAgenda) -> None:
    try:
        AGENDA_PATH.parent.mkdir(parents=True, exist_ok=True)
        AGENDA_PATH.write_text(
            json.dumps(agenda.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Could not save research agenda to %s: %s", AGENDA_PATH, e)


# ── Retention / pruning ───────────────────────────────────────────


def _parse_ts(value: object) -> Optional[datetime]:
    """Parse an ISO-8601 created_at; return tz-aware UTC datetime or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_days(topic: Dict, now: datetime) -> Optional[float]:
    dt = _parse_ts(topic.get("created_at"))
    if dt is None:
        return None
    return (now - dt).total_seconds() / 86400.0


def _append_archive(topics: List[Dict]) -> None:
    """Append topics to research_agenda_archive.json (create if missing)."""
    if not topics:
        return
    try:
        ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if ARCHIVE_PATH.exists():
            try:
                existing = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
                archived = existing.get("archived_topics", []) if isinstance(existing, dict) else []
            except (ValueError, TypeError, json.JSONDecodeError):
                archived = []
        else:
            archived = []
        archived.extend(topics)
        ARCHIVE_PATH.write_text(
            json.dumps({"archived_topics": archived}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Could not append to research agenda archive %s: %s", ARCHIVE_PATH, e)


def _load_prune_last_run() -> float:
    """Return the epoch of the last prune run (0.0 if never / unreadable)."""
    try:
        with open(PRUNE_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return float(data.get("last_pruned_at", 0.0))
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError):
        return 0.0
    except Exception as e:
        logger.debug("Could not read prune state %s: %s", PRUNE_STATE_PATH, e)
        return 0.0


def _save_prune_last_run(epoch: float) -> None:
    try:
        PRUNE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PRUNE_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"last_pruned_at": epoch}, f, ensure_ascii=False)
    except Exception as e:
        logger.warning("Could not persist prune state %s: %s", PRUNE_STATE_PATH, e)


def prune_agenda(
    agenda: ResearchAgenda,
    now: Optional[datetime] = None,
    covered_ttl_days: int = COVERED_TTL_DAYS,
    uncovered_archive_days: int = UNCOVERED_ARCHIVE_DAYS,
    max_active: int = MAX_ACTIVE_TOPICS,
    respect_interval: bool = True,
    interval_hours: float = PRUNE_INTERVAL_HOURS,
) -> Dict[str, int]:
    """Prune pending_topics in place. Returns counts of what happened.

    Policy (state-aware TTL + hard cap safety net):
      1. TTL: drop covered=True topics older than ``covered_ttl_days`` (deleted).
      2. Archive: move covered=False topics older than ``uncovered_archive_days``
         to research_agenda_archive.json (preserved, not deleted).
      3. Hard cap: if active topics still exceed ``max_active``, evict the oldest
         covered=True first, then the oldest covered=False, archiving the evicted
         uncovered ones. This is the safety net if the TTL sweep lapses.

    Frequency guard: when ``respect_interval`` is True (default), the prune logic
    only runs if at least ``interval_hours`` elapsed since the last successful run
    (persisted in data/prune_agenda_last_run.json). Otherwise it is a silent
    no-op returning ``{"skipped": 1, ...}``. This makes it safe to call every
    Phase C cycle. Pass ``respect_interval=False`` to force a run (tests / manual).

    ``now`` is injectable for deterministic testing. Topics without a parseable
    ``created_at`` are treated as age 0 (never purged by age; kept newest).
    """
    now = now or datetime.now(timezone.utc)

    result = {"dropped_covered_ttl": 0, "archived_uncovered_ttl": 0,
              "capped_dropped_covered": 0, "capped_archived_uncovered": 0,
              "before": len(agenda.pending_topics), "after": len(agenda.pending_topics),
              "skipped": 0}

    # ── Frequency guard: no-op silently if interval has not elapsed ──
    if respect_interval:
        last_run = _load_prune_last_run()
        if last_run > 0.0:
            elapsed_hours = (now.timestamp() - last_run) / 3600.0
            if elapsed_hours < interval_hours:
                logger.debug(
                    "prune_agenda: skipped (%.1fh since last run < %.1fh interval)",
                    elapsed_hours, interval_hours,
                )
                result["skipped"] = 1
                return result

    topics = list(agenda.pending_topics)

    to_archive: List[Dict] = []
    survivors: List[Dict] = []

    # ── 1 & 2: age-based TTL / archive ──
    for t in topics:
        age = _age_days(t, now)
        covered = bool(t.get("covered"))
        if covered:
            if age is not None and age >= covered_ttl_days:
                result["dropped_covered_ttl"] += 1
                continue  # deleted
            survivors.append(t)
        else:
            if age is not None and age >= uncovered_archive_days:
                to_archive.append(t)
                result["archived_uncovered_ttl"] += 1
                continue  # archived, not kept
            survivors.append(t)

    # ── 3: hard cap safety net ──
    if len(survivors) > max_active:
        # Sort by age descending (oldest first) using created_at; missing ts = newest.
        def _sort_key(t: Dict):
            dt = _parse_ts(t.get("created_at"))
            # oldest first: smaller timestamp sorts first; missing -> treat as newest
            return dt or now

        overflow = len(survivors) - max_active
        # Evict covered first (oldest), then uncovered (oldest).
        covered_sorted = sorted([t for t in survivors if t.get("covered")], key=_sort_key)
        uncovered_sorted = sorted([t for t in survivors if not t.get("covered")], key=_sort_key)

        evict_ids = []  # identity-based eviction set
        evicted = []
        for t in covered_sorted:
            if len(evicted) >= overflow:
                break
            evicted.append(t)
            evict_ids.append(id(t))
            result["capped_dropped_covered"] += 1
        if len(evicted) < overflow:
            for t in uncovered_sorted:
                if len(evicted) >= overflow:
                    break
                evicted.append(t)
                evict_ids.append(id(t))
                to_archive.append(t)  # preserve uncovered even when cap-evicted
                result["capped_archived_uncovered"] += 1

        evict_set = set(evict_ids)
        survivors = [t for t in survivors if id(t) not in evict_set]

    _append_archive(to_archive)
    agenda.pending_topics = survivors
    result["after"] = len(survivors)
    # Record successful run for the frequency guard.
    _save_prune_last_run(now.timestamp())
    return result
