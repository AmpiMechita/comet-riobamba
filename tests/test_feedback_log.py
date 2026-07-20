import json

import pytest
import services.feedback_log as fl


def _path():
    return fl.FEEDBACK_LOG_PATH


def _read():
    p = _path()
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        return []
    return [json.loads(line) for line in text.split("\n")]


@pytest.fixture(autouse=True)
def _isolate_log(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.feedback_log.FEEDBACK_LOG_PATH",
        tmp_path / "feedback_log.jsonl",
    )


# ── Caso A: registro de feedback válido ───────────────────

class TestValidFeedback:

    def test_log_post_feedback_writes_record(self):
        fl.log_post_feedback(
            post_id="post_001",
            topic="perovskita tandem",
            phase="A",
            comments_count=5,
            replies_depth_max=3,
            unique_commenters=2,
            sentiment="positive",
            has_deep_thread=True,
        )

        records = _read()
        assert len(records) == 1
        r = records[0]
        assert r["post_id"] == "post_001"
        assert r["topic"] == "perovskita tandem"
        assert r["phase"] == "A"
        assert r["metrics"]["comments_count"] == 5
        assert r["metrics"]["replies_depth_max"] == 3
        assert r["metrics"]["unique_commenters"] == 2
        assert r["quality"]["sentiment"] == "positive"
        assert r["quality"]["has_deep_thread"] is True
        assert "created_at" in r

    def test_append_multiple_records(self):
        fl.log_post_feedback(
            post_id="p1", topic="a", phase="B",
            comments_count=1, replies_depth_max=1, unique_commenters=1,
            sentiment="neutral", has_deep_thread=False,
        )
        fl.log_post_feedback(
            post_id="p2", topic="b", phase="C",
            comments_count=2, replies_depth_max=2, unique_commenters=2,
            sentiment="negative", has_deep_thread=False,
        )

        records = _read()
        assert len(records) == 2
        assert records[0]["post_id"] == "p1"
        assert records[1]["post_id"] == "p2"

    def test_feedbackrecord_to_dict(self):
        record = fl.FeedbackRecord(
            post_id="test",
            created_at="2026-07-18T12:00:00+00:00",
            topic="solar",
            phase="A",
            metrics=fl.FeedbackMetrics(comments_count=3, replies_depth_max=2,
                                       unique_commenters=1),
            quality=fl.FeedbackQuality(sentiment="positive", has_deep_thread=True),
        )
        d = record.to_dict()
        assert d["post_id"] == "test"
        assert d["metrics"]["comments_count"] == 3
        assert d["quality"]["sentiment"] == "positive"


# ── Caso B: edge cases ───────────────────────────────────

class TestEdgeCases:

    def test_empty_topic_and_zero_metrics(self):
        fl.log_post_feedback(
            post_id="edge_1",
            topic="",
            phase="B",
            comments_count=0,
            replies_depth_max=0,
            unique_commenters=0,
            sentiment="neutral",
            has_deep_thread=False,
        )

        records = _read()
        assert len(records) == 1
        r = records[0]
        assert r["topic"] == ""
        assert r["metrics"]["comments_count"] == 0
        assert r["quality"]["has_deep_thread"] is False

    def test_unusual_sentiment_does_not_crash(self):
        fl.log_post_feedback(
            post_id="edge_2",
            topic="test",
            phase="A",
            comments_count=1,
            replies_depth_max=1,
            unique_commenters=1,
            sentiment="mixed",
            has_deep_thread=False,
        )

        records = _read()
        assert len(records) == 1
        assert records[0]["quality"]["sentiment"] == "mixed"

    def test_append_to_existing_file(self):
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"post_id": "pre", "topic": "x", "phase": "A",
                        "created_at": "2026-01-01T00:00:00",
                        "metrics": {"comments_count": 0, "replies_depth_max": 0,
                                    "unique_commenters": 0},
                        "quality": {"sentiment": "positive",
                                    "has_deep_thread": False}}) + "\n",
            encoding="utf-8",
        )

        fl.log_post_feedback(
            post_id="post_002",
            topic="solar",
            phase="A",
            comments_count=2,
            replies_depth_max=1,
            unique_commenters=1,
            sentiment="positive",
            has_deep_thread=False,
        )

        records = _read()
        assert len(records) == 2
        assert records[0]["post_id"] == "pre"
        assert records[1]["post_id"] == "post_002"
