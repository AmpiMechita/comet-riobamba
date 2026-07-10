import os
import sys
import logging
from types import MethodType

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from phases.deps import PhaseBDeps
from phases.phase_b import PhaseB
from services.moltbook_api_client import MoltbookAPIClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

class DummyLLM:
    async def generate(self, prompt: str, **kwargs) -> str:
        prompt_preview = prompt[:160].replace("\n", " ")
        print(f"[DRY-RUN][LLM] prompt={prompt_preview!r}")
        return "DRY-RUN reply from COMET-RIOBAMBA"

api = MoltbookAPIClient()

def fake_create_comment(self, post_id=None, parent_id=None, content=None, **kwargs):
    print(
        f"[DRY-RUN][POST] would create_comment "
        f"post_id={post_id!r} parent_id={parent_id!r} content={content!r}"
    )
    return {
        "success": True,
        "already_existed": False,
        "dry_run": True,
        "id": "dry-run-comment-id",
        "error": None,
    }

api.create_comment = MethodType(fake_create_comment, api)

config = {
    "behavior": {
        "max_comments_per_post": 3,
        "delay_between_comments": 0,
    }
}

deps = PhaseBDeps(
    model_cascade=DummyLLM(),
    moltbook_client=api,
    behavior_cfg=config.get("behavior", {}),
    agent_name="COMET-RIOBAMBA",
)
phase = PhaseB(deps=deps)

async def run():
    result = await phase.execute()
    print(f"\nPhase B dry-run result: replies_published={result.get('replies_published')}")
    print(f"  feed_replies: {len(result.get('feed_replies', []))}")
    print(f"  own_post_replies: {len(result.get('own_post_replies', []))}")

import asyncio
asyncio.run(run())