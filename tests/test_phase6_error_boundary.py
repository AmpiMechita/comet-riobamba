import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.update({
    "DASHSCOPE_API_KEY": "sk-test",
    "OLLAMA_BASE_URL": "http://localhost:11434",
    "MOLTBOOK_API_KEY": "sk-test",
    "MOLTBOOK_BASE_URL": "http://localhost:8080",
})

logging.basicConfig(level=logging.INFO, format="%(levelname)s|%(name)s|%(message)s")

from phases.deps import PhaseBDeps, PhaseCDeps, PhaseADeps
from phases.phase_b import PhaseB
from phases.engagement import PhaseCEngagement
from phases.phase_a_content import PhaseAContentGeneration
from phases.phase_c_analytics import PhaseCAnalytics
from services.metrics import snapshot, incr


class FailingModel:
    async def generate(self, **kw):
        raise RuntimeError("induced error for testing")


def test_phase_b_error_boundary():
    """The error boundary only catches unhandled exceptions.
    Normal API errors (e.g., None client) are caught internally.
    To test the boundary, we monkeypatch execute() to raise."""
    deps = PhaseBDeps(
        model_cascade=FailingModel(),
        moltbook_client=None,
        behavior_cfg={},
        agent_name="TEST",
    )
    pb = PhaseB(deps=deps)
    # Monkeypatch to raise inside execute to trigger the decorator
    original = pb._execute_feed_replies
    async def broken(*a, **kw):
        raise RuntimeError("induced unhandled error in Phase B")
    pb._execute_feed_replies = broken
    result = asyncio.run(pb.execute())
    assert result["success"] is False
    assert result["replies_published"] == 0
    assert result["feed_replies"] == []
    assert result["own_post_replies"] == []
    print("  Phase B: error boundary caught unhandled exception, returned safe fallback")


def test_phase_c_engagement_error_boundary():
    """Phase CE ngagement normally handles errors internally.
    To test the boundary, we monkeypatch to raise."""
    deps = PhaseCDeps(
        model_cascade=FailingModel(),
        moltbook_client=None,
        write_policy=None,
    )
    eng = PhaseCEngagement(deps=deps)
    # Monkeypatch responder to raise inside execute
    original_extract = eng.responder.extract_posts_with_activity
    def broken(*a, **kw):
        raise RuntimeError("induced unhandled error in Phase C engagement")
    eng.responder.extract_posts_with_activity = broken
    result = asyncio.run(eng.execute())
    assert result == []
    print("  Phase C engagement: error boundary caught unhandled exception, returned []")


def test_metrics_incremented():
    metrics = snapshot()
    assert metrics.get("phase_b_errors", 0) >= 1, f"phase_b_errors={metrics.get('phase_b_errors', 0)}"
    assert metrics.get("phase_c_engagement_errors", 0) >= 1, f"phase_c_engagement_errors={metrics.get('phase_c_engagement_errors', 0)}"
    print(f"  Metrics verified: phase_b_errors={metrics.get('phase_b_errors', 0)}, phase_c_engagement_errors={metrics.get('phase_c_engagement_errors', 0)}")


if __name__ == "__main__":
    test_phase_b_error_boundary()
    test_phase_c_engagement_error_boundary()
    test_metrics_incremented()
    print("ALL PHASE 6 ERROR BOUNDARY TESTS PASS")
