# -*- coding: utf-8 -*-
"""Tests del panel de retorno de karma (scripts/karma_roi_report.py)."""

import json as _json
from pathlib import Path

from scripts import karma_roi_report as kat


class TestKarmaByDay:
    def test_computes_first_last_delta(self, tmp_path, monkeypatch):
        snap = tmp_path / "snapshots.jsonl"
        snap.write_text(
            "\n".join([
                _json.dumps({"ts": "2026-08-19T00:10:00", "karma": 3423}),
                _json.dumps({"ts": "2026-08-19T06:00:00", "karma": 3430}),
                _json.dumps({"ts": "2026-08-19T12:00:00", "karma": 3442}),
            ]),
            encoding="utf-8",
        )
        monkeypatch.setattr(kat, "SNAPSHOTS_PATH", snap)
        kb = kat.karma_by_day()
        assert kb["2026-08-19"]["first"] == 3423
        assert kb["2026-08-19"]["last"] == 3442

    def test_skips_without_karma(self, tmp_path, monkeypatch):
        snap = tmp_path / "snapshots.jsonl"
        snap.write_text(_json.dumps({"ts": "2026-08-19T00:00:00"}), encoding="utf-8")
        monkeypatch.setattr(kat, "SNAPSHOTS_PATH", snap)
        assert kat.karma_by_day() == {}


class TestPostsPerDay:
    def test_reads_list_toplevel(self, tmp_path, monkeypatch):
        pp = tmp_path / "published_posts.json"
        pp.write_text(_json.dumps([
            {"post_id": "a", "published_at": "2026-08-18T10:00:00"},
            {"post_id": "b", "published_at": "2026-08-18T11:00:00"},
            {"post_id": "c", "published_at": "2026-08-19T09:00:00"},
        ]), encoding="utf-8")
        monkeypatch.setattr("scripts.karma_roi_report.Path", type(
            "FakePath", (kat.Path,),
            {"exists": lambda self, p=pp: p.exists(),
             "read_text": lambda self, **k: pp.read_text(**k),
             "write_text": lambda self, v, **k: pp.write_text(v, **k),
             "parent": pp.parent}),
        )
        out = kat._posts_per_day()
        assert out["2026-08-18"] == 2
        assert out["2026-08-19"] == 1


class TestRecordDay:
    def test_upsert_by_date(self, tmp_path, monkeypatch):
        trend = tmp_path / "trend.jsonl"
        trend.write_text(
            _json.dumps({"date": "2026-08-18", "karma_delta": 41}) + "\n",
            encoding="utf-8",
        )
        snap = tmp_path / "snapshots.jsonl"
        snap.write_text(
            "\n".join([
                _json.dumps({"ts": "2026-08-19T08:00:00", "karma": 3423}),
                _json.dumps({"ts": "2026-08-19T12:00:00", "karma": 3442}),
            ]),
            encoding="utf-8",
        )
        monkeypatch.setattr(kat, "SNAPSHOTS_PATH", snap)
        monkeypatch.setattr(kat, "TREND_PATH", trend)
        monkeypatch.setattr(kat, "INBOUND_PATH", tmp_path / "no_inbound.json")
        # aislar data/metrics y published_posts de los datos reales
        monkeypatch.setattr(kat, "activity_for", lambda day: {"posts": 0, "comments": 0, "errors": 0, "cycles": 0})
        rec = kat.record_day("2026-08-19", trend_path=trend)
        assert rec["date"] == "2026-08-19"
        assert rec["karma_delta"] == 19
        rows = [_json.loads(l) for l in trend.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 2
        assert {x["date"] for x in rows} == {"2026-08-18", "2026-08-19"}
        assert rows[1]["posts"] == 0  # aislado: no toco datos reales