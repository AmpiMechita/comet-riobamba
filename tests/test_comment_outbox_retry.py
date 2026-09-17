"""Tests for _retry_comment_outbox failure classification (Fix: 4xx -> failed).

A diferencia del outbox de posts, el de comentarios no clasificaba los errores
4xx como no-reintentables: un 404 "Parent comment not found" quedaba en retry
infinito con backoff. Estos tests fijan el comportamiento esperado.
"""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

import services.persistence as sp
from services.persistence import (
    enqueue_outbox,
    fetch_pending_outbox,
    mark_outbox,
    update_outbox_backoff,
)


@pytest.fixture(autouse=True)
def _isolate_outbox_db(tmp_path, monkeypatch):
    """Redirige el DB del outbox a tmp_path.

    Sin esto, los tests leen/escriben la tabla REAL del outbox, y
    _outbox_status() devuelve la primera fila global (posiblemente una
    entrada 'published' de una corrida anterior).
    """
    db = tmp_path / "test_outbox.db"
    monkeypatch.setattr(sp, "DB_PATH", db, raising=False)


def _make_agent(moltbook):
    from core.agent import COMETRiobambaAgent
    import config.config as _cfg

    with (
        patch("core.agent.create_telegram_client", return_value=None),
        patch("core.agent.PlatformAwareness", return_value=None),
        patch.dict(_cfg.behavior_cfg, values={
            "phase_a_publish_enabled": False,
            "phase_b_enabled": False,
            "phase_c_enabled": False,
            "whisper_mode": False,
        }, clear=False),
    ):
        ag = COMETRiobambaAgent(
            credentials=MagicMock(moltbook_api_key="sk-test"),
            model_cascade=MagicMock(),
            moltbook_client=moltbook,
        )
    ag.state = MagicMock(posts_today=0, comments_today=0)
    return ag


def _enqueue_comment():
    enqueue_outbox(kind="comment", payload={
        "post_id": "6828dc95-d4f6-4b45-8a6d-995bc29865b2",
        "content": "test comment body",
        "parent_comment_id": "parent-0001",
    })


def _outbox_status(kind="comment"):
    c = sqlite3.connect(sp.DB_PATH)
    try:
        row = c.execute("SELECT status, retry_attempt FROM outbox WHERE kind=?", (kind,)).fetchone()
        return (row[0], row[1]) if row else None
    finally:
        c.close()


def test_comment_outbox_404_marks_failed(tmp_path):
    """404 (parent comment not found) es un error permanente -> 'failed', no retry."""
    moltbook = MagicMock()
    moltbook.create_comment = MagicMock(return_value={
        "success": False, "status": 404, "id": None,
        "raw": {"message": "Parent comment not found"},
    })
    ag = _make_agent(moltbook)
    _enqueue_comment()

    published = ag._retry_comment_outbox()

    assert published == 0
    assert _outbox_status() == ("failed", 0)
    # Ya no queda pendiente para reintentar.
    pending = [i for i in fetch_pending_outbox(limit=10) if i.get("kind") == "comment"]
    assert pending == []


def test_comment_outbox_400_marks_failed(tmp_path):
    """Cualquier 4xx client error -> 'failed' (no reintentar)."""
    moltbook = MagicMock()
    moltbook.create_comment = MagicMock(return_value={
        "success": False, "status": 400, "id": None,
        "raw": {"message": "Bad request"},
    })
    ag = _make_agent(moltbook)
    _enqueue_comment()

    published = ag._retry_comment_outbox()

    assert published == 0
    assert _outbox_status() == ("failed", 0)


def test_comment_outbox_429_retries_with_backoff(tmp_path):
    """429 rate-limit -> sigue 'pending' y sube retry_attempt."""
    moltbook = MagicMock()
    moltbook.create_comment = MagicMock(return_value={
        "success": False, "status": 429, "id": None,
        "retry_after_seconds": 120,
    })
    ag = _make_agent(moltbook)
    _enqueue_comment()

    published = ag._retry_comment_outbox()

    assert published == 0
    assert _outbox_status() == ("pending", 1)


def test_comment_outbox_500_retries_with_backoff(tmp_path):
    """5xx transitorio -> sigue 'pending' con backoff."""
    moltbook = MagicMock()
    moltbook.create_comment = MagicMock(return_value={
        "success": False, "status": 500, "id": None,
        "raw": {"message": "Internal"},
    })
    ag = _make_agent(moltbook)
    _enqueue_comment()

    published = ag._retry_comment_outbox()

    assert published == 0
    assert _outbox_status() == ("pending", 1)


def test_comment_outbox_success_marks_published(tmp_path):
    """Éxito -> 'published' e incrementa el contador del día."""
    moltbook = MagicMock()
    moltbook.create_comment = MagicMock(return_value={
        "success": True, "status": 201, "id": "c-123",
    })
    ag = _make_agent(moltbook)
    _enqueue_comment()

    published = ag._retry_comment_outbox()

    assert published == 1
    ag.state.increment_comments_today.assert_called_once()
    assert _outbox_status() == ("published", 0)


def test_comment_outbox_persists_failed_flag_across_calls(tmp_path):
    """Tras marcar failed, un segundo ciclo no reintenta (ya no es pending)."""
    moltbook = MagicMock()
    moltbook.create_comment = MagicMock(return_value={
        "success": False, "status": 404, "id": None,
        "raw": {"message": "Parent comment not found"},
    })
    ag = _make_agent(moltbook)
    _enqueue_comment()

    assert ag._retry_comment_outbox() == 0
    assert _outbox_status() == ("failed", 0)

    # Segundo ciclo: el item ya no está pending -> no se llama de nuevo a la API.
    pending = [i for i in fetch_pending_outbox(limit=10) if i.get("kind") == "comment"]
    assert pending == []
    assert ag._retry_comment_outbox() == 0
    moltbook.create_comment.assert_called_once()
