# -*- coding: utf-8 -*-
"""Tests: phase_c_watchlist — cobertura de los 3 métodos testeables.

Fase 2.4.3: phase_c_watchlist.py tenía 0 cobertura directa ni indirecta.
417 líneas activas (invocadas desde core/agent.py:55). Este test cubre:
  - _load_watchlist: parsing JSON (3 formatos) + manejo de errores
  - _score_posts: ranking puro por señales de oportunidad
  - _quality_gate: filtro de calidad de comentarios

NO cubre _generate_comment ni run() — requieren mock de LLM/API.
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from phases.phase_c_watchlist import PhaseCWatchlist


@pytest.fixture
def pcw(tmp_path):
    """Instancia mínima con mocks. watchlist_file en tmp_path."""
    return PhaseCWatchlist(
        moltbook_client=MagicMock(),
        model_cascade=MagicMock(),
        dedup_store=MagicMock(),
        own_comment_store=MagicMock(),
        watchlist_file=str(tmp_path / "wl.json"),
    )


# ── _load_watchlist ────────────────────────────────────────

def test_load_watchlist_nonexistent_file(pcw):
    """Archivo inexistente → watchlist vacía, sin crash."""
    pcw._load_watchlist()
    assert pcw.watchlist == []


def test_load_watchlist_list_format(pcw, tmp_path):
    """JSON lista directa → carga strings."""
    (tmp_path / "wl.json").write_text(
        json.dumps(["alice", "bob", "charlie"]), encoding="utf-8"
    )
    pcw._load_watchlist()
    assert pcw.watchlist == ["alice", "bob", "charlie"]


def test_load_watchlist_top_agents_format(pcw, tmp_path):
    """JSON {"top_agents": [...]} → extrae usernames."""
    (tmp_path / "wl.json").write_text(
        json.dumps({"top_agents": [{"username": "alice"}, "bob", {"username": "charlie"}]}),
        encoding="utf-8",
    )
    pcw._load_watchlist()
    assert pcw.watchlist == ["alice", "bob", "charlie"]


def test_load_watchlist_bad_json(pcw, tmp_path):
    """JSON inválido → watchlist vacía, no crash."""
    (tmp_path / "wl.json").write_text("{not valid json", encoding="utf-8")
    pcw._load_watchlist()
    assert pcw.watchlist == []


def test_load_watchlist_unexpected_format(pcw, tmp_path):
    """JSON con formato inesperado → watchlist vacía."""
    (tmp_path / "wl.json").write_text(
        json.dumps({"unexpected": "format"}), encoding="utf-8"
    )
    pcw._load_watchlist()
    assert pcw.watchlist == []


# ── _score_posts ───────────────────────────────────────────

def test_score_posts_empty_list(pcw):
    """Lista vacía → lista vacía."""
    assert pcw._score_posts([]) == []


def test_score_posts_first_comment_bonus(pcw):
    """comments_count=0 → +40."""
    post = {"comments_count": 0, "author": {}, "body": ""}
    result = pcw._score_posts([post])
    assert result[0][0] == 40


def test_score_posts_high_karma_bonus(pcw):
    """author.karma > 5000 → +20."""
    post = {"comments_count": 5, "author": {"karma": 6000}, "body": ""}
    result = pcw._score_posts([post])
    assert result[0][0] == 20


def test_score_posts_low_karma_no_bonus(pcw):
    """author.karma <= 5000 → sin bonus."""
    post = {"comments_count": 5, "author": {"karma": 4000}, "body": ""}
    result = pcw._score_posts([post])
    assert result[0][0] == 0


def test_score_posts_recent_bonus(pcw):
    """published_at < 30min → +30."""
    recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    post = {"comments_count": 5, "author": {}, "body": "", "published_at": recent}
    result = pcw._score_posts([post])
    assert result[0][0] == 30


def test_score_posts_old_post_no_recent_bonus(pcw):
    """published_at > 30min → sin bonus."""
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    post = {"comments_count": 5, "author": {}, "body": "", "published_at": old}
    result = pcw._score_posts([post])
    assert result[0][0] == 0


def test_score_posts_topic_keyword_bonus(pcw):
    """Body con keyword técnica → +10."""
    post = {"comments_count": 5, "author": {}, "body": "agent memory drift"}
    result = pcw._score_posts([post])
    assert result[0][0] == 10


def test_score_posts_compound_signals(pcw):
    """Múltiples señales se suman (40+20+30+10=100)."""
    recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    post = {
        "comments_count": 0,
        "author": {"karma": 6000},
        "body": "agent orchestration",
        "published_at": recent,
    }
    result = pcw._score_posts([post])
    assert result[0][0] == 100


def test_score_posts_invalid_date_ignored(pcw):
    """published_at inválido → no rompe, sin bonus."""
    post = {"comments_count": 5, "author": {}, "body": "", "published_at": "not-a-date"}
    result = pcw._score_posts([post])
    assert result[0][0] == 0


# ── _quality_gate (async) ──────────────────────────────────

@pytest.mark.asyncio
async def test_quality_gate_too_short(pcw):
    """Comentario < 80 chars → False."""
    post = {"topic": "specific unrelated topic"}
    assert await pcw._quality_gate("short comment", post) is False


@pytest.mark.asyncio
async def test_quality_gate_too_long(pcw):
    """Comentario > 600 chars → False."""
    post = {"topic": "specific unrelated topic"}
    comment = "mechanism boundary experiment measure " + "x" * 600
    assert await pcw._quality_gate(comment, post) is False


@pytest.mark.asyncio
async def test_quality_gate_repeats_topic(pcw):
    """Comentario que incluye el topic literal → False."""
    post = {"topic": "agent memory management"}
    comment = (
        "agent memory management is critical here. I would test this "
        "by measuring the boundary condition with an experiment to prove "
        "the mechanism works under realistic conditions."
    )
    assert await pcw._quality_gate(comment, post) is False


@pytest.mark.asyncio
async def test_quality_gate_no_mechanism_signal(pcw):
    """Comentario sin keywords de mecanismo/prueba → False.

    Nota: el comentario debe evitar TODAS las palabras de la lista:
    mechanism, boundary, if-then, experiment, measure, prove, falsable,
    decision, trigger, rollback, would test, i would measure, test this by.
    """
    post = {"topic": "specific unrelated topic"}
    comment = (
        "This is a generic comment that does not add any specific new value "
        "or concrete signal beyond restating what was already there in the "
        "original discussion without introducing any novel contribution."
    )
    assert len(comment) >= 80
    assert await pcw._quality_gate(comment, post) is False


@pytest.mark.asyncio
async def test_quality_gate_ends_with_question(pcw):
    """Comentario termina en ? → False (retórica)."""
    post = {"topic": "specific unrelated topic"}
    comment = (
        "I would test this by measuring the boundary condition where "
        "the mechanism fails under realistic load and see what happens "
        "when the experiment pushes past the threshold?"
    )
    assert await pcw._quality_gate(comment, post) is False


@pytest.mark.asyncio
async def test_quality_gate_valid_comment(pcw):
    """Comentario válido: 80-600 chars, no repite topic, tiene mecanismo, no ?."""
    post = {"topic": "specific unrelated topic"}
    comment = (
        "I would test this by measuring the boundary condition where "
        "the mechanism fails, and the experiment would give a clear "
        "decision threshold for triggering a rollback in production."
    )
    assert len(comment) >= 80
    assert len(comment) <= 600
    assert await pcw._quality_gate(comment, post) is True

