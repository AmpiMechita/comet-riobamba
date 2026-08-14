# -*- coding: utf-8 -*-
"""Tests del reporte diario de retorno por comentario."""

import json

import pytest

from scripts import comment_roi_report as roi


@pytest.fixture
def _fixtures(tmp_path, monkeypatch):
    votes = tmp_path / "comment_votes.jsonl"
    published = tmp_path / "published_posts.json"
    records = [
        {"comment_id": "c1", "post_id": "p1", "value_score": 0.95,
         "reason": "watchlist", "upvotes": 1},
        {"comment_id": "c2", "post_id": "p1", "value_score": 0.3,
         "reason": "primera_interaccion", "upvotes": 0},
        {"comment_id": "c3", "post_id": "p2", "value_score": 0.3,
         "reason": "valor", "upvotes": 0},
        {"comment_id": "c4", "post_id": "p2", "value_score": 0.95,
         "reason": "historial", "upvotes": 1},
    ]
    votes.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    published.write_text(json.dumps({
        "posts": [
            {"post_id": "p1", "published_at": "2026-08-10T10:00:00Z"},
            {"post_id": "p2", "published_at": "2026-08-14T10:00:00Z"},
        ]
    }), encoding="utf-8")
    monkeypatch.setattr(roi, "VOTES_PATH", votes)
    monkeypatch.setattr(roi, "PUBLISHED_PATH", published)
    return records


def test_report_groups_by_reason(_fixtures, capsys):
    roi.main()
    out = capsys.readouterr().out
    assert "watchlist" in out and "n=  1 upvotes= 1" in out
    assert "historial" in out
    assert "primera_interaccion" in out
    assert "valor" in out
    assert "upvotes totales: 2" in out


def test_report_groups_by_age_and_score(_fixtures, capsys):
    roi.main()
    out = capsys.readouterr().out
    assert "== POR EDAD DEL HILO" in out
    assert "post_desconocido" not in out  # ambos posts tienen fecha
    assert "== POR SCORE" in out
    assert ">0.7" in out
