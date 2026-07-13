from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from services.editorial_mutator import propose_topic_weight_updates
from services.feedback_analysis import summarize_feedback_by_topic

logger = logging.getLogger(__name__)

POLICY_PATH = Path("data/editorial_policy.json")
NEXT_POLICY_PATH = Path("data/editorial_policy.next.json")


def load_policy(path: Path = POLICY_PATH) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Policy file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        try:
            policy = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in policy file {path}: {exc}") from exc

    if not isinstance(policy, dict):
        raise ValueError(f"Policy file {path} must contain a JSON object at top level")

    return policy


def get_topic_feedback_stats(
    min_events: int = 1,
    phases_filter: Optional[Tuple[str, ...]] = None,
) -> Dict[str, Dict[str, Any]]:
    summary = summarize_feedback_by_topic()
    filtered: Dict[str, Dict[str, Any]] = {}

    for topic, stats in summary.items():
        total_events = int(stats.get("total_events", 0))
        phases = stats.get("phases", {}) or {}

        if phases_filter:
            filtered_events = sum(int(phases.get(phase, 0)) for phase in phases_filter)
        else:
            filtered_events = total_events

        if filtered_events < min_events:
            logger.debug(
                "Ignoring topic %s due to insufficient events after phase filter: %s < %s",
                topic,
                filtered_events,
                min_events,
            )
            continue

        stats_copy = dict(stats)
        stats_copy["filtered_events"] = filtered_events
        filtered[topic] = stats_copy

    return filtered


def get_topic_weight_proposals(policy: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    proposals = propose_topic_weight_updates(policy) or {}
    if not isinstance(proposals, dict):
        raise ValueError("propose_topic_weight_updates must return a dict")
    return proposals


def apply_proposals_to_policy(
    policy: Dict[str, Any],
    proposals: Dict[str, Dict[str, Any]],
    feedback_stats: Dict[str, Dict[str, Any]],
    min_events: int = 1,
    min_deep_thread_ratio: float = 0.0,
) -> Dict[str, Any]:
    topic_weights = dict(policy.get("topic_weights") or {})
    if not isinstance(topic_weights, dict):
        raise ValueError("policy.topic_weights must be a dict")

    updated_topic_weights = dict(topic_weights)
    applied_topics = []

    for topic, proposal in proposals.items():
        delta = float(proposal.get("delta", 0.0))
        if abs(delta) <= 0.0:
            logger.debug("Skipping topic %s because delta is zero", topic)
            continue

        stats = feedback_stats.get(topic)
        if not stats:
            logger.info(
                "Skipping topic %s: no feedback stats or below min_events=%s",
                topic,
                min_events,
            )
            continue

        filtered_events = int(stats.get("filtered_events", 0))
        if filtered_events < min_events:
            logger.info(
                "Skipping topic %s: filtered_events=%s < min_events=%s",
                topic,
                filtered_events,
                min_events,
            )
            continue

        deep_thread_ratio = float(stats.get("deep_thread_ratio", 0.0))
        if deep_thread_ratio < min_deep_thread_ratio:
            logger.info(
                "Skipping topic %s: deep_thread_ratio=%.4f < min_deep_thread_ratio=%.4f",
                topic,
                deep_thread_ratio,
                min_deep_thread_ratio,
            )
            continue

        current_weight = float(proposal.get("current_weight", 0.0))
        proposed_weight = float(proposal.get("proposed_weight", current_weight))

        if topic not in updated_topic_weights:
            logger.warning(
                "Topic %s present in proposals but not in policy.topic_weights; skipping",
                topic,
            )
            continue

        logger.info(
            "Applying proposal for topic %s: %.4f -> %.4f (delta=%.4f, events=%s, deep_thread_ratio=%.4f)",
            topic,
            current_weight,
            proposed_weight,
            delta,
            filtered_events,
            deep_thread_ratio,
        )
        updated_topic_weights[topic] = proposed_weight
        applied_topics.append(topic)

    new_policy = dict(policy)
    new_policy["topic_weights"] = updated_topic_weights

    if not applied_topics:
        logger.warning("No topic weight changes applied after filters")

    return new_policy


def write_next_policy_safely(
    policy_next: Dict[str, Any],
    path: Path = NEXT_POLICY_PATH,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(policy_next, indent=2, sort_keys=True, ensure_ascii=False)

    with tmp_path.open("w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, path)
    logger.info("Wrote next policy to %s", path)
    return path


def has_effective_changes(
    policy_current: Dict[str, Any],
    policy_next: Dict[str, Any],
) -> bool:
    current_tw = policy_current.get("topic_weights") or {}
    next_tw = policy_next.get("topic_weights") or {}
    return current_tw != next_tw


def print_summary(
    policy_current: Dict[str, Any],
    policy_next: Dict[str, Any],
    proposals: Dict[str, Dict[str, Any]],
    feedback_stats: Dict[str, Dict[str, Any]],
    min_events: int,
    min_deep_thread_ratio: float,
) -> None:
    current_tw = policy_current.get("topic_weights") or {}
    next_tw = policy_next.get("topic_weights") or {}

    print("=== Editorial Policy Apply Summary ===")
    print(f"min_events filter: {min_events}")
    print(f"min_deep_thread_ratio filter: {min_deep_thread_ratio}")
    print()

    for topic, proposal in proposals.items():
        cur = proposal.get("current_weight")
        prop = proposal.get("proposed_weight")
        delta = float(proposal.get("delta", 0.0))
        stats = feedback_stats.get(topic)
        events = int(stats.get("filtered_events", 0)) if stats else 0
        deep_thread_ratio = float(stats.get("deep_thread_ratio", 0.0)) if stats else 0.0

        cur_final = current_tw.get(topic)
        next_final = next_tw.get(topic)

        if topic not in next_tw:
            status = "IGNORED_NOT_IN_POLICY"
        elif cur_final == next_final:
            if events < min_events:
                status = "IGNORED_INSUFFICIENT_EVENTS"
            elif deep_thread_ratio < min_deep_thread_ratio:
                status = "IGNORED_LOW_DEEP_THREAD_RATIO"
            else:
                status = "IGNORED_DELTA_ZERO_OR_FILTERED"
        else:
            status = "APPLIED"

        print(
            f"topic={topic} "
            f"status={status} "
            f"events={events} "
            f"deep_thread_ratio={deep_thread_ratio:.4f} "
            f"delta={delta:.4f} "
            f"current={cur} "
            f"proposed={prop} "
            f"final={next_final}"
        )

    print()
    if not has_effective_changes(policy_current, policy_next):
        print("NO_TOPIC_WEIGHT_CHANGES_AFTER_FILTERS")
    else:
        print("TOPIC_WEIGHT_CHANGES_APPLIED")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply editorial topic weight proposals into a next policy file with human-in-the-loop safeguards.",
    )

    parser.add_argument(
        "--policy-path",
        type=str,
        default=str(POLICY_PATH),
        help="Path to the current editorial policy JSON (default: data/editorial_policy.json).",
    )
    parser.add_argument(
        "--next-path",
        type=str,
        default=str(NEXT_POLICY_PATH),
        help="Path to write the next editorial policy JSON (default: data/editorial_policy.next.json).",
    )
    parser.add_argument(
        "--min-events",
        type=int,
        default=3,
        help="Minimum number of feedback events per topic to allow changes (default: 3).",
    )
    parser.add_argument(
        "--phases",
        type=str,
        default="",
        help="Optional comma-separated list of phases to consider (e.g., 'A,B' or 'B'). If empty, all phases are considered.",
    )
    parser.add_argument(
        "--min-deep-thread-ratio",
        type=float,
        default=0.0,
        help="Minimum deep_thread_ratio required to allow changes (default: 0.0).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write any file, only print summary of potential changes.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging (set log level to INFO).",
    )

    args = parser.parse_args(argv)
    if args.min_deep_thread_ratio < 0.0:
        args.min_deep_thread_ratio = 0.0
    if args.min_deep_thread_ratio > 1.0:
        args.min_deep_thread_ratio = 1.0
    return args


def configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    policy_path = Path(args.policy_path)
    next_path = Path(args.next_path)

    try:
        policy = load_policy(policy_path)
    except Exception as exc:
        logger.error("Failed to load policy from %s: %s", policy_path, exc)
        return 1

    phases_filter: Optional[Tuple[str, ...]] = None
    if args.phases:
        phases_filter = tuple(
            p.strip() for p in args.phases.split(",") if p.strip()
        )
        logger.info("Using phases filter: %s", phases_filter)

    feedback_stats = get_topic_feedback_stats(
        min_events=1,
        phases_filter=phases_filter,
    )

    proposals = get_topic_weight_proposals(policy)

    policy_next = apply_proposals_to_policy(
        policy=policy,
        proposals=proposals,
        feedback_stats=feedback_stats,
        min_events=args.min_events,
        min_deep_thread_ratio=args.min_deep_thread_ratio,
    )

    print_summary(
        policy_current=policy,
        policy_next=policy_next,
        proposals=proposals,
        feedback_stats=feedback_stats,
        min_events=args.min_events,
        min_deep_thread_ratio=args.min_deep_thread_ratio,
    )

    if not has_effective_changes(policy, policy_next):
        logger.warning("No effective topic_weight changes; not writing next policy file")
        return 0

    if args.dry_run:
        logger.info("Dry run enabled; not writing next policy file")
        return 0

    try:
        write_next_policy_safely(policy_next, next_path)
    except Exception as exc:
        logger.error("Failed to write next policy to %s: %s", next_path, exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())