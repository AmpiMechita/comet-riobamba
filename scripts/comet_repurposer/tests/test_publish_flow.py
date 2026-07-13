"""
End-to-end smoke test for generate -> enqueue -> approve -> publish (dry-run).

Uses the mock LLM client (no real API calls) and a fake publisher
config so we verify the entire pipeline without spending quota.

Run:  python tests/test_publish_flow.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from comet_repurposer._mock_llm import MockLLMClient
from comet_repurposer.config import ALL_PLATFORMS, RepurposeConfig
from comet_repurposer.dedup import DedupStore
from comet_repurposer.pipeline import repurpose_one
from comet_repurposer.publishers.base import (
    PublishJob, PublishStatus, QueueStore, kill_switch_active,
)
from comet_repurposer.publishers.linkedin import LinkedInPublisher
from comet_repurposer.publishers.twitter import TwitterPublisher
from comet_repurposer.publishers.scheduler import OptimalScheduler


FIXTURES = {
    "data/published_posts.json": [
        {
            "post_id": "f28da0d2-abcd-4321-9876-001122334455",
            "topic": "Session persistence patterns across 11 submolts",
            "published_at": "2026-06-20T14:30:00Z",
        },
    ],
    "exports/social_content/2026-06-20_silent_back-pressure.md": (
        "## Twitter Thread\n"
        "- Your agent's 'health score' might be lying to you...\n"
        "- A high success rate looks the same whether an endpoint is rate-limiting you or the network path is silently broken...\n\n"
        "## LinkedIn Post\n"
        "In the complex world of autonomous agents, a single 'health score' for tool calls can be dangerously misleading...\n"
    ),
}


def _build_project(tmp_root: Path) -> Path:
    for rel, content in FIXTURES.items():
        path = tmp_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_text(json.dumps(content, indent=2), encoding="utf-8")
    return tmp_root


def _cleanup(tmp_root: Path):
    if tmp_root.exists():
        import shutil
        shutil.rmtree(tmp_root)


def test_full_flow():
    tmp_root = Path("/tmp/comet_publish_smoke")
    _cleanup(tmp_root)
    tmp_root.mkdir(parents=True)

    project_root = _build_project(tmp_root)

    # Patch env so we don't need real LLM keys
    os.environ["MODEL_TIER_OPUS_API_KEY"] = "fake-key-for-test"
    os.environ["MODEL_TIER_OPUS_API_KEY_BASE_URL"] = "https://generativelanguage.googleapis.com/v1beta/openai"
    os.environ["MODEL_TIER_OPUS_API_KEY_MODEL"] = "gemini-2.5-pro"
    # Fake publisher creds so validation passes
    os.environ["LINKEDIN_CLIENT_ID"] = "fake_id"
    os.environ["LINKEDIN_CLIENT_SECRET"] = "fake_secret"
    os.environ["LINKEDIN_ACCESS_TOKEN"] = "fake_access"
    os.environ["LINKEDIN_PERSON_ID"] = "fake_person_123"
    os.environ["TWITTER_API_KEY"] = "fake_key"
    os.environ["TWITTER_API_KEY_SECRET"] = "fake_secret"
    os.environ["TWITTER_ACCESS_TOKEN"] = "fake_token"
    os.environ["TWITTER_ACCESS_TOKEN_SECRET"] = "fake_token_secret"

    cfg = RepurposeConfig.from_env(
        project_root=project_root,
        platforms=ALL_PLATFORMS,
        language="en",
    )
    cfg.ensure_dirs()

    # --- Stage 1: generate (with mock LLM) ---
    print("\n=== Stage 1: generate ===")
    client = MockLLMClient()
    dedup = DedupStore(cfg.dedup_db_path)

    from comet_repurposer.sources import iter_all_sources
    items = list(iter_all_sources(project_root))
    print(f"Found {len(items)} source item(s)")

    # Take the first item, generate linkedin + x drafts
    item = items[0]
    print(f"Repurposing: [{item.source_kind}] {item.title}")
    results = repurpose_one(item, cfg, client, dedup, force=True,
                            platforms=["linkedin", "x"])
    assert results["linkedin"]["ok"], f"LinkedIn generate failed: {results['linkedin']}"
    assert results["x"]["ok"], f"X generate failed: {results['x']}"
    print(f"  + linkedin -> {results['linkedin']['path']}")
    print(f"  + x        -> {results['x']['path']}")

    # --- Stage 2: enqueue into publish queue ---
    print("\n=== Stage 2: enqueue ===")
    queue = QueueStore(cfg.publish_queue_db_path)
    from comet_repurposer.cli import _load_payload_for_publish
    for platform in ("linkedin", "x"):
        md_path = Path(results[platform]["path"])
        payload, plain = _load_payload_for_publish(md_path)
        assert plain.strip(), f"Empty payload for {platform}"
        job = PublishJob(
            platform=platform,
            source_id=item.source_id,
            source_kind=item.source_kind,
            title=item.title,
            payload=payload,
            payload_text=plain,
            status=PublishStatus.GENERATED,
        )
        job_id = queue.enqueue(job)
        print(f"  + enqueued job {job_id} ({platform})")

    # --- Stage 3: approve (1-click gate) ---
    print("\n=== Stage 3: approve ===")
    scheduler = OptimalScheduler(
        slots_by_platform={
            "linkedin": cfg.linkedin_optimal_slots,
            "x": cfg.x_optimal_slots,
        },
        min_gap_hours=cfg.publish_min_gap_hours,
    )
    from datetime import datetime, timezone
    pending = queue.list_by_status(status=PublishStatus.GENERATED)
    print(f"  Found {len(pending)} pending jobs to approve")
    for j in pending:
        next_dt = scheduler.next_slot(j.platform)
        j.status = PublishStatus.APPROVED
        # In production we'd use next_dt; for the test we force 'now' so the
        # dry-run publish step can fire immediately.
        j.scheduled_at = datetime.now(timezone.utc).timestamp()
        queue.update(j)
        print(f"  + Approved job {j.id} ({j.platform}) -> "
              f"scheduled slot would be {next_dt.isoformat()} (forced to now for test)")

    # --- Stage 4: publish (dry-run) ---
    print("\n=== Stage 4: publish (dry-run) ===")
    ready = queue.list_ready_to_publish()
    assert ready, "Expected ready jobs after approval"
    print(f"  Found {len(ready)} job(s) ready to publish")

    for j in ready:
        if j.platform == "linkedin":
            pub = LinkedInPublisher(cfg.linkedin_credentials, dry_run=True)
        elif j.platform in ("x", "twitter"):
            pub = TwitterPublisher(cfg.twitter_credentials, dry_run=True)
        else:
            print(f"  ! unknown platform {j.platform}, skipping")
            continue
        updated = pub.publish(j)
        queue.update(updated)
        if updated.status == PublishStatus.PUBLISHED:
            print(f"  + [{j.platform}] job {j.id} -> "
                  f"post_id={updated.platform_post_id}")
        else:
            print(f"  ! [{j.platform}] job {j.id} FAILED: {updated.error}")
            raise AssertionError(f"Publish failed: {updated.error}")

    # --- Stage 5: kill switch ---
    print("\n=== Stage 5: kill switch ===")
    from comet_repurposer.publishers.base import (
        activate_kill_switch, deactivate_kill_switch,
    )
    activate_kill_switch(cfg.kill_switch_path, reason="test")
    assert kill_switch_active(cfg.kill_switch_path)
    print(f"  + Kill switch active at {cfg.kill_switch_path}")
    deactivate_kill_switch(cfg.kill_switch_path)
    assert not kill_switch_active(cfg.kill_switch_path)
    print(f"  + Kill switch cleared")

    # --- Final state ---
    print("\n=== Final queue state ===")
    counts = queue.count_by_status()
    for status, n in sorted(counts.items()):
        print(f"  {status}: {n}")

    dedup.close()
    queue.close()
    _cleanup(tmp_root)
    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    test_full_flow()
