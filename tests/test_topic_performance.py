"""Tests for topic performance logging, refresh, and selector feedback."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from phases.phase_a_content import (
    _track_topic_performance,
    _load_topic_performance,
    choose_topic,
)


TEMP = Path(os.environ.get("TEMP", r"C:\Users\rafae\AppData\Local\Temp")) / "opencode"


def _perf_file():
    TEMP.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=".jsonl", dir=str(TEMP))
    os.close(fd)
    return Path(path)


# ── Piece 1: Publication tracking ──────────────────────────────────────────

class TestTrackTopicPerformance:
    """Scenarios a, b, c."""

    def test_a_writes_jsonl_record(self):
        """_track_topic_performance writes a JSONL record with expected fields."""
        p = _perf_file()
        try:
            with patch("phases.phase_a_content.PERFORMANCE_LOG_PATH", p):
                _track_topic_performance("agent tool safety", "post_abc12345")
            lines = p.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 1
            rec = json.loads(lines[0])
            assert rec["topic"] == "agent tool safety"
            assert rec["post_id"] == "post_abc12345"
            assert rec["initial_score"] == 0
            assert rec["initial_comments"] == 0
            assert rec["score_checked"] is False
            assert "published_at" in rec
        finally:
            p.unlink(missing_ok=True)

    def test_b_creates_parent_directory(self):
        """_track_topic_performance creates parent dir when missing."""
        nested = _perf_file()
        parent = nested.parent
        # Use a subdirectory that does not exist yet
        deep = parent / "a" / "b" / "test.jsonl"
        try:
            with patch("phases.phase_a_content.PERFORMANCE_LOG_PATH", deep):
                _track_topic_performance("test topic", "post_00000000")
                assert deep.exists()
        finally:
            if deep.exists():
                deep.unlink()

    def test_c_append_produces_two_lines(self):
        """Second call appends, resulting in 2 lines."""
        p = _perf_file()
        try:
            with patch("phases.phase_a_content.PERFORMANCE_LOG_PATH", p):
                _track_topic_performance("topic A", "post_a")
                _track_topic_performance("topic B", "post_b")
            lines = p.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 2
            rec_a = json.loads(lines[0])
            rec_b = json.loads(lines[1])
            assert rec_a["topic"] == "topic A"
            assert rec_b["topic"] == "topic B"
        finally:
            p.unlink(missing_ok=True)


# ── Piece 3: Topic selector feedback ───────────────────────────────────────

class TestLoadTopicPerformance:
    """Scenarios d, e."""

    def test_d_file_missing_returns_empty(self):
        """_load_topic_performance returns empty dict when file doesn't exist."""
        with patch("phases.phase_a_content.PERFORMANCE_LOG_PATH", Path("/nonexistent/file.jsonl")):
            assert _load_topic_performance() == {}

    def test_e_parses_records(self):
        """_load_topic_performance returns dict keyed by topic."""
        p = _perf_file()
        try:
            p.write_text(
                '{"topic": "A", "score": 5, "score_checked": true}\n'
                '{"topic": "B", "score": 0, "score_checked": true}\n',
                encoding="utf-8",
            )
            with patch("phases.phase_a_content.PERFORMANCE_LOG_PATH", p):
                result = _load_topic_performance()
            assert set(result.keys()) == {"A", "B"}
            assert result["A"]["score"] == 5
            assert result["B"]["score"] == 0
        finally:
            p.unlink(missing_ok=True)


class TestChooseTopicEngagement:
    """Scenarios f, g."""

    @patch("phases.phase_a_content.load_agenda")
    @patch("phases.phase_a_content.load_roadmap")
    def test_f_skips_zero_engagement_topics(self, mock_roadmap, mock_agenda):
        """choose_topic filters out zero-engagement topics."""
        p = _perf_file()
        try:
            p.write_text(
                '{"topic": "dud topic", "score": 0, "comment_count": 0, "score_checked": true}\n',
                encoding="utf-8",
            )
            mock_agenda_obj = MagicMock()
            mock_agenda_obj.get_uncovered_topics.return_value = [
                {"topic": "dud topic", "source": "test"},
            ]
            mock_agenda.return_value = mock_agenda_obj
            mock_roadmap.return_value = MagicMock()

            with patch("phases.phase_a_content.PERFORMANCE_LOG_PATH", p), \
                 patch("phases.phase_a_content.choose_topic_from_roadmap", return_value=None), \
                 patch("phases.phase_a_content.compute_topic_weights", return_value={"dud topic": 1.0}):
                topic, source = choose_topic(mode="research")
            assert isinstance(topic, str)
            assert topic != "dud topic"
        finally:
            p.unlink(missing_ok=True)

    @patch("phases.phase_a_content.load_agenda")
    def test_g_boosts_high_engagement_topic(self, mock_agenda):
        """choose_topic picks high-engagement topic first."""
        p = _perf_file()
        try:
            p.write_text(
                '{"topic": "high eng topic", "score": 10, "score_checked": true}\n'
                '{"topic": "low eng topic", "score": 1, "score_checked": true}\n',
                encoding="utf-8",
            )
            mock_agenda_obj = MagicMock()
            mock_agenda_obj.get_uncovered_topics.return_value = [
                {"topic": "low eng topic", "source": "test"},
                {"topic": "high eng topic", "source": "test"},
            ]
            mock_agenda.return_value = mock_agenda_obj

            with patch("phases.phase_a_content.PERFORMANCE_LOG_PATH", p):
                topic, source = choose_topic(mode="research")
            assert topic == "high eng topic"
        finally:
            p.unlink(missing_ok=True)


# Tests h/i/j eliminados: _PERFORMANCE_LOG_PATH y
# _refresh_topic_performance fueron removidos del módulo en refactor.
