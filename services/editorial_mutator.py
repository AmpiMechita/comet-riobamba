from pathlib import Path
import json
from typing import Dict, Any

from services.feedback_analysis import summarize_feedback_by_topic

POLICY_PATH = Path("data/editorial_policy.json")


def load_policy() -> Dict[str, Any]:
    if not POLICY_PATH.exists():
        raise FileNotFoundError(f"Policy file not found: {POLICY_PATH}")
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def compute_topic_score(stats: Dict[str, Any]) -> float:
    avg_comments = float(stats.get("avg_comments_count", 0.0) or 0.0)
    deep_ratio = float(stats.get("deep_thread_ratio", 0.0) or 0.0)
    sentiments = stats.get("sentiment_counts", {}) or {}

    positive = float(sentiments.get("positive", 0) or 0)
    neutral = float(sentiments.get("neutral", 0) or 0)
    negative = float(sentiments.get("negative", 0) or 0)
    total = positive + neutral + negative

    sentiment_score = 0.0
    if total > 0:
        sentiment_score = (positive - negative) / total

    return (avg_comments * 0.5) + (deep_ratio * 1.5) + (sentiment_score * 0.5)


def propose_topic_weight_updates(policy: Dict[str, Any]) -> Dict[str, Any]:
    topic_weights = (policy.get("topic_weights") or {}).copy()
    mutation_limits = policy.get("mutation_limits") or {}

    max_delta = float(mutation_limits.get("max_topic_weight_delta", 0.15) or 0.15)
    min_weight = float(mutation_limits.get("min_topic_weight", 0.05) or 0.05)
    max_weight = float(mutation_limits.get("max_topic_weight", 0.60) or 0.60)

    feedback_summary = summarize_feedback_by_topic()
    proposals = {}

    for topic, stats in feedback_summary.items():
        if topic not in topic_weights:
            continue

        current = float(topic_weights.get(topic, 0.0) or 0.0)
        score = compute_topic_score(stats)

        if score >= 1.5:
            delta = max_delta
        elif score >= 0.75:
            delta = max_delta * 0.5
        elif score <= -0.5:
            delta = -max_delta
        elif score <= 0.0:
            delta = -max_delta * 0.5
        else:
            delta = 0.0

        proposed = clamp(current + delta, min_weight, max_weight)

        proposals[topic] = {
            "current_weight": round(current, 4),
            "proposed_weight": round(proposed, 4),
            "delta": round(proposed - current, 4),
            "score": round(score, 4),
            "stats": stats,
        }

    return proposals


if __name__ == "__main__":
    policy = load_policy()
    proposals = propose_topic_weight_updates(policy)

    if not proposals:
        print("NO_TOPIC_WEIGHT_PROPOSALS")
    else:
        for topic, info in proposals.items():
            print(f"Topic: {topic}")
            print(f"  current_weight:  {info['current_weight']}")
            print(f"  proposed_weight: {info['proposed_weight']}")
            print(f"  delta:           {info['delta']}")
            print(f"  score:           {info['score']}")
            print()
