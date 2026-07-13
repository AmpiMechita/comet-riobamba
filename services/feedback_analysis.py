from pathlib import Path
import json
import re
from typing import Dict, Any, List


FEEDBACK_LOG_PATH = Path("data/feedback_log.jsonl")


TOPIC_ALIASES = {
    "agent memory and feedback": "memoria_y_feedback",
    "memory and feedback": "memoria_y_feedback",
    "agent memory": "memoria_y_feedback",
    "feedback loops": "memoria_y_feedback",
    "specialized ai agents": "agentes_ia_especializados",
    "ai agents": "agentes_ia_especializados",
    "agent architecture": "arquitectura_agentica",
    "agent orchestration": "arquitectura_agentica",
    "llm optimization": "optimizacion_llm",
    "llm optimization and inference": "optimizacion_llm",
}


def canonicalize_topic(raw_topic: str) -> str:
    topic = str(raw_topic or "").strip().lower()
    topic = re.sub(r"\s+", " ", topic)
    if not topic:
        return "unknown"
    return TOPIC_ALIASES.get(topic, topic)


def _iter_feedback_records() -> List[Dict[str, Any]]:
    if not FEEDBACK_LOG_PATH.exists():
        return []

    records: List[Dict[str, Any]] = []
    with FEEDBACK_LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    records.append(obj)
            except json.JSONDecodeError:
                # Saltar líneas corruptas sin romper el análisis
                continue
    return records


def summarize_feedback_by_topic() -> Dict[str, Dict[str, Any]]:
    """
    Devuelve un resumen agregado por topic.

    Estructura:
    {
      "topic1": {
        "total_events": int,
        "sum_comments_count": int,
        "avg_comments_count": float,
        "deep_thread_events": int,
        "deep_thread_ratio": float,
        "sentiment_counts": {"positive": int, "neutral": int, "negative": int},
        "phases": {"A": int, "B": int}
      },
      ...
    }
    """
    records = _iter_feedback_records()
    summary: Dict[str, Dict[str, Any]] = {}

    for rec in records:
        topic = canonicalize_topic(rec.get("topic") or "unknown")
        phase = str(rec.get("phase") or "?")
        metrics = rec.get("metrics") or {}
        quality = rec.get("quality") or {}

        comments_count = int(metrics.get("comments_count") or 0)
        has_deep = bool(quality.get("has_deep_thread") or False)
        sentiment = str(quality.get("sentiment") or "unknown")

        t = summary.setdefault(
            topic,
            {
                "total_events": 0,
                "sum_comments_count": 0,
                "deep_thread_events": 0,
                "sentiment_counts": {"positive": 0, "neutral": 0, "negative": 0, "other": 0},
                "phases": {},
            },
        )

        t["total_events"] += 1
        t["sum_comments_count"] += comments_count

        if has_deep:
            t["deep_thread_events"] += 1

        if sentiment in ("positive", "neutral", "negative"):
            t["sentiment_counts"][sentiment] += 1
        else:
            t["sentiment_counts"]["other"] += 1

        t["phases"][phase] = t["phases"].get(phase, 0) + 1

    # Post-procesar promedios/ratios
    for topic, t in summary.items():
        total = t["total_events"]
        if total > 0:
            t["avg_comments_count"] = t["sum_comments_count"] / float(total)
            t["deep_thread_ratio"] = t["deep_thread_events"] / float(total)
        else:
            t["avg_comments_count"] = 0.0
            t["deep_thread_ratio"] = 0.0

    return summary


if __name__ == "__main__":
    data = summarize_feedback_by_topic()
    for topic, stats in data.items():
        print(f"Topic: {topic}")
        print(f"  total_events: {stats['total_events']}")
        print(f"  avg_comments_count: {stats['avg_comments_count']:.2f}")
        print(f"  deep_thread_ratio: {stats['deep_thread_ratio']:.2f}")
        print(f"  sentiment_counts: {stats['sentiment_counts']}")
        print(f"  phases: {stats['phases']}")
        print()
