# -*- coding: utf-8 -*-
"""Tests de la reflexion diaria: interacciones -> topics de agenda."""

import json
from datetime import datetime, timedelta, timezone

import pytest

import services.nightly_reflection as nr


def _event(topic="agent retry mechanism", comment_id="c1", ts=None, clf="aporte_util",
           problema="The user commented on the idea of treating tool calls as carrying a deadline budget."):
    return {
        "timestamp": (ts or datetime.now(timezone.utc).isoformat()),
        "post_id": "p1", "comment_id": comment_id,
        "tema": topic, "tipo_problema": "architecture question",
        "clasificacion_valor": clf, "resumen_problema": problema,
        "resumen_solucion": "solution",
    }


def _write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")


class TestLoadEvents:
    def test_filters_by_cutoff_and_classification(self, tmp_path):
        path = tmp_path / "value_log.jsonl"
        old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        _write(path, [
            _event("epoch-before", ts=old),                       # muy viejo: fuera
            _event("bad-class", clf="baja_relevancia"),            # clasificacion no util
            _event("no-problema", clf="aporte_util", problema=""),  # sin resumen
            _event("good", clf="resolvio_problema"),
        ])
        cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
        events = nr.load_events(cutoff, events_path=path)
        assert [e["tema"] for e in events] == ["good"]


class TestBuildTopics:
    def test_prioritizes_retorno_real(self, tmp_path):
        path = tmp_path / "value_log.jsonl"
        now = datetime.now(timezone.utc).isoformat()
        _write(path, [
            _event("tema vueltas", ts=now, comment_id="c-a"),
            _event("tema con upvotes", ts=now, comment_id="c-b"),
        ])
        cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
        events = nr.load_events(cutoff, events_path=path)
        topics = nr.build_topics(events, {"c-b": 3}, max_topics=10)
        assert topics[0]["topic"].startswith("tema con upvotes")
        assert topics[0]["upvotes"] == 3
        assert topics[0]["tags"][0] == "nightly_reflection"

    def test_dedup_same_tema(self):
        events = [
            _event("same", comment_id="1"),
            _event("same", comment_id="2"),
        ]
        topics = nr.build_topics(events, {}, max_topics=10)
        assert len(topics) == 1

    def test_max_topics_cap(self):
        events = [_event(f"tema{i}", comment_id=f"c{i}") for i in range(6)]
        topics = nr.build_topics(events, {}, max_topics=3)
        assert len(topics) == 3

    def test_skips_ban_tema(self):
        topics = nr.build_topics([_event("Hola", problema="hello there")], {})
        assert topics == []


class TestCadence:
    def test_should_run_when_never(self):
        assert nr.should_run({}) is True

    def test_should_not_run_when_recent(self):
        now = datetime.now(timezone.utc)
        state = {"last_run": (now - timedelta(hours=1)).isoformat()}
        assert nr.should_run(state, now=now) is False

    def test_should_run_after_interval(self):
        now = datetime.now(timezone.utc)
        state = {"last_run": (now - timedelta(hours=20)).isoformat()}
        assert nr.should_run(state, now=now) is True


class TestRunReflection:
    def test_respects_cadence(self, tmp_path):
        now = datetime.now(timezone.utc)
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"last_run": now.isoformat()}), encoding="utf-8")
        res = nr.run_reflection(state_path=state,
                                events_path=tmp_path / "v.jsonl",
                                votes_path=tmp_path / "cv.jsonl",
                                now=now)
        assert res["ran"] is False

    def test_adds_topics_to_agenda(self, tmp_path):
        now = datetime.now(timezone.utc)
        events = tmp_path / "value_log.jsonl"
        _write(events, [_event("trustful topic", ts=now.isoformat())])
        votes = tmp_path / "comment_votes.jsonl"
        _write(votes, [{"comment_id": "c1", "upvotes": 2}])

        class FakeAgenda:
            def __init__(self):
                self.topics = []
                self.terms = []
            def add_topic(self, topic, source="", tags=None):
                self.topics.append({"topic": topic, "source": source, "tags": tags})
            def add_new_term(self, term, context="", source=""):
                self.terms.append({"term": term, "context": context, "source": source})

        ag = FakeAgenda()
        res = nr.run_reflection(force=True, state_path=tmp_path / "state.json",
                                events_path=events, votes_path=votes, agenda=ag, now=now)
        assert res["ran"] is True
        assert len(ag.topics) == 1
        assert ag.topics[0]["source"] == "nightly_reflection"
        assert "retorno_real_2" in ag.topics[0]["tags"]


def _write_agenda(fixture):
    pass