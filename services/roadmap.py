"""Topic roadmap: structured series-based topic selection with anti-repetition."""

import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_ROADMAP_PATH = Path("data/topic_roadmap.json")
PUBLISHED_LOG_PATH = Path("data/published_posts.json")


@dataclass
class Series:
    id: str
    weight: int
    topics: List[str]


@dataclass
class Roadmap:
    series: List[Series] = field(default_factory=list)

    def all_topics(self) -> List[str]:
        return [t for s in self.series for t in s.topics]

    def topic_to_series(self, topic: str) -> Optional[str]:
        for s in self.series:
            if topic in s.topics:
                return s.id
        return None


def _default_roadmap() -> Roadmap:
    return Roadmap(series=[
        Series(id="agent_patterns", weight=3, topics=[
            "ReAct patterns in Moltbook agents: when reasoning loops actually help",
            "Planner-Executor vs monolithic agent loops: a production comparison",
        ]),
        Series(id="guardrails", weight=2, topics=[
            "Daily quota enforcement in autonomous content agents",
            "Duplicate detection strategies for agent-generated text",
        ]),
    ])


def load_roadmap(path: Optional[Path] = None) -> Roadmap:
    p = path or DEFAULT_ROADMAP_PATH
    if not p.exists():
        logger.info("Roadmap: %s no encontrado, usando default", p)
        return _default_roadmap()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        series_list = []
        for s in data.get("series", []):
            series_list.append(Series(
                id=s["id"],
                weight=s.get("weight", 1),
                topics=s["topics"],
            ))
        return Roadmap(series=series_list)
    except Exception as e:
        logger.warning("Roadmap: error cargando %s: %s. Usando default.", p, e)
        return _default_roadmap()


def save_roadmap(roadmap: Roadmap, path: Optional[Path] = None) -> None:
    p = path or DEFAULT_ROADMAP_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "series": [
            {"id": s.id, "weight": s.weight, "topics": s.topics}
            for s in roadmap.series
        ]
    }
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_recent_topics(window: int = 5) -> set:
    if not PUBLISHED_LOG_PATH.exists():
        return set()
    try:
        history = json.loads(PUBLISHED_LOG_PATH.read_text(encoding="utf-8"))
        recent = [p.get("topic", "") for p in history[-window:] if isinstance(p, dict)]
        return set(recent)
    except Exception:
        return set()


def choose_topic_from_roadmap(roadmap: Optional[Roadmap] = None,
                               recent_window: int = 5) -> Optional[str]:
    rm = roadmap or load_roadmap()
    if not rm.series:
        return None

    recent = _load_recent_topics(window=recent_window)
    weights = [max(s.weight, 1) for s in rm.series]
    chosen_series = random.choices(rm.series, weights=weights, k=1)[0]

    # Try to pick a non-recent topic from chosen series; fallback to any topic in series
    available = [t for t in chosen_series.topics if t not in recent]
    if not available:
        available = chosen_series.topics
    return random.choice(available) if available else None


def update_series_weight(roadmap: Roadmap, series_id: str, delta: float,
                         min_weight: int = 1, max_weight: int = 10) -> None:
    for s in roadmap.series:
        if s.id == series_id:
            s.weight = max(min_weight, min(max_weight, s.weight + delta))
            break
