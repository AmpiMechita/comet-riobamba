# -*- coding: utf-8 -*-
"""Tests del auto-tune semanal de umbrales de Phase B basado en ROI real."""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

import services.roi_auto_tune as rat


def _write_votes(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _vote(comment_id, reason, score, upvotes):
    return {"comment_id": comment_id, "post_id": "p",
            "reason": reason, "value_score": score, "upvotes": upvotes}


class TestAnalyzeRoi:
    def test_empty_ledger(self, tmp_path):
        path = tmp_path / "votes.jsonl"
        assert rat.analyze_roi(path)["total_checked"] == 0

    def test_groups_by_reason_and_score(self, tmp_path):
        path = tmp_path / "votes.jsonl"
        _write_votes(path, [
            _vote("a", "watchlist", 0.6, 3),
            _vote("b", "watchlist", 0.4, 1),
            _vote("c", "valor", 0.2, 0),
        ])
        roi = rat.analyze_roi(path)
        assert roi["total_checked"] == 3
        assert roi["reasons"]["watchlist"]["n"] == 2
        assert roi["reasons"]["watchlist"]["roi"] == 2.0
        assert roi["reasons"]["valor"]["roi"] == 0.0
        assert roi["scores"]["0.51-0.7"]["n"] == 1   # 0.6
        assert roi["scores"]["0.31-0.5"]["n"] == 1   # 0.4
        assert roi["scores"]["<=0.3"]["n"] == 1      # 0.2

    def test_skips_records_without_upvotes(self, tmp_path):
        path = tmp_path / "votes.jsonl"
        path.write_text(json.dumps({"comment_id": "x", "upvotes": None}) + "\n",
                        encoding="utf-8")
        assert rat.analyze_roi(path)["total_checked"] == 0


class TestRecommendTuning:
    def test_raises_feed_when_feed_roi_better(self, tmp_path):
        path = tmp_path / "votes.jsonl"
        rows = []
        for i in range(8):
            rows.append(_vote(f"f{i}", "watchlist", 0.6, 1))  # feed roi=1.0
        for i in range(8):
            rows.append(_vote(f"o{i}", "valor", 0.4, 0))      # own roi=0.0
        _write_votes(path, rows)
        rec = rat.recommend_tuning(rat.analyze_roi(path),
                                   current={"feed_budget_pct": 15.0, "min_value": 0.0})
        feed_change = [c for c in rec["changes"] if c["param"] == "feed_budget_pct"]
        assert feed_change
        assert rec["proposed"]["feed_budget_pct"] == 20.0  # 15 + paso 5

    def test_raises_min_value_when_low_score_no_return(self, tmp_path):
        path = tmp_path / "votes.jsonl"
        rows = []
        for i in range(8):
            rows.append(_vote(f"l{i}", "valor", 0.2, 0))   # score <=0.3, sin upvotes
        _write_votes(path, rows)
        rec = rat.recommend_tuning(rat.analyze_roi(path),
                                   current={"feed_budget_pct": 15.0, "min_value": 0.0})
        mv = [c for c in rec["changes"] if c["param"] == "min_value"]
        assert mv
        assert rec["proposed"]["min_value"] == 0.1

    def test_no_change_when_sample_too_small(self, tmp_path):
        path = tmp_path / "votes.jsonl"
        _write_votes(path, [_vote("a", "watchlist", 0.6, 1)])  # n=1 < min 5
        rec = rat.recommend_tuning(rat.analyze_roi(path),
                                   current={"feed_budget_pct": 15.0, "min_value": 0.0})
        assert rec["changes"] == []

    def test_respects_ceiling(self, tmp_path):
        path = tmp_path / "votes.jsonl"
        rows = [_vote(f"f{i}", "watchlist", 0.6, 1) for i in range(8)]
        rows += [_vote(f"o{i}", "valor", 0.4, 0) for i in range(8)]
        _write_votes(path, rows)
        rec = rat.recommend_tuning(rat.analyze_roi(path),
                                   current={"feed_budget_pct": 49.0, "min_value": 0.0})
        assert rec["proposed"]["feed_budget_pct"] <= rat._FEED_PCT_CEIL


class TestCadence:
    def test_should_run_when_no_last_run(self):
        assert rat.should_run({}, now=datetime.now(timezone.utc)) is True

    def test_should_not_run_until_cadence(self):
        now = datetime.now(timezone.utc)
        tuning = {"last_run": (now - timedelta(days=1)).isoformat()}
        assert rat.should_run(tuning, now=now) is False

    def test_should_run_after_cadence(self):
        now = datetime.now(timezone.utc)
        tuning = {"last_run": (now - timedelta(days=8)).isoformat()}
        assert rat.should_run(tuning, now=now) is True


class TestApplyAndGetters:
    def test_apply_persists_and_sets_last_run(self, tmp_path, monkeypatch):
        votes = tmp_path / "votes.jsonl"
        tuning = tmp_path / "tuning.json"
        hist = tmp_path / "hist.jsonl"
        rows = [_vote(f"f{i}", "watchlist", 0.6, 1) for i in range(8)]
        rows += [_vote(f"o{i}", "valor", 0.4, 0) for i in range(8)]
        _write_votes(votes, rows)
        monkeypatch.setenv("AGENT_FEED_BUDGET_PCT", "")
        monkeypatch.setenv("AGENT_MIN_REPLY_VALUE_SCORE", "")
        res = rat.apply_tuning(force=True, path=tuning, history_path=hist, votes_path=votes)
        assert res["ran"] is True
        assert res["changes"]
        saved = json.loads(tuning.read_text(encoding="utf-8"))
        assert "last_run" in saved
        assert saved["applied"]["feed_budget_pct"] == 20.0
        assert hist.exists()

    def test_getters_prefer_env_over_tuning(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENT_FEED_BUDGET_PCT", "22")
        monkeypatch.setenv("AGENT_MIN_REPLY_VALUE_SCORE", "0.25")
        assert rat.get_feed_budget_pct(default_pct=15.0, path=tmp_path / "x.json") == 22.0
        assert rat.get_min_value(default_min=0.0, path=tmp_path / "x.json") == 0.25

    def test_getters_fall_back_to_tuning_when_no_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AGENT_FEED_BUDGET_PCT", raising=False)
        monkeypatch.delenv("AGENT_MIN_REPLY_VALUE_SCORE", raising=False)
        tuning = tmp_path / "t.json"
        tuning.write_text(json.dumps({"applied": {"feed_budget_pct": 30.0, "min_value": 0.2}}),
                          encoding="utf-8")
        assert rat.get_feed_budget_pct(default_pct=15.0, path=tuning) == 30.0
        assert rat.get_min_value(default_min=0.0, path=tuning) == 0.2
