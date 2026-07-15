# -*- coding: utf-8 -*-
"""Tests for utils/jsonl_rotation.py — size-based JSONL rotation."""

import json
from pathlib import Path

import pytest


def test_count_lines_returns_correct_count(tmp_path):
    from utils.jsonl_rotation import _count_lines
    f = tmp_path / "test.jsonl"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    assert _count_lines(f) == 3


def test_count_lines_empty_file(tmp_path):
    from utils.jsonl_rotation import _count_lines
    f = tmp_path / "empty.jsonl"
    f.write_text("", encoding="utf-8")
    assert _count_lines(f) == 0


def test_rotate_under_limit_does_nothing(tmp_path):
    from utils.jsonl_rotation import append_jsonl
    f = tmp_path / "scores.jsonl"
    for i in range(5):
        append_jsonl({"id": i}, f, max_lines=10)
    lines = f.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 5
    archive = tmp_path / "scores.jsonl.archive"
    assert not archive.exists()


def test_rotate_exceeds_limit_creates_archive(tmp_path):
    from utils.jsonl_rotation import append_jsonl
    f = tmp_path / "scores.jsonl"
    for i in range(12):
        append_jsonl({"id": i}, f, max_lines=10)
    archive = tmp_path / "scores.jsonl.archive"
    assert archive.exists()
    # Active file starts fresh after rotation
    active_lines = f.read_text(encoding="utf-8").strip().splitlines()
    assert len(active_lines) < 10  # Rotated, new file is shorter


def test_rotate_preserves_old_data_in_archive(tmp_path):
    from utils.jsonl_rotation import append_jsonl
    f = tmp_path / "scores.jsonl"
    for i in range(12):
        append_jsonl({"id": i}, f, max_lines=10)
    archive = tmp_path / "scores.jsonl.archive"
    archive_lines = archive.read_text(encoding="utf-8").strip().splitlines()
    assert len(archive_lines) == 10
    records = [json.loads(l) for l in archive_lines]
    assert records[0]["id"] == 0
    assert records[9]["id"] == 9


def test_rotate_single_generation_archive_overwrites(tmp_path):
    from utils.jsonl_rotation import append_jsonl
    f = tmp_path / "scores.jsonl"
    # Write 15 items → triggers rotation at item 11 (when count reaches 10 before append)
    for i in range(15):
        append_jsonl({"id": i}, f, max_lines=10)
    archive = tmp_path / "scores.jsonl.archive"
    assert archive.exists()
    first_archive_lines = archive.read_text(encoding="utf-8").strip().splitlines()
    assert len(first_archive_lines) >= 1

    # Write 10 more — triggers second rotation when active count hits 10
    for i in range(15, 30):
        append_jsonl({"id": i}, f, max_lines=10)
    archive = tmp_path / "scores.jsonl.archive"
    second_archive_lines = archive.read_text(encoding="utf-8").strip().splitlines()
    assert len(second_archive_lines) >= 1
    # Second archive overwrote first: verify the active file still works
    active_lines = f.read_text(encoding="utf-8").strip().splitlines()
    assert len(active_lines) <= 10


def test_append_jsonl_creates_parent_dir(tmp_path):
    from utils.jsonl_rotation import append_jsonl
    f = tmp_path / "subdir" / "nested.jsonl"
    append_jsonl({"test": True}, f)
    assert f.exists()
    assert json.loads(f.read_text(encoding="utf-8").strip()) == {"test": True}


def test_rotate_missing_file_returns_false(tmp_path):
    from utils.jsonl_rotation import _rotate_log_if_needed
    f = tmp_path / "nonexistent.jsonl"
    assert _rotate_log_if_needed(f, max_lines=10) is False
