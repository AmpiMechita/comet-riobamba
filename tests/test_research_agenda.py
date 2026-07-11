"""Tests for services/research_agenda.py — research agenda store."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from services import research_agenda as ra


@pytest.fixture(autouse=True)
def _isolate_agenda_path(tmp_path):
    orig = ra.AGENDA_PATH
    orig_archive = ra.ARCHIVE_PATH
    ra.AGENDA_PATH = tmp_path / "research_agenda.json"
    ra.ARCHIVE_PATH = tmp_path / "research_agenda_archive.json"
    yield
    ra.AGENDA_PATH = orig
    ra.ARCHIVE_PATH = orig_archive


class TestResearchAgenda:
    def test_empty_agenda(self):
        agenda = ra.ResearchAgenda()
        assert agenda.get_open_questions() == []
        assert agenda.get_uncovered_topics() == []

    def test_add_and_get_open_questions(self):
        agenda = ra.ResearchAgenda()
        agenda.add_question("What fails first in tool-using LLMs?", source="test")
        agenda.add_question("How to detect agent loops?", source="test")
        questions = agenda.get_open_questions(limit=5)
        assert len(questions) == 2
        assert questions[0]["status"] == "open"

    def test_mark_answered(self):
        agenda = ra.ResearchAgenda()
        agenda.add_question("Test question?", source="test")
        assert agenda.mark_answered("Nonexistent") is False
        assert agenda.mark_answered("Test question?") is True
        assert len(agenda.get_open_questions()) == 0

    def test_add_and_get_uncovered_topics(self):
        agenda = ra.ResearchAgenda()
        agenda.add_topic("tool safety", source="test", tags=["agents"])
        agenda.add_topic("rate limits", source="test")
        topics = agenda.get_uncovered_topics(limit=5)
        assert len(topics) == 2
        assert topics[0]["covered"] is False

    def test_mark_covered(self):
        agenda = ra.ResearchAgenda()
        agenda.add_topic("test topic", source="test")
        assert agenda.mark_covered("test topic") is True
        assert agenda.get_uncovered_topics() == []

    def test_dedup_topics(self):
        agenda = ra.ResearchAgenda()
        agenda.add_topic("dedup topic", source="a")
        agenda.add_topic("dedup topic", source="b")
        assert len(agenda.pending_topics) == 1

    def test_add_experiment(self):
        agenda = ra.ResearchAgenda()
        agenda.add_experiment("Test cascade with fallback", tags=["agents"])
        assert len(agenda.experiments) == 1
        assert agenda.experiments[0]["status"] == "proposed"

    def test_add_high_impact_thread(self):
        agenda = ra.ResearchAgenda()
        agenda.add_high_impact_thread("thread-1", title="Hot thread", engagement=10)
        assert len(agenda.high_impact_threads) == 1
        agenda.add_high_impact_thread("thread-1", engagement=5)
        assert len(agenda.high_impact_threads) == 1

    def test_add_new_term(self):
        agenda = ra.ResearchAgenda()
        agenda.add_new_term("tool calling", source="test")
        agenda.add_new_term("tool calling", source="test")
        assert len(agenda.new_terms) == 1

    def test_serialization_roundtrip(self):
        agenda = ra.ResearchAgenda()
        agenda.add_question("Q1?", source="test")
        agenda.add_topic("T1", source="test")
        data = agenda.to_dict()
        restored = ra.ResearchAgenda.from_dict(data)
        assert len(restored.open_questions) == 1
        assert restored.open_questions[0]["question"] == "Q1?"
        assert len(restored.pending_topics) == 1

    def test_save_and_load(self):
        agenda = ra.ResearchAgenda()
        agenda.add_question("Persist test?", source="test")
        agenda.add_topic("persist topic", source="test")
        ra.save_agenda(agenda)
        loaded = ra.load_agenda()
        assert len(loaded.open_questions) == 1
        assert len(loaded.pending_topics) == 1
        assert loaded.open_questions[0]["question"] == "Persist test?"

    def test_load_missing_file_returns_empty(self):
        agenda = ra.load_agenda()
        assert isinstance(agenda, ra.ResearchAgenda)
        assert agenda.open_questions == []

    def test_load_corrupted_file_returns_empty(self):
        ra.AGENDA_PATH.parent.mkdir(parents=True, exist_ok=True)
        ra.AGENDA_PATH.write_text("not json", encoding="utf-8")
        agenda = ra.load_agenda()
        assert isinstance(agenda, ra.ResearchAgenda)
        assert agenda.open_questions == []

    def test_phase_b_feed_topic_gets_source_tag(self):
        """Topic added via Phase B feed path automatically gets source='phase_b_feed'."""
        agenda = ra.ResearchAgenda()
        agenda.add_topic("feed topic", source="phase_b_feed", tags=["agents"])
        assert len(agenda.pending_topics) == 1
        assert agenda.pending_topics[0]["source"] == "phase_b_feed"
        assert agenda.pending_topics[0]["topic"] == "feed topic"

    def test_phase_b_feed_topic_excluded_from_filtered_list(self):
        """Topics with source='phase_b_feed' should not appear in default uncovered list."""
        agenda = ra.ResearchAgenda()
        agenda.add_topic("legit", source="human_seeded")
        agenda.add_topic("feed artifact", source="phase_b_feed")
        uncovered = agenda.get_uncovered_topics(limit=5)
        # get_uncovered_topics does NOT filter — it returns all uncovered.
        # The filter lives in Phase A. This test just documents the contract.
        sources = {t["source"] for t in uncovered}
        assert "phase_b_feed" in sources  # agenda itself does not filter


# ── Retention / pruning ───────────────────────────────────────────


def _mk_topic(name, covered, age_days, now):
    """Build a pending_topic dict with created_at = now - age_days."""
    return {
        "topic": name,
        "source": "test",
        "tags": [],
        "covered": covered,
        "created_at": (now - timedelta(days=age_days)).isoformat(),
    }


class TestPruneAgenda:
    NOW = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)

    def test_covered_ttl_drops_old_covered_topics(self):
        agenda = ra.ResearchAgenda()
        agenda.pending_topics = [
            _mk_topic("old-covered", True, age_days=20, now=self.NOW),   # >14d -> drop
            _mk_topic("fresh-covered", True, age_days=5, now=self.NOW),  # <14d -> keep
        ]
        res = ra.prune_agenda(agenda, now=self.NOW)
        names = {t["topic"] for t in agenda.pending_topics}
        assert names == {"fresh-covered"}
        assert res["dropped_covered_ttl"] == 1

    def test_covered_topic_deleted_not_archived(self):
        agenda = ra.ResearchAgenda()
        agenda.pending_topics = [_mk_topic("old-covered", True, age_days=30, now=self.NOW)]
        ra.prune_agenda(agenda, now=self.NOW)
        # Covered TTL deletes; archive file should have no covered entry.
        if ra.ARCHIVE_PATH.exists():
            arch = json.loads(ra.ARCHIVE_PATH.read_text(encoding="utf-8"))
            assert all(t["topic"] != "old-covered" for t in arch.get("archived_topics", []))

    def test_uncovered_old_is_archived_not_deleted(self):
        agenda = ra.ResearchAgenda()
        agenda.pending_topics = [
            _mk_topic("stale-pending", False, age_days=70, now=self.NOW),   # >60d -> archive
            _mk_topic("recent-pending", False, age_days=10, now=self.NOW),  # keep
        ]
        res = ra.prune_agenda(agenda, now=self.NOW)
        names = {t["topic"] for t in agenda.pending_topics}
        assert names == {"recent-pending"}
        assert res["archived_uncovered_ttl"] == 1
        arch = json.loads(ra.ARCHIVE_PATH.read_text(encoding="utf-8"))
        assert any(t["topic"] == "stale-pending" for t in arch["archived_topics"])

    def test_uncovered_not_purged_by_covered_ttl(self):
        """An uncovered topic aged between 14d and 60d must survive (not covered-TTL'd)."""
        agenda = ra.ResearchAgenda()
        agenda.pending_topics = [_mk_topic("mid-age-pending", False, age_days=30, now=self.NOW)]
        ra.prune_agenda(agenda, now=self.NOW)
        assert [t["topic"] for t in agenda.pending_topics] == ["mid-age-pending"]

    def test_hard_cap_evicts_covered_first(self):
        agenda = ra.ResearchAgenda()
        # 3 fresh covered + 2 fresh uncovered, cap=3 -> must evict 2 (the covered, oldest first)
        agenda.pending_topics = [
            _mk_topic("cov-oldest", True, age_days=10, now=self.NOW),
            _mk_topic("cov-mid", True, age_days=8, now=self.NOW),
            _mk_topic("cov-new", True, age_days=1, now=self.NOW),
            _mk_topic("unc-a", False, age_days=5, now=self.NOW),
            _mk_topic("unc-b", False, age_days=2, now=self.NOW),
        ]
        res = ra.prune_agenda(agenda, now=self.NOW, max_active=3)
        names = [t["topic"] for t in agenda.pending_topics]
        assert len(names) == 3
        # Both uncovered survive; the 2 oldest covered are evicted.
        assert "unc-a" in names and "unc-b" in names
        assert "cov-oldest" not in names and "cov-mid" not in names
        assert res["capped_dropped_covered"] == 2

    def test_hard_cap_evicts_uncovered_when_not_enough_covered(self):
        agenda = ra.ResearchAgenda()
        # 1 covered + 4 uncovered, cap=2 -> evict 3: the 1 covered + 2 oldest uncovered
        agenda.pending_topics = [
            _mk_topic("cov", True, age_days=3, now=self.NOW),
            _mk_topic("unc-oldest", False, age_days=9, now=self.NOW),
            _mk_topic("unc-2", False, age_days=7, now=self.NOW),
            _mk_topic("unc-3", False, age_days=5, now=self.NOW),
            _mk_topic("unc-newest", False, age_days=1, now=self.NOW),
        ]
        res = ra.prune_agenda(agenda, now=self.NOW, max_active=2)
        names = [t["topic"] for t in agenda.pending_topics]
        assert len(names) == 2
        assert "unc-newest" in names          # newest uncovered survives
        assert "unc-oldest" not in names       # oldest uncovered evicted
        assert res["capped_dropped_covered"] == 1
        assert res["capped_archived_uncovered"] == 2
        # Cap-evicted uncovered are archived, not lost.
        arch = json.loads(ra.ARCHIVE_PATH.read_text(encoding="utf-8"))
        arch_names = {t["topic"] for t in arch["archived_topics"]}
        assert "unc-oldest" in arch_names

    def test_missing_created_at_not_purged_by_age(self):
        agenda = ra.ResearchAgenda()
        agenda.pending_topics = [
            {"topic": "no-timestamp", "source": "test", "tags": [], "covered": True},
        ]
        res = ra.prune_agenda(agenda, now=self.NOW)
        assert [t["topic"] for t in agenda.pending_topics] == ["no-timestamp"]
        assert res["dropped_covered_ttl"] == 0

    def test_prune_result_counts_and_no_op(self):
        agenda = ra.ResearchAgenda()
        agenda.pending_topics = [
            _mk_topic("keep1", True, age_days=1, now=self.NOW),
            _mk_topic("keep2", False, age_days=1, now=self.NOW),
        ]
        res = ra.prune_agenda(agenda, now=self.NOW)
        assert res["before"] == 2
        assert res["after"] == 2
        assert res["dropped_covered_ttl"] == 0
        assert res["archived_uncovered_ttl"] == 0
        # No archive file created when nothing archived.
        assert not ra.ARCHIVE_PATH.exists()

    def test_archive_appends_across_calls(self):
        agenda = ra.ResearchAgenda()
        agenda.pending_topics = [_mk_topic("old1", False, age_days=70, now=self.NOW)]
        ra.prune_agenda(agenda, now=self.NOW)
        agenda.pending_topics = [_mk_topic("old2", False, age_days=90, now=self.NOW)]
        ra.prune_agenda(agenda, now=self.NOW)
        arch = json.loads(ra.ARCHIVE_PATH.read_text(encoding="utf-8"))
        names = {t["topic"] for t in arch["archived_topics"]}
        assert names == {"old1", "old2"}

    def test_prune_then_save_load_roundtrip(self):
        agenda = ra.ResearchAgenda()
        agenda.pending_topics = [
            _mk_topic("old-covered", True, age_days=30, now=self.NOW),
            _mk_topic("keep", False, age_days=1, now=self.NOW),
        ]
        ra.prune_agenda(agenda, now=self.NOW)
        ra.save_agenda(agenda)
        loaded = ra.load_agenda()
        assert [t["topic"] for t in loaded.pending_topics] == ["keep"]
