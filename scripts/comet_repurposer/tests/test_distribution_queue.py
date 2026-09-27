"""
Tests for iter_distribution_queue + _select_items("distribution_queue").
Regression for P-116: content_distributor.py pasa --source distribution_queue.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from comet_repurposer.cli import _select_items
from comet_repurposer.sources import iter_distribution_queue


def _write(tmp_path: Path, payload) -> Path:
    (tmp_path / "data").mkdir(exist_ok=True)
    p = tmp_path / "data" / "distribution_queue.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_reads_two_posts(tmp_path):
    _write(tmp_path, {
        "selected_at": "2026-09-26T23:29:20+00:00",
        "posts": [
            {"post_id": "a1", "topic": "T1", "body": "B1",
             "published_at": "2026-09-26T10:00:00"},
            {"post_id": "a2", "topic": "T2", "body": "B2"},
        ],
    })
    items = list(iter_distribution_queue(tmp_path))
    assert len(items) == 2
    assert items[0].source_kind == "distribution_item"
    assert items[0].source_id == "a1"
    assert items[0].title == "T1"
    assert items[0].body == "B1"
    assert items[0].created_at == "2026-09-26T10:00:00"


def test_missing_file_yields_nothing(tmp_path):
    assert list(iter_distribution_queue(tmp_path)) == []


def test_malformed_json_yields_nothing(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "distribution_queue.json").write_text("{not json", encoding="utf-8")
    assert list(iter_distribution_queue(tmp_path)) == []


def test_skips_entries_without_id_or_topic(tmp_path):
    _write(tmp_path, {"posts": [
        {"post_id": "", "topic": "T"},
        {"post_id": "x", "topic": ""},
        {"post_id": "ok", "topic": "T"},
    ]})
    items = list(iter_distribution_queue(tmp_path))
    assert [i.source_id for i in items] == ["ok"]


def test_select_items_dispatches(tmp_path):
    _write(tmp_path, {"posts": [
        {"post_id": "p1", "topic": "T1", "body": "B1"},
    ]})
    items = list(_select_items("distribution_queue", tmp_path, limit=None))
    assert len(items) == 1
    assert items[0].source_id == "p1"
