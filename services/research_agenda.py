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
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

AGENDA_PATH = Path("data/research_agenda.json")


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
