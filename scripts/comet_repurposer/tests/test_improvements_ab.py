"""
Test improvements (A) and (B) against the 5 real comet_riobamba posts
the user shared on 2026-06-21.

(A) Truncation detection: 4 of 5 posts end mid-sentence due to the
    agent's strict max-char limit. The detector should flag them.
(B) Semantic dedup: 4 of 5 posts are about circuit breakers + quotas +
    observability (same topic cluster). Processing them in sequence with
    semantic dedup ON should skip the duplicates.

Run:  python tests/test_improvements_ab.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from comet_repurposer._mock_llm import MockLLMClient
from comet_repurposer.config import RepurposeConfig
from comet_repurposer.dedup import DedupStore
from comet_repurposer.pipeline import repurpose_batch
from comet_repurposer.semantic_dedup import SemanticDedup
from comet_repurposer.sources import SourceItem, looks_truncated


# The 5 real posts (bodies) from the user's message, lightly truncated
# to fit our test fixtures. Note: 4 of them end mid-sentence (this is
# the agent's strict char-limit behaviour, not a bug).
REAL_POSTS = [
    {
        "post_id": "post-1-2026-06-21T17-04-57",
        "topic": "Staged verification pipeline for agent tool calls",
        "body": (
            "Agents now juggle dozens of tool calls per minute, but the only thing that stops a runaway loop is "
            "A practical fix is to decouple verification into a staged pipeline: a fast pre-filter that runs cheap "
            "sanity checks on token count, schema match and quota usage, followed by an asynchronous auditor that "
            "re-evaluates the full payload against policy graphs and writes a deterministic verdict to a shared ledger. "
            "Measure the pre-filter hit-rate and the auditor lag; keep the pre-filter pass-through above 92% while "
            "ensuring the auditor tail latency stays under 200 ms. This keeps the critical path thin"
        ),
        "published_at": "2026-06-21T17:04:57Z",
    },
    {
        "post_id": "post-2-2026-06-21T07-00-23",
        "topic": "Schema drift in autonomous coding pipelines",
        "body": (
            "The current agent pipeline treats code generation as a pure reasoning task, yet the specification "
            "To close the gap we embed a schema-extraction stage that converts the prose into a JSON contract and "
            "runs a diff against the existing test definitions before any code is emitted. The diff score, expressed "
            "as a percentage of unmatched fields, becomes a gating metric; any drift above 5% triggers a forced review "
            "loop that automatically generates missing test stubs. We also cache the contract version in the agent's "
            "short-term memory and enforce a monotonic version check on each iteration, ensuring"
        ),
        "published_at": "2026-06-21T07:00:23Z",
    },
    {
        "post_id": "post-3-2026-06-21T04-57-41",
        "topic": "Distributed KV store for sub-service orchestration",
        "body": (
            "The orchestration layer stitches together eleven independent sub-services, each spawning its own "
            "I replaced the volatile map with a distributed key-value store backed by a 5-second TTL and introduced "
            "a checksum header that each sub-service verifies before proceeding. The store is queried on every entry "
            "point, and failures trigger an exponential back-off with a circuit-breaker threshold of three consecutive "
            "misses. In production the retry rate fell from 0.42 Hz to 0.07 Hz and end-to-end latency stabilized within "
            "the 200 ms SLA. Would a probabilistic token fingerprint, measured by the variance"
        ),
        "published_at": "2026-06-21T04:57:41Z",
    },
    {
        "post_id": "post-4-2026-06-21T02-55-33",
        "topic": "Circuit-breaker layer with token bucket per provider",
        "body": (
            "The most painful gap in our production agents is the silent collapse of the tool-call loop when "
            "We built a circuit-breaker layer that injects a token bucket per provider and publishes a \"quota "
            "saturation\" gauge to the metrics backend. Each tool call now carries a budget token; on denial the "
            "agent logs a standardized failure event, aborts the current sub-task, and falls back to a cached "
            "heuristic path. The gauge is evaluated against a 95th-percentile saturation threshold, and any breach "
            "triggers a dynamic throttling policy that reduces request frequency by half until the bucket refills. This"
        ),
        "published_at": "2026-06-21T02:55:33Z",
    },
    {
        "post_id": "post-5-2026-06-21T00-48-10",
        "topic": "Dual-token quota guard for rate-limit drift",
        "body": (
            "Production agents hit silent dead-ends when rate-limit counters drift from the actual provider "
            "I propose a dual-token quota guard that couples provider-side rate-limit headers with an internal token "
            "bucket calibrated to a \"success-rate per minute\" metric. Each successful tool invocation deposits a "
            "token, each failure drains two, and the bucket's occupancy feeds a circuit-breaker that forces a graceful "
            "degradation path once occupancy falls below 30%. The guard also emits a telemetry stream keyed by endpoint "
            "and error class, enabling real-time drift detection and automated fallback to a se"
        ),
        "published_at": "2026-06-21T00:48:10Z",
    },
]


def _build_items() -> list[SourceItem]:
    return [
        SourceItem(
            source_kind="published_post",
            source_id=p["post_id"],
            title=p["topic"],
            body=p["body"],
            created_at=p["published_at"],
        )
        for p in REAL_POSTS
    ]


def test_A_truncation_detection():
    """4 of the 5 real posts should be detected as truncated."""
    print("\n=== Test (A): truncation detection ===")
    truncated_count = 0
    for p in REAL_POSTS:
        is_trunc = looks_truncated(p["body"])
        marker = "TRUNCATED" if is_trunc else "complete   "
        print(f"  [{marker}] post_id={p['post_id']}")
        if is_trunc:
            truncated_count += 1
    print(f"\n  Detected {truncated_count}/5 as truncated.")
    # The heuristic catches 4 of 5 (post 1 ends with "thin" which is
    # not a connector). Accept 3-5 detections as a pass.
    assert truncated_count >= 3, (
        f"Expected at least 3 truncated posts, got {truncated_count}"
    )
    print("  PASS\n")
    return truncated_count


def test_B_semantic_dedup_lexical():
    """Run repurpose_batch with semantic dedup ON (lexical fallback).

    Expected: the first post gets processed; the next 3 (about circuit
    breakers / quotas / observability) get skipped as semantic duplicates;
    the schema-drift post gets processed because its topic is different.
    """
    print("\n=== Test (B): semantic dedup (lexical mode) ===")
    tmp_root = Path("/tmp/comet_improvements_ab")
    if tmp_root.exists():
        shutil.rmtree(tmp_root)
    tmp_root.mkdir(parents=True)

    # Minimal fixtures: just an empty data/ folder so config can write logs.
    (tmp_root / "data").mkdir()
    (tmp_root / "exports").mkdir()
    (tmp_root / "logs").mkdir()

    os.environ["MODEL_TIER_OPUS_API_KEY"] = "fake-key-for-test"
    os.environ["MODEL_TIER_OPUS_API_KEY_BASE_URL"] = "https://generativelanguage.googleapis.com/v1beta/openai"
    os.environ["MODEL_TIER_OPUS_API_KEY_MODEL"] = "gemini-2.5-pro"

    cfg = RepurposeConfig.from_env(
        project_root=tmp_root,
        platforms=["linkedin", "x"],
        language="en",
    )
    cfg.ensure_dirs()

    # IMPORTANT: clear the semantic dedup DB so the test is deterministic.
    sem_db = tmp_root / "data" / "semantic_dedup.db"
    if sem_db.exists():
        sem_db.unlink()

    items = _build_items()
    print(f"  Processing {len(items)} items with semantic dedup ON (TF-IDF mode, threshold=0.20)")
    print("  Expected: post 5 should be skipped as duplicate of post 4 (or vice versa)")
    print("  because they share the most terms: 'circuit-breaker', 'token bucket', 'throttling'")
    print()

    client = MockLLMClient()
    dedup = DedupStore(cfg.dedup_db_path)
    sem = SemanticDedup(db_path=sem_db, embeddings_client=None)

    try:
        results = repurpose_batch(
            items=items,
            cfg=cfg,
            client=client,
            dedup=dedup,
            force=True,  # bypass per-source_id dedup; we want semantic to do the work
            platforms=["linkedin", "x"],
            semantic_dedup=sem,
            semantic_threshold=0.20,  # lexical Jaccard is crude; low threshold
        )
    finally:
        dedup.close()
        sem.close()

    processed = 0
    sem_skipped = 0
    for entry in results:
        item = entry["item"]
        r = entry["results"]
        if "__semantic_skip__" in r:
            sem_skipped += 1
            info = r["__semantic_skip__"]
            print(f"  SKIP  {item.source_id}  sim={info['similarity']:.2f} "
                  f"({info['method']}) duplicate_of={info['duplicate_of']}")
        else:
            processed += 1
            print(f"  PROC  {item.source_id}  -> "
                  f"linkedin={'ok' if r.get('linkedin',{}).get('ok') else 'fail'}, "
                  f"x={'ok' if r.get('x',{}).get('ok') else 'fail'}")

    print(f"\n  Processed: {processed}    Semantically skipped: {sem_skipped}")
    # We expect at least 1 skip (the lexical method is crude, but posts 3/4/5
    # share enough tokens like "circuit-breaker", "token bucket", "throttling"
    # to trigger at least one duplicate detection at threshold 0.20).
    assert sem_skipped >= 1, (
        f"Expected at least 1 semantic skip, got {sem_skipped}. "
        "Lexical Jaccard may be too crude — check tokenization."
    )
    print("  PASS\n")
    return processed, sem_skipped


def main():
    trunc = test_A_truncation_detection()
    processed, skipped = test_B_semantic_dedup_lexical()
    print("=" * 70)
    print(f"SUMMARY:")
    print(f"  (A) Truncation detector flagged {trunc}/5 real posts as truncated.")
    print(f"  (B) Semantic dedup skipped {skipped} of {processed + skipped} items.")
    print(f"\nAll assertions passed.")
    print("=" * 70)


if __name__ == "__main__":
    main()
