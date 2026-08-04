# -*- coding: utf-8 -*-
"""Tests for services/postmortem_source.py — registra post-mortems reales en la agenda."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeAgenda:
    def __init__(self):
        self.pending_topics = []

    def add_topic(self, topic, source="", tags=None):
        existing = {t["topic"] for t in self.pending_topics}
        if topic not in existing:
            self.pending_topics.append({
                "topic": topic, "source": source, "tags": tags or [],
                "covered": False, "created_at": "2026-08-04T00:00:00+00:00",
            })


def test_register_adds_all_postmortems():
    from services.postmortem_source import register_postmortems, POSTMORTEMS
    agenda = FakeAgenda()
    added = register_postmortems(agenda)
    assert added == len(POSTMORTEMS)
    assert len(agenda.pending_topics) == len(POSTMORTEMS)


def test_register_is_idempotent():
    from services.postmortem_source import register_postmortems, POSTMORTEMS
    agenda = FakeAgenda()
    register_postmortems(agenda)
    added_second = register_postmortems(agenda)
    assert added_second == len(POSTMORTEMS)  # add_topic dedup: no duplica
    assert len(agenda.pending_topics) == len(POSTMORTEMS)


def test_postmortems_use_source_and_tags():
    from services.postmortem_source import register_postmortems, POSTMORTEMS
    agenda = FakeAgenda()
    register_postmortems(agenda)
    for t in agenda.pending_topics:
        assert t["source"] == "postmortem_own"
        assert "postmortem" in t["tags"]
        assert "own" in t["tags"]


def test_postmortems_have_verifiable_content():
    """Cada post-mortem tiene titulo, leccion y detalle no vacios."""
    from services.postmortem_source import POSTMORTEMS
    assert len(POSTMORTEMS) >= 4
    for title, lesson, detail in POSTMORTEMS:
        assert len(title) > 10
        assert len(lesson) > 20
        assert len(detail) > 20
