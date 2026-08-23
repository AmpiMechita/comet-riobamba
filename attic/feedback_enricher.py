from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from core.agent import COMETRiobambaAgent
from services.feedback_log import FEEDBACK_LOG_PATH

logger = logging.getLogger(__name__)

DEFAULT_INPUT_PATH = FEEDBACK_LOG_PATH
DEFAULT_OUTPUT_PATH = Path("data/feedback_log.enriched.jsonl")


def iter_feedback_records(path: Path) -> Iterable[Dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        logger.warning("Feedback log file not found: %s", path)
        return []

    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping corrupt JSONL line %s in %s", line_no, path)
                continue
            if not isinstance(obj, dict):
                logger.warning("Skipping non-dict JSONL line %s in %s", line_no, path)
                continue
            yield obj


def group_records_by_post(
    records: Iterable[Dict[str, Any]],
    min_events_per_post: int = 1,
) -> Dict[str, List[Dict[str, Any]]]:
    by_post: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for rec in records:
        post_id = rec.get("post_id")
        if post_id is None:
            post_id = rec.get("post_id_str") or rec.get("_post_id") or rec.get("id")
        if post_id is None:
            logger.debug("Skipping record without post_id: %s", rec)
            continue
        by_post[str(post_id)].append(rec)

    filtered = {
        pid: recs
        for pid, recs in by_post.items()
        if len(recs) >= min_events_per_post
    }

    logger.info(
        "Grouped feedback into %s posts (min_events_per_post=%s, total_records=%s)",
        len(filtered),
        min_events_per_post,
        sum(len(v) for v in filtered.values()),
    )
    return filtered


def compute_thread_metrics_from_comments(
    comments: List[Dict[str, Any]],
    agent_author_ids: Optional[Tuple[str, ...]] = None,
    depth_threshold: int = 2,
) -> Dict[str, Any]:
    agent_author_ids = tuple(a.lower() for a in (agent_author_ids or ()))

    def is_human(c: Dict[str, Any]) -> bool:
        author = c.get("author") or c.get("user") or ""
        author_norm = str(author).strip().lower()
        return author_norm != "" and author_norm not in agent_author_ids

    human_comments = [c for c in comments if is_human(c)]
    thread_comments_total = len(human_comments)

    depth_values = [int(c.get("depth", 0)) for c in comments]
    thread_replies_depth = max(depth_values) if depth_values else 0
    thread_has_deep = thread_replies_depth >= depth_threshold

    return {
        "thread_comments_total": thread_comments_total,
        "thread_replies_depth": thread_replies_depth,
        "thread_has_deep": thread_has_deep,
    }


def enrich_record_with_thread_metrics(
    record: Dict[str, Any],
    thread_metrics: Dict[str, Any],
    overwrite: bool = False,
) -> Dict[str, Any]:
    out = dict(record)

    for key in ("thread_comments_total", "thread_replies_depth", "thread_has_deep"):
        if key in thread_metrics:
            if overwrite or key not in out or out.get(key) is None:
                out[key] = thread_metrics[key]

    return out


def flatten_thread(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []

    def _walk(c: Dict[str, Any]) -> None:
        flat.append(c)
        for r in c.get("replies", []) or []:
            if isinstance(r, dict):
                _walk(r)

    _walk(node)
    return flat


def build_fetch_comments_fn(
    sincehours: int = 168,
    excludeauthors: Optional[List[str]] = None,
    minlength: int = 1,
) -> Callable[[str], List[Dict[str, Any]]]:
    excludeauthors = excludeauthors or ["cometriobamba", "comet-riobamba"]

    agent = COMETRiobambaAgent()
    client = agent.moltbook_api_client

    def _fetch_comments(post_id: str) -> List[Dict[str, Any]]:
        all_threads = client.fetchcomments(
            sincehours=sincehours,
            excludeauthors=excludeauthors,
            minlength=minlength,
        )

        if not all_threads:
            return []

        normalized: List[Dict[str, Any]] = []

        for thread in all_threads:
            if not isinstance(thread, dict):
                continue

            thread_post_id = thread.get("_post_id") or thread.get("post_id")
            if str(thread_post_id) != str(post_id):
                continue

            for c in flatten_thread(thread):
                author_obj = c.get("author") or {}
                author_name = (
                    author_obj.get("name")
                    if isinstance(author_obj, dict)
                    else c.get("author")
                )

                normalized.append(
                    {
                        "comment_id": c.get("id"),
                        "parent_id": c.get("parent_id"),
                        "author": author_name,
                        "depth": c.get("depth", 0),
                    }
                )

        return normalized

    return _fetch_comments


def enrich_feedback_log(
    input_path: Path = DEFAULT_INPUT_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    fetch_comments_fn: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
    overwrite_existing: bool = False,
    min_events_per_post: int = 1,
    depth_threshold: int = 2,
    agent_author_ids: Optional[Tuple[str, ...]] = None,
) -> None:
    records = list(iter_feedback_records(input_path))
    if not records:
        logger.warning("No feedback records found in %s", input_path)
        return

    grouped = group_records_by_post(records, min_events_per_post=min_events_per_post)
    if not grouped:
        logger.warning("No posts with at least %s events; nothing to enrich", min_events_per_post)
        return

    if fetch_comments_fn is None:
        fetch_comments_fn = build_fetch_comments_fn()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    metrics_cache: Dict[str, Dict[str, Any]] = {}

    for post_id, recs in grouped.items():
        try:
            comments = fetch_comments_fn(post_id)
        except Exception as exc:
            logger.error("Failed to fetch comments for post_id=%s: %s", post_id, exc)
            metrics_cache[post_id] = {}
            continue

        metrics_cache[post_id] = compute_thread_metrics_from_comments(
            comments=comments,
            agent_author_ids=agent_author_ids,
            depth_threshold=depth_threshold,
        )

    enriched_count = 0

    with output_path.open("w", encoding="utf-8") as out_f:
        for rec in records:
            post_id = rec.get("post_id")
            if post_id is None:
                post_id = rec.get("post_id_str") or rec.get("_post_id") or rec.get("id")
            post_id = str(post_id) if post_id is not None else None

            metrics = metrics_cache.get(post_id) if post_id is not None else None

            if metrics:
                enriched = enrich_record_with_thread_metrics(
                    record=rec,
                    thread_metrics=metrics,
                    overwrite=overwrite_existing,
                )
                out_f.write(json.dumps(enriched, ensure_ascii=False) + "\n")
                enriched_count += 1
            else:
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    logger.info(
        "Enriched %s records across %s posts into %s (min_events_per_post=%s, depth_threshold=%s)",
        enriched_count,
        len(grouped),
        output_path,
        min_events_per_post,
        depth_threshold,
    )


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich feedback_log.jsonl with thread-level metrics (comments_total, depth, has_deep).",
    )
    parser.add_argument("--input", type=str, default=str(DEFAULT_INPUT_PATH))
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--min-events-per-post", type=int, default=1)
    parser.add_argument("--depth-threshold", type=int, default=2)
    parser.add_argument("--sincehours", type=int, default=168)
    parser.add_argument("--overwrite-existing", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    input_path = Path(args.input)
    output_path = Path(args.output)

    try:
        fetch_comments_fn = build_fetch_comments_fn(
            sincehours=args.sincehours,
            excludeauthors=["cometriobamba", "comet-riobamba"],
            minlength=1,
        )

        enrich_feedback_log(
            input_path=input_path,
            output_path=output_path,
            fetch_comments_fn=fetch_comments_fn,
            overwrite_existing=args.overwrite_existing,
            min_events_per_post=args.min_events_per_post,
            depth_threshold=args.depth_threshold,
            agent_author_ids=("comet_riobamba", "cometriobamba", "comet-riobamba"),
        )
    except Exception as exc:
        logger.error("Unexpected error during enrichment: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
