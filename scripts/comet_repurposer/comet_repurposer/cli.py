#!/usr/bin/env python
"""
COMET-RIOBAMBA multi-platform repurposer + publisher.

Two stages:
  1. ``generate``  -- read agent output, call LLM, produce markdown
                      drafts per platform (LinkedIn, X, TikTok, etc.)
  2. ``publish``   -- take approved drafts and POST them to the
                      platform APIs (LinkedIn + X/Twitter for now).

Approval gate (1-click) sits between the two: nothing publishes until
you run ``approve <job_id>`` (or ``approve --all``).

Examples
--------
    # Stage 1 — generate drafts for the latest 5 items
    python -m comet_repurposer generate --source latest --limit 5

    # Stage 1 — also enqueue into the publish queue (status=generated)
    python -m comet_repurposer generate --source latest --limit 5 \\
        --enqueue-linkedin --enqueue-twitter

    # See what's in the queue
    python -m comet_repurposer queue

    # Approve specific jobs (1-click gate)
    python -m comet_repurposer approve 12 13 14
    python -m comet_repurposer approve --all --platform linkedin

    # Dry-run publish (default; just shows what would be posted)
    python -m comet_repurposer publish --dry-run

    # Real publish (kill switch must be OFF)
    python -m comet_repurposer publish --for-real

    # Emergency stop
    python -m comet_repurposer kill --reason "wrong tone"

    # First-time LinkedIn OAuth setup
    python -m comet_repurposer auth-linkedin
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

from .config import ALL_PLATFORMS, RepurposeConfig
from .dedup import DedupStore
from .llm_client import LLMClient
from .pipeline import repurpose_batch
from .sources import (
    SourceItem,
    iter_all_sources,
    iter_ebooks,
    iter_latest,
    iter_published_posts,
    iter_research_agenda,
    iter_social_content,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_platforms(raw: str) -> list[str]:
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    valid = set(ALL_PLATFORMS)
    bad = [p for p in parts if p not in valid]
    if bad:
        raise SystemExit(f"Unknown platform(s): {bad}. Valid: {sorted(valid)}")
    return parts


def _select_items(source: str, project_root: Path, limit: int | None) -> Iterator[SourceItem]:
    if source == "all":
        it = iter_all_sources(project_root)
    elif source == "latest":
        it = iter_latest(project_root, n=limit or 5)
    elif source == "social_content":
        it = iter_social_content(project_root)
    elif source == "published_posts":
        it = iter_published_posts(project_root)
    elif source == "ebook":
        it = iter_ebooks(project_root)
    elif source == "research_agenda":
        it = iter_research_agenda(project_root)
    else:
        raise SystemExit(f"Unknown --source: {source}")
    items = list(it)
    if limit and source != "latest":
        items = items[:limit]
    return iter(items)


def _print_progress(idx: int, total: int, item: SourceItem, results: dict) -> None:
    ok_count = sum(1 for r in results.values() if r.get("ok"))
    skip_count = sum(1 for r in results.values() if r.get("skipped"))
    fail_count = sum(1 for r in results.values() if not r.get("ok"))
    print(
        f"[{idx}/{total}] {item.source_kind:15s} | {item.title[:60]:60s} "
        f"| ok={ok_count} skipped={skip_count} failed={fail_count}",
        file=sys.stderr,
    )
    for platform, r in results.items():
        if not r.get("ok"):
            print(f"    ! {platform}: {r.get('error')}", file=sys.stderr)
        elif r.get("skipped"):
            print(f"    ~ {platform}: skipped ({r.get('reason')})", file=sys.stderr)
        else:
            print(f"    + {platform}: {r.get('path')}", file=sys.stderr)


def _load_payload_for_publish(md_path: Path) -> tuple[dict, str]:
    """Parse a generated markdown file back into (payload, plain_text).

    For LinkedIn we extract the 'Post' section.
    For Twitter we extract the 'Tweets' section.
    """
    text = md_path.read_text(encoding="utf-8")
    # Heuristic: find the '## Post' or '## Tweets' section.
    payload: dict = {}
    plain = ""

    import re
    # Twitter: list of tweets
    tweets_match = re.search(r"^## Tweets\s*$\n((?:^\d+\.\s.*$\n?)+)", text, flags=re.MULTILINE)
    if tweets_match:
        block = tweets_match.group(1)
        tweets = [line.split(". ", 1)[1] for line in block.strip().splitlines()
                  if line.strip().startswith(tuple("0123456789")) and ". " in line]
        payload["tweets"] = tweets
        plain = "\n\n".join(tweets)
        return payload, plain

    # LinkedIn: post body
    post_match = re.search(r"^## Post\s*$\n^(.+?)(?=^## |\Z)", text, flags=re.MULTILINE | re.DOTALL)
    if post_match:
        plain = post_match.group(1).strip()
        payload["post"] = plain
        return payload, plain

    # Fallback: take everything after the first '---' separator.
    parts = text.split("---", 1)
    if len(parts) == 2:
        plain = parts[1].strip()
    return payload or {"text": plain}, plain


def _build_publisher(platform: str, cfg: RepurposeConfig, dry_run: bool):
    """Factory: return a publisher instance for the platform.

    Accepts both 'x' and 'twitter' as aliases for X/Twitter.
    """
    if platform == "linkedin":
        from .publishers.linkedin import LinkedInPublisher
        return LinkedInPublisher(
            credentials=cfg.linkedin_credentials,
            dry_run=dry_run,
            timeout=cfg.request_timeout,
        )
    if platform in ("x", "twitter"):
        from .publishers.twitter import TwitterPublisher
        return TwitterPublisher(
            credentials=cfg.twitter_credentials,
            dry_run=dry_run,
            timeout=cfg.request_timeout,
        )
    raise SystemExit(f"No publisher implemented for platform: {platform}")


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_generate(args, cfg: RepurposeConfig) -> int:
    """Stage 1: read sources, call LLM, write markdown drafts.
    Optionally enqueue drafts into the publish queue."""
    items = list(_select_items(args.source, cfg.project_root, args.limit))
    if not items:
        print("No source items found.", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"Would process {len(items)} item(s) for platforms: {cfg.platforms}")
        for i, item in enumerate(items, 1):
            print(f"  {i}. [{item.source_kind}] {item.title}")
        return 0

    print(f"Repurposing {len(items)} item(s) to {cfg.output_root}", file=sys.stderr)
    print(f"Platforms: {cfg.platforms}", file=sys.stderr)
    print(f"Language : {cfg.language}", file=sys.stderr)
    print(f"Providers: {[p['name'] for p in cfg.llm_providers]}", file=sys.stderr)
    print("-" * 70, file=sys.stderr)

    client = LLMClient(
        providers=cfg.llm_providers,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        timeout=cfg.request_timeout,
    )
    dedup = DedupStore(cfg.dedup_db_path)

    # Build semantic dedup if requested (default: on, lexical-only mode).
    sem_dedup = None
    sem_threshold = getattr(args, "semantic_threshold", 0.20)  # TF-IDF calibrated
    use_semantic = getattr(args, "semantic_dedup", True)
    if use_semantic:
        from .semantic_dedup import SemanticDedup, EmbeddingsClient
        # If user has configured an embeddings endpoint in .env, use it.
        # Otherwise fall back to lexical TF-IDF mode (less precise but
        # still catches obvious duplicates).
        emb_client = None
        emb_base = os.getenv("EMBEDDINGS_BASE_URL", "").strip()
        emb_key = os.getenv("EMBEDDINGS_API_KEY", "").strip()
        emb_model = os.getenv("EMBEDDINGS_MODEL", "").strip()
        if emb_base and emb_key and emb_model:
            emb_client = EmbeddingsClient(
                base_url=emb_base, api_key=emb_key, model=emb_model,
            )
            # When embeddings are available, raise the default threshold.
            if sem_threshold < 0.5:
                sem_threshold = 0.85
                print(f"[semantic dedup] Using embeddings ({emb_model}); "
                      f"threshold=0.85", file=sys.stderr)
        else:
            print(f"[semantic dedup] No EMBEDDINGS_* env vars set; using "
                  f"lexical TF-IDF mode (threshold={sem_threshold}). "
                  f"For better results, set EMBEDDINGS_BASE_URL, "
                  f"EMBEDDINGS_API_KEY, EMBEDDINGS_MODEL in .env.",
                  file=sys.stderr)
        sem_dedup = SemanticDedup(
            db_path=cfg.project_root / "data" / "semantic_dedup.db",
            embeddings_client=emb_client,
        )

    enqueue_platforms: List[str] = []
    if args.enqueue_linkedin:
        enqueue_platforms.append("linkedin")
    if getattr(args, "enqueue_x", False) or getattr(args, "enqueue_twitter", False):
        enqueue_platforms.append("x")

    queue = None
    if enqueue_platforms:
        from .publishers.base import QueueStore, PublishJob, PublishStatus
        queue = QueueStore(cfg.publish_queue_db_path)

    try:
        all_results = repurpose_batch(
            items=items,
            cfg=cfg,
            client=client,
            dedup=dedup,
            force=args.force,
            platforms=cfg.platforms,
            on_progress=_print_progress,
            semantic_dedup=sem_dedup,
            semantic_threshold=sem_threshold,
        )

        # Enqueue approved platform outputs into the publish queue.
        if queue:
            from .publishers.base import PublishJob, PublishStatus
            enqueued = 0
            for entry in all_results:
                item: SourceItem = entry["item"]
                results = entry["results"]
                for platform in enqueue_platforms:
                    r = results.get(platform)
                    if not r or not r.get("ok") or r.get("skipped"):
                        continue
                    md_path = Path(r["path"])
                    payload, plain = _load_payload_for_publish(md_path)
                    if not plain.strip():
                        continue
                    job = PublishJob(
                        platform=platform,
                        source_id=item.source_id,
                        source_kind=item.source_kind,
                        title=item.title,
                        payload=payload,
                        payload_text=plain,
                        status=PublishStatus.GENERATED,
                    )
                    queue.enqueue(job)
                    enqueued += 1
            print("-" * 70, file=sys.stderr)
            print(f"Enqueued {enqueued} job(s) into publish queue "
                  f"(status=generated, awaiting approval).", file=sys.stderr)
            print(f"Run `python -m comet_repurposer queue` to review.",
                  file=sys.stderr)
    finally:
        dedup.close()
        if queue:
            queue.close()

    print("-" * 70, file=sys.stderr)
    print(f"Done. Output: {cfg.output_root}", file=sys.stderr)
    print(f"Log    : {cfg.log_path}", file=sys.stderr)
    return 0


def cmd_queue(args, cfg: RepurposeConfig) -> int:
    """List jobs in the publish queue."""
    from .publishers.base import QueueStore, PublishStatus
    queue = QueueStore(cfg.publish_queue_db_path)
    try:
        status = PublishStatus(args.status) if args.status else None
        jobs = queue.list_by_status(status=status, platform=args.platform, limit=args.limit)
        if not jobs:
            print("Queue is empty.")
            return 0
        print(f"{'ID':>4}  {'Platform':<10}  {'Status':<10}  {'Scheduled':<20}  Title")
        print("-" * 90)
        for j in jobs:
            sched = datetime.fromtimestamp(j.scheduled_at, tz=timezone.utc).isoformat() \
                if j.scheduled_at else "-"
            print(f"{j.id:>4}  {j.platform:<10}  {j.status.value:<10}  {sched:<20}  {j.title[:50]}")
        # Status counts
        counts = queue.count_by_status(platform=args.platform)
        print("\nStatus counts:")
        for s, n in sorted(counts.items()):
            print(f"  {s:<12} {n}")
    finally:
        queue.close()
    return 0


def cmd_approve(args, cfg: RepurposeConfig) -> int:
    """1-click approval: move jobs from generated -> approved and assign
    optimal scheduled_at."""
    from .publishers.base import QueueStore, PublishStatus
    from .publishers.scheduler import OptimalScheduler
    queue = QueueStore(cfg.publish_queue_db_path)
    try:
        # Build scheduler
        scheduler = OptimalScheduler(
            slots_by_platform={
                "linkedin": cfg.linkedin_optimal_slots,
                "x": cfg.x_optimal_slots,
            },
            min_gap_hours=cfg.publish_min_gap_hours,
        )

        # Resolve target job IDs
        if args.all:
            jobs = queue.list_by_status(status=PublishStatus.GENERATED,
                                         platform=args.platform, limit=1000)
        else:
            jobs = []
            for jid in args.job_ids:
                j = queue.get(int(jid))
                if not j:
                    print(f"Job {jid} not found.", file=sys.stderr)
                    continue
                jobs.append(j)

        if not jobs:
            print("No jobs to approve.", file=sys.stderr)
            return 1

        # Find last published_at per platform to enforce min_gap
        from collections import defaultdict
        last_published: dict = {}
        published_jobs = queue.list_by_status(status=PublishStatus.PUBLISHED, limit=1000)
        for pj in published_jobs:
            if pj.published_at and (pj.platform not in last_published
                                     or pj.published_at > last_published[pj.platform]):
                last_published[pj.platform] = pj.published_at

        from datetime import datetime, timezone
        approved_count = 0
        for j in jobs:
            if j.status != PublishStatus.GENERATED:
                print(f"  ! Job {j.id} is '{j.status.value}', skipping.", file=sys.stderr)
                continue
            last_dt = None
            if j.platform in last_published:
                last_dt = datetime.fromtimestamp(last_published[j.platform], tz=timezone.utc)
            next_dt = scheduler.enforce_min_gap(last_dt, j.platform)
            j.status = PublishStatus.APPROVED
            j.scheduled_at = next_dt.timestamp()
            queue.update(j)
            approved_count += 1
            print(f"  + Approved job {j.id} ({j.platform}) -> "
                  f"{next_dt.isoformat()}")
        print(f"\nApproved {approved_count} job(s). "
              f"Run `python -m comet_repurposer publish --dry-run` to preview.",
              file=sys.stderr)
    finally:
        queue.close()
    return 0


def cmd_publish(args, cfg: RepurposeConfig) -> int:
    """Publish approved+scheduled jobs to their platforms."""
    from .publishers.base import (
        QueueStore, kill_switch_active, PublishStatus,
    )
    # Kill switch check
    if kill_switch_active(cfg.kill_switch_path) and not args.dry_run:
        print(f"KILL SWITCH active at {cfg.kill_switch_path}. "
              f"Refusing to publish. Run `python -m comet_repurposer unkill` "
              f"to clear it.", file=sys.stderr)
        return 1

    # Default to dry-run unless --for-real is passed
    if not args.for_real:
        dry_run = True
        print("[DRY RUN] No real API calls will be made.", file=sys.stderr)
    else:
        dry_run = False
        if cfg.publish_dry_run_default and not args.i_know:
            print("Refusing to publish for real without --i-know flag "
                  "(safety belt). Re-run with --for-real --i-know.",
                  file=sys.stderr)
            return 1

    queue = QueueStore(cfg.publish_queue_db_path)
    try:
        jobs = queue.list_ready_to_publish()
        if not jobs:
            print("No jobs ready to publish.")
            return 0
        print(f"Publishing {len(jobs)} job(s) "
              f"({'dry-run' if dry_run else 'REAL'})", file=sys.stderr)
        print("-" * 70, file=sys.stderr)
        for j in jobs:
            try:
                publisher = _build_publisher(j.platform, cfg, dry_run=dry_run)
                updated = publisher.publish(j)
                queue.update(updated)
                if updated.status == PublishStatus.PUBLISHED:
                    print(f"  + [{j.platform}] job {j.id} -> "
                          f"post_id={updated.platform_post_id} "
                          f"({updated.title[:50]})")
                else:
                    print(f"  ! [{j.platform}] job {j.id} FAILED: "
                          f"{updated.error}")
            except Exception as exc:
                j.status = PublishStatus.FAILED
                j.error = f"publisher error: {exc}"
                queue.update(j)
                print(f"  ! [{j.platform}] job {j.id} EXCEPTION: {exc}",
                      file=sys.stderr)
    finally:
        queue.close()
    return 0


def cmd_reject(args, cfg: RepurposeConfig) -> int:
    from .publishers.base import QueueStore, PublishStatus
    queue = QueueStore(cfg.publish_queue_db_path)
    try:
        for jid in args.job_ids:
            j = queue.get(int(jid))
            if not j:
                print(f"Job {jid} not found.", file=sys.stderr)
                continue
            j.status = PublishStatus.REJECTED
            queue.update(j)
            print(f"  - Rejected job {jid}")
    finally:
        queue.close()
    return 0


def cmd_kill(args, cfg: RepurposeConfig) -> int:
    from .publishers.base import activate_kill_switch
    activate_kill_switch(cfg.kill_switch_path, reason=args.reason or "manual")
    print(f"Kill switch ACTIVATED at {cfg.kill_switch_path}", file=sys.stderr)
    print("All future publish calls will refuse to run until you clear it.",
          file=sys.stderr)
    return 0


def cmd_unkill(args, cfg: RepurposeConfig) -> int:
    from .publishers.base import deactivate_kill_switch
    deactivate_kill_switch(cfg.kill_switch_path)
    print(f"Kill switch cleared at {cfg.kill_switch_path}", file=sys.stderr)
    return 0


def cmd_auth_linkedin(args, cfg: RepurposeConfig) -> int:
    """Run the LinkedIn OAuth flow interactively."""
    from .publishers.linkedin import run_linkedin_oauth_flow
    client_id = args.client_id or cfg.linkedin_credentials.get("client_id", "")
    client_secret = args.client_secret or cfg.linkedin_credentials.get("client_secret", "")
    if not client_id or not client_secret:
        print("LinkedIn client_id and client_secret required.")
        print("Pass --client-id and --client-secret, or set LINKEDIN_CLIENT_ID "
              "and LINKEDIN_CLIENT_SECRET in your .env first.", file=sys.stderr)
        return 1

    port = args.port or 8080
    print(f"Starting OAuth flow on http://localhost:{port}/callback ...")
    result = run_linkedin_oauth_flow(client_id, client_secret,
                                     redirect_port=port,
                                     open_browser=not args.no_browser)
    print("\n=== LinkedIn credentials obtained ===")
    print(f"LINKEDIN_ACCESS_TOKEN={result['access_token']}")
    print(f"LINKEDIN_ACCESS_TOKEN_EXPIRES_AT={result['access_token_expires_at']}")
    print(f"LINKEDIN_REFRESH_TOKEN={result['refresh_token']}")
    print(f"LINKEDIN_REFRESH_TOKEN_EXPIRES_AT={result['refresh_token_expires_at']}")
    print(f"LINKEDIN_PERSON_ID={result['person_id']}")
    print("\nCopy these into your .env file. Then run:")
    print("  python -m comet_repurposer queue   # to see pending posts")
    return 0


# ---------------------------------------------------------------------------
# Argparse setup
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="comet-repurposer",
        description="Repurpose comet_riobamba content + publish to social platforms.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # generate
    pg = sub.add_parser("generate", help="Read sources and produce drafts per platform.")
    pg.add_argument("--source", default="latest",
                    choices=["all", "latest", "social_content", "published_posts", "ebook", "research_agenda"])
    pg.add_argument("--platforms", default=",".join(ALL_PLATFORMS))
    pg.add_argument("--limit", type=int, default=5)
    pg.add_argument("--lang", choices=["en", "es"], default=None)
    pg.add_argument("--force", action="store_true")
    pg.add_argument("--project-root", default=None)
    pg.add_argument("--dry-run", action="store_true", help="List items without calling LLM.")
    pg.add_argument("--enqueue-linkedin", action="store_true",
                    help="Also enqueue LinkedIn draft into publish queue.")
    pg.add_argument("--enqueue-x", action="store_true",
                    help="Also enqueue X/Twitter draft into publish queue.")
    pg.add_argument("--enqueue-twitter", action="store_true",
                    help="Alias for --enqueue-x.")
    pg.add_argument("--semantic-dedup", action="store_true", default=True,
                    help="Skip items that are semantically similar to ones already "
                         "processed (default: ON).")
    pg.add_argument("--no-semantic-dedup", dest="semantic_dedup", action="store_false",
                    help="Disable semantic deduplication; process every item independently.")
    pg.add_argument("--semantic-threshold", type=float, default=0.20,
                    help="Similarity threshold for semantic dedup (0.0-1.0). "
                         "Default 0.20 for lexical TF-IDF mode, 0.85 when "
                         "embeddings are configured. Lower = more aggressive "
                         "skipping.")
    pg.set_defaults(func=cmd_generate)

    # queue
    pq = sub.add_parser("queue", help="List jobs in the publish queue.")
    pq.add_argument("--status", default=None,
                    choices=["generated", "approved", "scheduled", "published", "failed", "rejected", "cancelled"])
    pq.add_argument("--platform", default=None)
    pq.add_argument("--limit", type=int, default=100)
    pq.add_argument("--project-root", default=None)
    pq.set_defaults(func=cmd_queue)

    # approve
    pa = sub.add_parser("approve", help="Approve generated jobs (1-click gate).")
    pa.add_argument("job_ids", nargs="*", help="Job IDs to approve.")
    pa.add_argument("--all", action="store_true", help="Approve all 'generated' jobs.")
    pa.add_argument("--platform", default=None, help="Limit --all to a platform.")
    pa.add_argument("--project-root", default=None)
    pa.set_defaults(func=cmd_approve)

    # reject
    pr = sub.add_parser("reject", help="Reject generated jobs (won't publish).")
    pr.add_argument("job_ids", nargs="+", help="Job IDs to reject.")
    pr.add_argument("--project-root", default=None)
    pr.set_defaults(func=cmd_reject)

    # publish
    pp = sub.add_parser("publish", help="Publish approved jobs to platforms.")
    pp.add_argument("--dry-run", action="store_true", help="Preview without API calls (default).")
    pp.add_argument("--for-real", action="store_true", help="Actually publish (requires --i-know too).")
    pp.add_argument("--i-know", action="store_true", help="Acknowledge the safety belt.")
    pp.add_argument("--project-root", default=None)
    pp.set_defaults(func=cmd_publish)

    # kill switch
    pk = sub.add_parser("kill", help="Activate emergency kill switch.")
    pk.add_argument("--reason", default=None)
    pk.add_argument("--project-root", default=None)
    pk.set_defaults(func=cmd_kill)

    puk = sub.add_parser("unkill", help="Clear the kill switch.")
    puk.add_argument("--project-root", default=None)
    puk.set_defaults(func=cmd_unkill)

    # auth-linkedin
    pl = sub.add_parser("auth-linkedin", help="Run LinkedIn OAuth flow (first-time setup).")
    pl.add_argument("--client-id", default=None)
    pl.add_argument("--client-secret", default=None)
    pl.add_argument("--port", type=int, default=8080)
    pl.add_argument("--no-browser", action="store_true")
    pl.add_argument("--project-root", default=None)
    pl.set_defaults(func=cmd_auth_linkedin)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Load config for commands that need it
    project_root = Path(args.project_root) if getattr(args, "project_root", None) else None
    try:
        cfg = RepurposeConfig.from_env(
            project_root=project_root,
            platforms=_parse_platforms(getattr(args, "platforms", ",".join(ALL_PLATFORMS))),
            language=getattr(args, "lang", None),
        )
        cfg.ensure_dirs()
    except RuntimeError as exc:
        # For commands that don't strictly need LLM providers (queue, approve,
        # publish, kill, unkill, auth-linkedin), allow proceeding with a
        # minimal config.
        if getattr(args, "command", None) in {"queue", "approve", "reject",
                                               "publish", "kill", "unkill",
                                               "auth-linkedin"}:
            cfg = RepurposeConfig.__new__(RepurposeConfig)
            cfg.project_root = Path(project_root or ".").resolve()
            cfg.publish_queue_db_path = cfg.project_root / "data" / "publish_queue.db"
            cfg.kill_switch_path = cfg.project_root / "data" / "KILL_SWITCH"
            cfg.publish_dry_run_default = True
            cfg.publish_min_gap_hours = 2
            cfg.linkedin_optimal_slots = ["09:00", "12:00", "17:00"]
            cfg.x_optimal_slots = ["08:00", "12:00", "18:00", "21:00"]
            # Reload publisher creds from env without requiring LLM keys
            import os
            from dotenv import load_dotenv
            env_path = cfg.project_root / ".env"
            if env_path.exists():
                load_dotenv(env_path, override=True)
            cfg.linkedin_credentials = {
                "client_id": os.getenv("LINKEDIN_CLIENT_ID", ""),
                "client_secret": os.getenv("LINKEDIN_CLIENT_SECRET", ""),
                "access_token": os.getenv("LINKEDIN_ACCESS_TOKEN", ""),
                "access_token_expires_at": os.getenv("LINKEDIN_ACCESS_TOKEN_EXPIRES_AT", ""),
                "refresh_token": os.getenv("LINKEDIN_REFRESH_TOKEN", ""),
                "refresh_token_expires_at": os.getenv("LINKEDIN_REFRESH_TOKEN_EXPIRES_AT", ""),
                "person_id": os.getenv("LINKEDIN_PERSON_ID", ""),
            }
            cfg.twitter_credentials = {
                "api_key": os.getenv("TWITTER_API_KEY", ""),
                "api_key_secret": os.getenv("TWITTER_API_KEY_SECRET", ""),
                "access_token": os.getenv("TWITTER_ACCESS_TOKEN", ""),
                "access_token_secret": os.getenv("TWITTER_ACCESS_TOKEN_SECRET", ""),
                "bearer_token": os.getenv("TWITTER_BEARER_TOKEN", ""),
            }
            cfg.request_timeout = 30.0
            cfg.ensure_dirs = lambda: None
            # Re-resolve output paths needed by some commands
            cfg.output_root = cfg.project_root / "exports" / "social_repurpose"
            cfg.log_path = cfg.project_root / "logs" / "repurpose.jsonl"
        else:
            raise

    return args.func(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
