"""
Smoke test: run the pipeline end-to-end with a mock LLM client and
fixture data that mirrors comet_riobamba's real output layout.

Run with:  python -m pytest tests/test_smoke.py -v
Or simply: python tests/test_smoke.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the package importable when running this file directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from comet_repurposer._mock_llm import MockLLMClient
from comet_repurposer.config import ALL_PLATFORMS, RepurposeConfig
from comet_repurposer.dedup import DedupStore
from comet_repurposer.pipeline import repurpose_one
from comet_repurposer.sources import iter_all_sources


FIXTURES = {
    "data/published_posts.json": [
        {
            "post_id": "f28da0d2-abcd-4321-9876-001122334455",
            "topic": "Session persistence patterns across 11 submolts",
            "published_at": "2026-06-20T14:30:00Z",
        },
        {
            "post_id": "9f307dc3-abcd-4321-9876-001122334456",
            "topic": "Autonomous coding doesn't fail on reasoning; it fails on schema drift between prose and checks",
            "published_at": "2026-06-21T09:15:00Z",
        },
    ],
    "exports/social_content/2026-06-20_silent_back-pressure.md": (
        "## Twitter Thread\n"
        "- Your agent's 'health score' might be lying to you...\n"
        "- A high success rate looks the same whether an endpoint is rate-limiting you or the network path is silently broken...\n"
        "- Pair success rates with fast-changing signals like TCP resets or ICMP reachability...\n\n"
        "## LinkedIn Post\n"
        "In the complex world of autonomous agents, a single 'health score' for tool calls can be dangerously misleading...\n"
    ),
    "exports/ebook_2026-06-15_agent-observability.md": (
        "# Agent Observability: A Field Guide\n\n"
        "Most agent health scores are success-rate in disguise. This ebook walks through\n"
        "the silent failure modes that success rate hides, and proposes a reference\n"
        "formula mixing success rate with fast-changing transport signals.\n\n"
        "## Chapter 1 - The dashboard lie\n"
        "A 99.7% success rate looks identical whether an endpoint is rate-limiting you\n"
        "or the network path is silently broken. The dashboard says green. The reality\n"
        "is silent back-pressure.\n"
    ),
    "data/research_agenda.json": {
        "open_questions": [],
        "pending_topics": [
            {
                "topic": "Observability gaps in long-running agent loops",
                "source": "research_agenda_update",
                "tags": ["observability", "monitoring", "agent-loops"],
                "covered": True,
            },
            {
                "topic": "Guardrails for autonomous posting agents",
                "source": "research_agenda_update",
                "tags": ["guardrails", "safety"],
                "covered": True,
            },
        ],
        "high_impact_threads": [],
        "new_terms": ["agent loop", "context window", "prompt injection"],
    },
}


def _build_fixture_project(tmp_root: Path) -> Path:
    for rel, content in FIXTURES.items():
        path = tmp_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_text(json.dumps(content, indent=2), encoding="utf-8")
    return tmp_root


def test_end_to_end(tmp_path: Path | None = None) -> None:
    tmp_path = tmp_path or Path("/tmp/comet_repurposer_smoke")
    if tmp_path.exists():
        for p in tmp_path.rglob("*"):
            if p.is_file():
                p.unlink()
        for p in reversed(list(tmp_path.rglob("*"))):
            if p.is_dir():
                p.rmdir()
    tmp_path.mkdir(parents=True, exist_ok=True)

    project_root = _build_fixture_project(tmp_path)

    # Patch the .env loading so we don't need real API keys.
    import os
    os.environ["MODEL_TIER_OPUS_API_KEY"] = "fake-key-for-test"
    os.environ["MODEL_TIER_OPUS_API_KEY_BASE_URL"] = "https://generativelanguage.googleapis.com/v1beta/openai"
    os.environ["MODEL_TIER_OPUS_API_KEY_MODEL"] = "gemini-2.5-pro"

    cfg = RepurposeConfig.from_env(
        project_root=project_root,
        platforms=ALL_PLATFORMS,
        language="en",
    )
    cfg.ensure_dirs()

    # Use the mock client instead of LLMClient.
    client = MockLLMClient()
    dedup = DedupStore(cfg.dedup_db_path)

    items = list(iter_all_sources(project_root))
    print(f"Found {len(items)} source item(s):")
    for i in items:
        print(f"  - [{i.source_kind}] {i.title}")
    assert items, "Expected at least one source item from fixtures"

    # Process the first item end-to-end.
    item = items[0]
    print(f"\nRepurposing: [{item.source_kind}] {item.title}")
    results = repurpose_one(item, cfg, client, dedup, force=True,
                            platforms=cfg.platforms)

    print("\nResults:")
    for platform, r in results.items():
        if r.get("ok") and not r.get("skipped"):
            print(f"  + {platform:10s} -> {r['path']}")
        elif r.get("skipped"):
            print(f"  ~ {platform:10s} skipped")
        else:
            print(f"  ! {platform:10s} ERROR: {r.get('error')}")

    # Verify outputs exist.
    out_dir = cfg.output_root
    md_files = list(out_dir.rglob("*.md"))
    print(f"\nGenerated {len(md_files)} markdown file(s):")
    for md in sorted(md_files):
        print(f"  - {md.relative_to(out_dir)}")

    assert len(md_files) >= 1, "Expected at least one .md output"

    # Show a sample of one of the outputs.
    sample = md_files[0]
    print(f"\n--- Sample: {sample.name} ---")
    print(sample.read_text(encoding="utf-8")[:1500])
    print("--- end sample ---\n")

    dedup.close()
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    test_end_to_end()
