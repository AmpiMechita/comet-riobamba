"""Tests for the Phase C Trend Watcher (services/trend_watcher.py + phase_c wiring)."""

import json
import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

pytest_plugins = ("pytest_asyncio",)

from services.trend_watcher import extract_keywords, cluster_posts, run_trend_watcher
from services.research_agenda import ResearchAgenda


def _make_posts(count: int, base_keyword: str = "security") -> list:
    posts = []
    for i in range(count):
        posts.append({
            "id": f"post_{i}",
            "title": f"{base_keyword} gateway model risk {i}",
            "score": 10 + i,
            "likes": 10 + i,
            "comments_count": 2 + i,
            "content": f"Content about {base_keyword} topic {i}",
        })
    return posts


def _make_agenda(existing_keywords: list = None) -> ResearchAgenda:
    agenda = ResearchAgenda()
    for kw in (existing_keywords or []):
        agenda.add_topic(kw, source="human_seeded")
    return agenda


logging.basicConfig(level=logging.DEBUG, format="%(levelname)s|%(name)s|%(message)s")


# ── Keyword extraction ────────────────────────────────────────────


class TestExtractKeywords:
    def test_removes_stopwords(self):
        assert extract_keywords("the quick brown fox") == ["quick", "brown"]

    def test_short_words_filtered(self):
        assert extract_keywords("a an the is at") == []

    def test_dedup(self):
        assert extract_keywords("test test foo") == ["test"]

    def test_three_char_words_included(self):
        assert extract_keywords("bar security") == ["security"]

    def test_max_keywords(self):
        result = extract_keywords("security gateway model cascade risk management", max_keywords=3)
        assert len(result) == 3

    def test_lowercase(self):
        assert extract_keywords("SECURITY Gateway") == ["security", "gateway"]


# ── Clustering ────────────────────────────────────────────────────


class TestClusterPosts:
    def test_single_keyword_cluster(self):
        posts = _make_posts(3, base_keyword="security")
        clusters = cluster_posts(posts)
        assert len(clusters) >= 1
        sec_clusters = [c for c in clusters if c["keyword"] == "security"]
        assert len(sec_clusters) == 1
        assert sec_clusters[0]["post_count"] == 3

    def test_two_keyword_groups(self):
        posts = _make_posts(3, base_keyword="security") + _make_posts(2, base_keyword="mlops")
        clusters = cluster_posts(posts)
        keywords = {c["keyword"] for c in clusters}
        assert "security" in keywords
        assert "mlops" in keywords

    def test_clusters_ranked_by_score(self):
        posts = _make_posts(3, base_keyword="security") + _make_posts(1, base_keyword="mlops")
        clusters = cluster_posts(posts)
        assert clusters[0]["score"] >= clusters[-1]["score"]

    def test_empty_posts(self):
        assert cluster_posts([]) == []

    def test_posts_without_title_skipped(self):
        posts = [{"id": "p1", "title": ""}]
        assert cluster_posts(posts) == []


# ── Full pipeline ─────────────────────────────────────────────────


class TestRunTrendWatcher:
    def test_feed_with_10_posts_top_2_proposed(self):
        """Scenario (a): Feed with 10 posts → clusters formed → top 2 proposed."""
        api = MagicMock()
        posts = _make_posts(10, base_keyword="security")
        api.fetch_posts.return_value = posts
        agenda = _make_agenda()
        result = run_trend_watcher(api, agenda, feed_size=50, top_n=2, trends_path=Path("data/test_trends.jsonl"))
        assert result["posts_scanned"] == 10
        assert result["clusters_found"] >= 1
        assert result["topics_proposed"] >= 1
        assert len(agenda.pending_topics) >= 1
        for topic in agenda.pending_topics:
            assert topic["source"] == "phase_c_trend"

    def test_keyword_already_in_agenda_skipped(self):
        """Scenario (b): Keyword already in agenda → skipped (no duplicate added)."""
        api = MagicMock()
        posts = _make_posts(3, base_keyword="security")
        api.fetch_posts.return_value = posts
        agenda = _make_agenda(existing_keywords=["security"])
        result = run_trend_watcher(api, agenda, feed_size=50, top_n=2, trends_path=Path("data/test_trends.jsonl"))
        # "security" is already in agenda, so it should NOT be re-added.
        # The count of topics with topic=="security" must stay at 1.
        security_topics = [t for t in agenda.pending_topics if t["topic"] == "security"]
        assert len(security_topics) == 1
        # Other keywords from the titles (gateway, model) may still be proposed
        # — that's expected. The key invariant is no duplicate of "security".

    def test_empty_feed_returns_zero_and_logs_warning(self):
        """Scenario (c): get_feed returns empty → WARNING, 0 proposals."""
        api = MagicMock()
        api.fetch_posts.return_value = []
        agenda = _make_agenda()
        with patch("services.trend_watcher.logger") as mock_log:
            result = run_trend_watcher(api, agenda, feed_size=50, top_n=2, trends_path=Path("data/test_trends.jsonl"))
        assert result["posts_scanned"] == 0
        assert result["topics_proposed"] == 0
        mock_log.warning.assert_called()

    def test_feed_exception_returns_zero_and_logs_warning(self):
        """Scenario (d): get_feed raises exception → WARNING, 0 proposals."""
        api = MagicMock()
        api.fetch_posts.side_effect = RuntimeError("API down")
        agenda = _make_agenda()
        with patch("services.trend_watcher.logger") as mock_log:
            result = run_trend_watcher(api, agenda, feed_size=50, top_n=2, trends_path=Path("data/test_trends.jsonl"))
        assert result["posts_scanned"] == 0
        assert result["topics_proposed"] == 0
        mock_log.warning.assert_called()

    def test_top_n_1_only_one_topic_proposed(self):
        """Scenario (e): TREND_WATCHER_TOP_N=1 → only 1 topic proposed."""
        api = MagicMock()
        # Create posts with two distinct keywords so we get 2+ clusters
        posts = _make_posts(3, base_keyword="security") + _make_posts(3, base_keyword="mlops")
        api.fetch_posts.return_value = posts
        agenda = _make_agenda()
        result = run_trend_watcher(api, agenda, feed_size=50, top_n=1, trends_path=Path("data/test_trends.jsonl"))
        # top_n=1 should propose at most 1
        assert result["topics_proposed"] <= 1
        assert len(result["top_clusters"]) == 1

    def test_analytics_jsonl_written(self):
        """Scenario (h): analytics_trends.jsonl written with correct fields."""
        trends_path = Path("data/test_trends_analytics.jsonl")
        try:
            api = MagicMock()
            api.fetch_posts.return_value = _make_posts(3, base_keyword="security")
            agenda = _make_agenda()
            result = run_trend_watcher(api, agenda, feed_size=50, top_n=2, trends_path=trends_path)
            assert trends_path.exists()
            lines = trends_path.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 1
            record = json.loads(lines[0])
            assert record["posts_scanned"] == 3
            assert record["clusters_found"] >= 1
            assert record["topics_proposed"] >= 1
            assert len(record["top_clusters"]) >= 1
            assert "ts" in record
        finally:
            if trends_path.exists():
                trends_path.unlink()

    def test_multiple_runs_appends_to_jsonl(self):
        """Running trend watcher twice appends two lines to JSONL."""
        trends_path = Path("data/test_trends_analytics.jsonl")
        try:
            api = MagicMock()
            api.fetch_posts.return_value = _make_posts(3, base_keyword="security")
            agenda = _make_agenda()
            run_trend_watcher(api, agenda, feed_size=50, top_n=2, trends_path=trends_path)
            agenda2 = _make_agenda()
            run_trend_watcher(api, agenda2, feed_size=50, top_n=2, trends_path=trends_path)
            lines = trends_path.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 2
        finally:
            if trends_path.exists():
                trends_path.unlink()
