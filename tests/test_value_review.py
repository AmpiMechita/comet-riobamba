"""Tests for core/value_review.py — weekly value review pipeline."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import core.value_review as vr


@pytest.fixture
def review_dir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(vr, "REVIEW_DIR", d)
    return d


@pytest.fixture
def no_events(monkeypatch):
    monkeypatch.setattr(vr, "get_value_events_since", lambda since: [])


@pytest.fixture
def some_events(monkeypatch):
    events = [
        {
            "id": "e1", "timestamp": "2026-09-17T10:00:00",
            "post_id": "p1", "comment_id": "c1",
            "clasificacion_valor": "resolvio_problema",
            "tema": "agents", "tipo_problema": "latency",
        },
        {
            "id": "e2", "timestamp": "2026-09-17T11:00:00",
            "post_id": "p2", "comment_id": "c2",
            "clasificacion_valor": "aporte_util",
            "tema": "guardrails", "tipo_problema": "safety",
        },
    ]
    monkeypatch.setattr(vr, "get_value_events_since", lambda since: events)
    return events


class TestSummarizeEvents:
    def test_empty(self):
        out = vr._summarize_events([])
        assert "No high-value events" in out

    def test_counts_classifications(self):
        events = [
            {"clasificacion_valor": "resolvio_problema", "tema": "t1", "tipo_problema": "x"},
            {"clasificacion_valor": "aporte_util", "tema": "t1", "tipo_problema": "y"},
            {"clasificacion_valor": "aporte_util", "tema": "t2", "tipo_problema": "y"},
        ]
        out = vr._summarize_events(events)
        assert "Total high-value events: 3" in out
        assert "resolvio_problema" in out
        assert "aporte_util" in out


class TestRunValueReview:
    @pytest.mark.asyncio
    async def test_no_events_returns_none(self, review_dir: Path, no_events):
        llm = AsyncMock()
        result = await vr.run_value_review(llm, days=7)
        assert result is None
        llm.generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self, review_dir: Path, some_events):
        llm = AsyncMock()
        llm.generate.side_effect = RuntimeError("boom")
        result = await vr.run_value_review(llm, days=7)
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_json_response_writes_file(self, review_dir: Path, some_events):
        payload = {
            "analysis_summary": "Two useful events.",
            "top_3_topics_resolved": ["agents", "guardrails"],
            "improvement_opportunities": ["more depth on latency"],
            "content_structure_proposals": ["new series"],
            "prompt_adjustments": ["tighten reply prompt"],
        }
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value=json.dumps(payload))
        result = await vr.run_value_review(llm, days=7)
        assert result is not None
        path = Path(result)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "Two useful events." in content
        assert "agents" in content

    @pytest.mark.asyncio
    async def test_markdown_fence_stripped(self, review_dir: Path, some_events):
        payload = {
            "analysis_summary": "Fenced json ok.",
            "top_3_topics_resolved": [],
            "improvement_opportunities": [],
            "content_structure_proposals": [],
            "prompt_adjustments": [],
        }
        fenced = "```json\\n" + json.dumps(payload) + "\\n```"
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value=fenced)
        result = await vr.run_value_review(llm, days=7)
        assert result is not None
        content = Path(result).read_text(encoding="utf-8")
        assert "Fenced json ok." in content

    @pytest.mark.asyncio
    async def test_invalid_json_still_writes_file(self, review_dir: Path, some_events):
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value="not json at all")
        result = await vr.run_value_review(llm, days=7)
        assert result is not None
        content = Path(result).read_text(encoding="utf-8")
        assert "not json at all" in content
        assert "Raw Response" in content

