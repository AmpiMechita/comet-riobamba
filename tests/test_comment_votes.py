# -*- coding: utf-8 -*-
"""Tests del ledger de retorno por comentario (upvotes por comentario propio)."""

import json
from unittest.mock import MagicMock

import pytest

from services.comment_votes import (
    record_published_comment, refresh_comment_votes, refresh_all_comment_votes,
    votes_summary,
)


class TestCommentVotesLedger:
    def test_record_persists_with_score(self, tmp_path):
        path = tmp_path / "comment_votes.jsonl"
        assert record_published_comment("post-1", "c-1", 0.72, path=path) is True
        records = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
        assert len(records) == 1
        rec = records[0]
        assert rec["comment_id"] == "c-1"
        assert rec["post_id"] == "post-1"
        assert rec["value_score"] == 0.72
        assert rec["upvotes"] is None

    def test_record_is_upsert_once(self, tmp_path):
        path = tmp_path / "comment_votes.jsonl"
        record_published_comment("post-1", "c-1", 0.5, path=path)
        assert record_published_comment("post-1", "c-1", 0.9, path=path) is False
        records = path.read_text(encoding="utf-8").splitlines()
        assert len(records) == 1

    def test_record_empty_id_noop(self, tmp_path):
        path = tmp_path / "comment_votes.jsonl"
        assert record_published_comment("post-1", "", 0.5, path=path) is False
        assert not path.exists()

    def test_record_with_reason(self, tmp_path):
        path = tmp_path / "comment_votes.jsonl"
        record_published_comment("post-1", "c-1", 0.3, reason="primera_interaccion", path=path)
        rec = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert rec["reason"] == "primera_interaccion"
        # default
        record_published_comment("post-2", "c-2", 0.9, path=path)
        rec2 = json.loads(path.read_text(encoding="utf-8").splitlines()[1])
        assert rec2["reason"] == "valor"

    def test_refresh_reads_upvotes_from_api(self, tmp_path):
        path = tmp_path / "comment_votes.jsonl"
        record_published_comment("post-1", "c-1", 0.72, path=path)
        record_published_comment("post-1", "c-2", 0.3, path=path)

        api = MagicMock()
        api.fetch_post_comments.return_value = [
            {"id": "c-1", "upvotes": 4},
            {"id": "other", "upvotes": 99},
            {"id": "c-2", "upvotes": 1},
        ]
        updated = refresh_comment_votes(api, "post-1", ["c-1", "c-2"], path=path)

        assert updated == 2
        records = {r["comment_id"]: r for r in
                   (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines())}
        assert records["c-1"]["upvotes"] == 4
        assert records["c-2"]["upvotes"] == 1

    def test_refresh_only_touches_registered_comments(self, tmp_path):
        path = tmp_path / "comment_votes.jsonl"
        record_published_comment("post-1", "c-1", 0.5, path=path)
        api = MagicMock()
        api.fetch_post_comments.return_value = [{"id": "c-1", "upvotes": 2}]
        refresh_comment_votes(api, "post-1", ["c-1", "not-registered"], path=path)
        records = path.read_text(encoding="utf-8").splitlines()
        assert len(records) == 1

    def test_refresh_finds_deep_comments_via_paginate(self, tmp_path):
        """P-122: el cliente pagina por cursor (paginate=True); el caller
        recibe ya todas las paginas en UNA sola llamada."""
        path = tmp_path / "comment_votes.jsonl"
        record_published_comment("post-1", "c-deep", 0.9, path=path)
        record_published_comment("post-1", "c-shallow", 0.3, path=path)

        api = MagicMock()
        api.fetch_post_comments.return_value = [
            {"id": f"other-{i}", "upvotes": 0} for i in range(50)
        ] + [{"id": "c-deep", "upvotes": 7}]

        updated = refresh_comment_votes(api, "post-1", ["c-deep", "c-shallow"], path=path)

        assert updated == 1
        assert api.fetch_post_comments.call_count == 1
        kwargs = api.fetch_post_comments.call_args.kwargs
        assert kwargs.get("paginate") is True
        records = {r["comment_id"]: r for r in
                   (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines())}
        assert records["c-deep"]["upvotes"] == 7
    def test_refresh_warns_when_comment_not_found(self, tmp_path, caplog):
        """P-122: una sola llamada paginada; el comentario no aparece -> 0 y warning."""
        import logging
        path = tmp_path / "comment_votes.jsonl"
        record_published_comment("post-1", "c-missing", 0.5, path=path)
        api = MagicMock()
        api.fetch_post_comments.return_value = [{"id": "other", "upvotes": 1}]

        with caplog.at_level(logging.WARNING, logger="services.comment_votes"):
            updated = refresh_comment_votes(api, "post-1", ["c-missing"], path=path)

        assert updated == 0
        assert api.fetch_post_comments.call_count == 1
        assert any("sin localizar" in r.getMessage() for r in caplog.records)
    def test_summary_groups_by_score(self, tmp_path):
        path = tmp_path / "comment_votes.jsonl"
        record_published_comment("p1", "c-high", 0.9, path=path)
        record_published_comment("p1", "c-low", 0.3, path=path)
        api = MagicMock()
        api.fetch_post_comments.return_value = [
            {"id": "c-high", "upvotes": 5},
            {"id": "c-low", "upvotes": 0},
        ]
        refresh_all_comment_votes(api, {"p1": ["c-high", "c-low"]}, path=path)

        summary = votes_summary(path=path)
        assert summary["total"] == 2
        assert summary["with_votes"] == 2
        assert summary["total_upvotes"] == 5
        assert summary["by_score"][">0.7"]["n"] == 1
        assert summary["by_score"][">0.7"]["upvotes"] == 5
        assert summary["by_score"]["<=0.3"]["n"] == 1

    def test_summary_empty(self, tmp_path):
        path = tmp_path / "none.jsonl"
        summary = votes_summary(path=path)
        assert summary["total"] == 0
        assert summary["total_upvotes"] == 0
