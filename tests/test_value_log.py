"""Tests for core/value_log.py — JSONL event log."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import core.value_log as vl


@pytest.fixture
def log_path(tmp_path: Path, monkeypatch) -> Path:
    p = tmp_path / "value_log.jsonl"
    monkeypatch.setattr(vl, "VALUE_LOG_PATH", p)
    return p


def _event(**overrides) -> dict:
    base = {
        "id": "evt-1",
        "timestamp": "2026-09-17T12:00:00",
        "post_id": "p1",
        "comment_id": "c1",
        "clasificacion_valor": "aporte_util",
    }
    base.update(overrides)
    return base


class TestEnsureFile:
    def test_creates_file(self, log_path: Path):
        assert not log_path.exists()
        vl._ensure_file()
        assert log_path.exists()

    def test_idempotent(self, log_path: Path):
        vl._ensure_file()
        vl._ensure_file()
        assert log_path.read_text(encoding="utf-8") == ""


class TestLogValueEvent:
    def test_writes_jsonl(self, log_path: Path):
        vl.log_value_event(_event())
        content = log_path.read_text(encoding="utf-8").strip()
        assert content
        rec = json.loads(content)
        assert rec["id"] == "evt-1"
        assert rec["clasificacion_valor"] == "aporte_util"

    def test_missing_field_skips(self, log_path: Path):
        bad = _event()
        del bad["comment_id"]
        vl.log_value_event(bad)
        assert log_path.read_text(encoding="utf-8") == ""

    def test_multiple_appends(self, log_path: Path):
        vl.log_value_event(_event(id="a"))
        vl.log_value_event(_event(id="b"))
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["id"] == "a"
        assert json.loads(lines[1])["id"] == "b"


class TestGetValueEventsSince:
    def test_no_file_returns_empty(self, log_path: Path):
        assert vl.get_value_events_since(datetime.now()) == []

    def test_filters_by_timestamp(self, log_path: Path):
        vl.log_value_event(_event(id="old", timestamp="2026-09-01T00:00:00"))
        vl.log_value_event(_event(id="new", timestamp="2026-09-17T12:00:00"))
        cutoff = datetime(2026, 9, 15)
        events = vl.get_value_events_since(cutoff)
        assert len(events) == 1
        assert events[0]["id"] == "new"

    def test_invalid_json_line_skipped(self, log_path: Path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "not json" + chr(10) + json.dumps(_event(id="valid")) + chr(10),
            encoding="utf-8",
        )
        events = vl.get_value_events_since(datetime(2020, 1, 1))
        assert len(events) == 1
        assert events[0]["id"] == "valid"


