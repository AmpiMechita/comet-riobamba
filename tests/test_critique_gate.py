# -*- coding: utf-8 -*-
"""Tests del gate de critica data-driven (writer + critic, v5.9).

Verifica que la critica se dispara para watchlist SIEMPRE y para canales con
ROI medido (upvotes/comentario) sobre el umbral, cacheada por ciclo."""
import json
from unittest.mock import MagicMock

import pytest

import services.roi_auto_tune as rat
from phases.phase_b.orchestrator import PhaseB


def _write_votes(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _vote(comment_id, reason, upvotes):
    return {"comment_id": comment_id, "post_id": "p",
            "reason": reason, "value_score": 0.5, "upvotes": upvotes}


class TestChannelsWithRoi:
    def test_empty_returns_empty(self, tmp_path):
        path = tmp_path / "v.jsonl"
        assert rat.channels_with_roi(path=path) == {}

    def test_filters_by_min_sample_and_roi(self, tmp_path):
        path = tmp_path / "v.jsonl"
        # watchlist: n=1 < min_sample -> fuera
        _write_votes(path, [_vote("a", "watchlist", 1)])
        assert rat.channels_with_roi(path=path) == {}

    def test_includes_channel_above_threshold(self, tmp_path):
        path = tmp_path / "v.jsonl"
        _write_votes(path, [_vote("a", "historial", 3)])
        res = rat.channels_with_roi(min_sample=1, path=path)
        assert "historial" in res
        assert res["historial"] == 3.0

    def test_excludes_below_threshold(self, tmp_path):
        path = tmp_path / "v.jsonl"
        _write_votes(path, [_vote("a", "valor", 0)])  # roi 0.0 < umbral
        assert rat.channels_with_roi(min_sample=1, path=path) == {}


def _make_phase_b():
    deps = MagicMock()
    deps.behavior_cfg = {}
    deps.agent_name = "comet_riobamba"
    deps.get_comments_today = lambda: 0
    pb = PhaseB(deps=deps)
    pb._roi_channels_cache = None
    return pb


class TestShouldCritique:
    def test_watchlist_always(self, monkeypatch):
        pb = _make_phase_b()
        monkeypatch.setattr(pb, "_is_watchlist_author", lambda a: True)
        assert pb._should_critique("flash", "viarapida") is True
        assert pb._should_critique("quality", "someone") is True

    def test_non_watchlist_without_proven_roi_is_false(self, monkeypatch):
        pb = _make_phase_b()
        monkeypatch.setattr(pb, "_is_watchlist_author", lambda a: False)
        monkeypatch.setattr(pb, "_comment_entry_reason", lambda a: "valor")
        pb._roi_channels_cache = {}  # ningun canal con ROI
        assert pb._should_critique("flash", "someone") is False

    def test_channel_with_proven_roi_critiques(self, monkeypatch):
        pb = _make_phase_b()
        monkeypatch.setattr(pb, "_is_watchlist_author", lambda a: False)
        monkeypatch.setattr(pb, "_comment_entry_reason", lambda a: "historial")
        pb._roi_channels_cache = {"historial": 0.5}
        assert pb._should_critique("flash", "someone") is True

    def test_caches_roi_per_cycle(self, monkeypatch):
        pb = _make_phase_b()
        monkeypatch.setattr(pb, "_is_watchlist_author", lambda a: False)
        monkeypatch.setattr(pb, "_comment_entry_reason", lambda a: "historial")
        calls = {"n": 0}
        def fake_channels_with_roi(*a, **k):
            calls["n"] += 1
            return {"historial": 0.5}
        monkeypatch.setattr("services.roi_auto_tune.channels_with_roi", fake_channels_with_roi)
        assert pb._should_critique("flash", "someone") is True
        assert pb._should_critique("flash", "someone") is True
        assert calls["n"] == 1  # cacheado: una sola lectura del ledger

    def test_error_falls_back_to_false(self, monkeypatch):
        pb = _make_phase_b()
        monkeypatch.setattr(pb, "_is_watchlist_author", lambda a: False)
        monkeypatch.setattr(pb, "_comment_entry_reason", lambda a: "valor")
        monkeypatch.setattr(pb, "_roi_channels_cache", None)
        monkeypatch.setattr("services.roi_auto_tune.channels_with_roi",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert pb._should_critique("flash", "someone") is False