# -*- coding: utf-8 -*-
"""Tests for core/tracer.py — Span tracing with append-only JSONL output."""

import json
from unittest.mock import patch

import pytest


def test_span_created_with_name_and_attrs():
    from core.tracer import Span
    span = Span("test_span", post_id="abc", score=42)
    assert span.name == "test_span"
    assert span.attrs == {"post_id": "abc", "score": 42}


def test_span_set_stores_extra_attributes():
    from core.tracer import Span
    span = Span("test_span", post_id="abc")
    span.set("outcome", "published")
    span.set("length", 120)
    assert span._extra == {"outcome": "published", "length": 120}


def test_span_writes_jsonl_record_on_exit(tmp_path, monkeypatch):
    from core.tracer import Span
    traces_dir = tmp_path / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("core.tracer.TRACES_DIR", traces_dir)

    with Span("phase_b_reply", post_id="p1", comment_id="c1") as span:
        span.set("outcome", "published")

    today = __import__("datetime").datetime.now().strftime("%Y%m%d")
    trace_file = traces_dir / f"phase_b_{today}.jsonl"
    assert trace_file.exists()

    lines = trace_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["span"] == "phase_b_reply"
    assert record["post_id"] == "p1"
    assert record["comment_id"] == "c1"
    assert record["outcome"] == "published"
    assert "latency_ms" in record
    assert isinstance(record["latency_ms"], int)


def test_span_captures_exception_does_not_suppress(tmp_path, monkeypatch):
    from core.tracer import Span
    traces_dir = tmp_path / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("core.tracer.TRACES_DIR", traces_dir)

    with pytest.raises(ValueError, match="test error"):
        with Span("failing_span") as span:
            raise ValueError("test error")

    today = __import__("datetime").datetime.now().strftime("%Y%m%d")
    trace_file = traces_dir / f"phase_b_{today}.jsonl"
    assert trace_file.exists()
    lines = trace_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["span"] == "failing_span"
    assert "error" in record
    assert "ValueError" in record["error"]


def test_span_records_latency(tmp_path, monkeypatch):
    from core.tracer import Span
    traces_dir = tmp_path / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("core.tracer.TRACES_DIR", traces_dir)

    with Span("latency_test") as span:
        span.set("result", "ok")

    today = __import__("datetime").datetime.now().strftime("%Y%m%d")
    trace_file = traces_dir / f"phase_b_{today}.jsonl"
    record = json.loads(trace_file.read_text(encoding="utf-8").strip().splitlines()[0])
    assert record["latency_ms"] >= 0


def test_span_does_not_crash_on_write_failure(tmp_path, monkeypatch):
    """Span must not propagate exceptions from trace file writes.
    
    When _trace_path or the file write inside Span.__exit__ fails (e.g.
    permission error, disk full), the exception is caught and logged
    at debug level — it must NOT propagate to the caller.
    """
    from core.tracer import Span
    traces_dir = tmp_path / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("core.tracer.TRACES_DIR", traces_dir)

    with patch("builtins.open", side_effect=OSError("disk full")):
        with Span("should_not_crash"):
            pass
    # No exception should reach here

