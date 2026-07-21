# -*- coding: utf-8 -*-
"""Tests for services.arxiv_topic_source.

Usa un fixture XML real (formato Atom de la API de arXiv) para verificar el
parseo sin depender de red -- el sandbox de CI/dev puede no tener salida a
export.arxiv.org (ver docs/ESTRATEGIA_MOLTBOOK_2026-07-21.md).
"""

from services.arxiv_topic_source import (
    build_topic_string,
    parse_arxiv_response,
    refresh_agenda_from_arxiv,
)
from services.research_agenda import ResearchAgenda

SAMPLE_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2606.12345v1</id>
    <updated>2026-06-24T00:00:00Z</updated>
    <published>2026-06-24T00:00:00Z</published>
    <title>Reliable Tool Calling in Long-Running Multi-Agent Systems</title>
    <summary>
      We study failure recovery in long-running agent orchestration pipelines
      under partial tool failures and propose a checkpointing protocol.
    </summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2606.54321v2</id>
    <updated>2026-06-20T00:00:00Z</updated>
    <published>2026-06-18T00:00:00Z</published>
    <title>  Context Memory Drift in Production LLM Agents  </title>
    <summary>Empirical study of memory drift across 400 production deployments.</summary>
  </entry>
</feed>
"""

EMPTY_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>
"""

MALFORMED_XML = "<not-valid-xml"


def test_parse_arxiv_response_extracts_id_and_title():
    papers = parse_arxiv_response(SAMPLE_ARXIV_XML)
    assert len(papers) == 2
    assert papers[0]["id"] == "2606.12345v1"
    assert papers[0]["title"] == "Reliable Tool Calling in Long-Running Multi-Agent Systems"
    assert "checkpointing" in papers[0]["summary"]


def test_parse_arxiv_response_strips_whitespace_in_title():
    papers = parse_arxiv_response(SAMPLE_ARXIV_XML)
    assert papers[1]["title"] == "Context Memory Drift in Production LLM Agents"


def test_parse_arxiv_response_empty_feed_returns_empty_list():
    assert parse_arxiv_response(EMPTY_ARXIV_XML) == []


def test_parse_arxiv_response_malformed_xml_returns_empty_list():
    assert parse_arxiv_response(MALFORMED_XML) == []


def test_build_topic_string_contains_allowed_signal_and_citation():
    paper = {"id": "2606.12345v1", "title": "Reliable Tool Calling", "summary": ""}
    topic = build_topic_string(paper)
    # Debe pasar _is_allowed_topic() de phase_a_content.py (requiere "agent"/"production").
    assert "agent" in topic.lower()
    assert "production" in topic.lower()
    # Debe traer la cita verificable.
    assert "arXiv:2606.12345v1" in topic
    assert "Reliable Tool Calling" in topic


def test_refresh_agenda_from_arxiv_adds_topics(monkeypatch, tmp_path):
    fake_papers = [
        {"id": "2606.11111v1", "title": "Paper One", "summary": "s1"},
        {"id": "2606.22222v1", "title": "Paper Two", "summary": "s2"},
    ]
    monkeypatch.setattr(
        "services.arxiv_topic_source.fetch_recent_papers", lambda **kwargs: fake_papers
    )
    monkeypatch.setattr(
        "services.arxiv_topic_source.load_agenda", lambda: ResearchAgenda()
    )
    saved = {}
    monkeypatch.setattr(
        "services.arxiv_topic_source.save_agenda", lambda agenda: saved.setdefault("agenda", agenda)
    )

    added = refresh_agenda_from_arxiv()

    assert added == 2
    assert len(saved["agenda"].pending_topics) == 2
    assert saved["agenda"].pending_topics[0]["source"] == "arxiv"


def test_refresh_agenda_from_arxiv_skips_duplicates(monkeypatch):
    paper = {"id": "2606.11111v1", "title": "Paper One", "summary": "s1"}
    monkeypatch.setattr(
        "services.arxiv_topic_source.fetch_recent_papers", lambda **kwargs: [paper]
    )
    existing_agenda = ResearchAgenda()
    existing_agenda.add_topic(build_topic_string(paper), source="arxiv")
    monkeypatch.setattr(
        "services.arxiv_topic_source.load_agenda", lambda: existing_agenda
    )
    save_calls = []
    monkeypatch.setattr(
        "services.arxiv_topic_source.save_agenda", lambda agenda: save_calls.append(agenda)
    )

    added = refresh_agenda_from_arxiv()

    assert added == 0
    assert save_calls == []  # no debe guardar si no hubo nada nuevo


def test_refresh_agenda_from_arxiv_no_papers_returns_zero(monkeypatch):
    monkeypatch.setattr("services.arxiv_topic_source.fetch_recent_papers", lambda **kwargs: [])
    added = refresh_agenda_from_arxiv()
    assert added == 0
