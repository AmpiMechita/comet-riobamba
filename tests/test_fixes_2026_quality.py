# -*- coding: utf-8 -*-
"""Tests de los fixes operativos y de calidad (agosto 2026):

C1  outbox retry marca dedup durable (evita duplicados en plataforma)
C2  cleanup del DedupStore compara fechas en el MISMO formato/zona (TTL real)
C3  create_comment 2xx + verification_required NO confirmada = exito (2xx=creado)
G1  quality gate tier=quality exige senal de sustancia (evidence o metric)
G2  shadow checks ungrounded bloquean en tier=quality
G3  claim checker fail-CLOSED si el LLM falla
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest_plugins = ("pytest_asyncio",)

from services.persistence import enqueue_outbox
from services.reply_cap import has_replied_to_comment
from services.dedup_store import DedupStore


# ── C1: outbox retry marca dedup durable ─────────────────────────

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


def test_c1_outbox_success_marks_reply_cap_and_commented_post(tmp_path):
    """C1: tras un retry exitoso del outbox, el comentario queda marcado en
    reply_cap (re-reply) y en commented_post (top-level duplicado) — el
    proximo scan NO debe volver a responder el mismo objetivo."""
    from tests.test_comment_outbox_retry import _make_agent as _make_agent_outbox
    import tests.test_comment_outbox_retry as _mod

    moltbook = MagicMock()
    moltbook.create_comment = MagicMock(return_value={
        "success": True, "status": 201, "id": "c-123",
    })
    ag = _make_agent_outbox(moltbook)
    post_id = "6828dc95-d4f6-4b45-8a6d-995bc29865b2"
    enqueue_outbox(kind="comment", payload={
        "post_id": post_id,
        "content": "test comment body",
        "parent_comment_id": "parent-0001",
    })

    published = ag._retry_comment_outbox()

    assert published == 1
    # re-reply guard: el comentario al que se respondio queda marcado
    assert has_replied_to_comment(f"{post_id}:parent-0001"), \
        "el outbox retry debe marcar reply_cap (evita re-reply)"
    # top-level guard: el post queda marcado como comentado
    assert DedupStore().is_commented_post(post_id), \
        "el outbox retry debe marcar commented_post (evita duplicado top-level)"
    agent_ids = DedupStore().get_agent_comment_ids()
    assert "c-123" in agent_ids.get(post_id, []), \
        "el comment id real debe quedar en agent_comment_ids"


def test_c1_outbox_success_top_level_marks_commented_post(tmp_path):
    """C1: comentario top-level (sin parent) marca commented_post."""
    from tests.test_comment_outbox_retry import _make_agent as _make_agent_outbox

    moltbook = MagicMock()
    moltbook.create_comment = MagicMock(return_value={
        "success": True, "status": 201, "id": "c-999",
    })
    ag = _make_agent_outbox(moltbook)
    post_id = "6828dc95-d4f6-4b45-8a6d-995bc29865b2"
    enqueue_outbox(kind="comment", payload={
        "post_id": post_id,
        "content": "top-level comment",
        "parent_comment_id": None,
    })

    published = ag._retry_comment_outbox()

    assert published == 1
    assert DedupStore().is_commented_post(post_id)


# ── C2: cleanup del DedupStore con TTL correcto ──────────────────

def test_c2_cleanup_preserves_recent_rows_same_format(tmp_path):
    """C2: el cleanup solo borra filas reales de >24h. El bug: created_at
    SQLite usa 'YYYY-MM-DD HH:MM:SS' (espacio, UTC) pero el cutoff usaba
    isoformat() ('T', hora local) -> ' ' < 'T' borraba TODO lo del dia
    anterior. Ahora ambos formatos coinciden."""
    from datetime import datetime, timedelta, timezone

    store = DedupStore()
    store._add("replied_comment", "fresh-key", "v")
    # Insertar filas con el formato SQLite real (espacio, UTC)
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S")
    recent_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    with store._get_conn() as conn:
        conn.execute(
            "INSERT INTO dedup_store (namespace, key, created_at) VALUES (?, ?, ?)",
            ("replied_comment", "old-key", old_ts),
        )
        conn.execute(
            "INSERT INTO dedup_store (namespace, key, created_at) VALUES (?, ?, ?)",
            ("replied_comment", "recent-key", recent_ts),
        )

    deleted = store.cleanup(older_than_hours=24)

    assert deleted >= 1, "debe borrar al menos la fila vieja"
    assert store._has("replied_comment", "old-key") is False, "fila de 30h debe purgarse"
    assert store._has("replied_comment", "recent-key") is True, "fila de 2h DEBE sobrevivir"
    assert store._has("replied_comment", "fresh-key") is True


# ── C3: create_comment 2xx = publicado ───────────────────────────

def test_c3_create_comment_2xx_verification_not_confirmed_is_success(tmp_path):
    """C3: un HTTP 2xx con verification_required pero sin _verified es EXITO:
    el comentario ya fue creado en el servidor; tratarlo como fallo hacia que
    el caller reintentara un 2xx y publicara un duplicado."""
    from tests.test_moltbook_api_client import _make_client

    client = _make_client()
    client._wait_for_write_token = MagicMock()
    client._call_write = MagicMock(return_value={
        "status": 200,
        "data": {"comment": {"id": "c-abc"}, "verification_required": True},
    })
    # _handle_verification no puede resolver (sin llm_client) -> _verified ausente
    client.llm_client = None

    result = client.create_comment("post-1", "hello")

    assert result["success"] is True, "2xx = comentario creado, aunque la verificacion no se confirme"


# ── G1: quality gate exige sustancia en tier=quality ─────────────

def test_g1_quality_gate_requires_evidence_or_metric(tmp_path):
    from phases.phase_b import PhaseB

    assert PhaseB._passes_quality_gate("This reply has no substance at all beyond restating the obvious point the post made", require_evidence=True) is False
    assert PhaseB._passes_quality_gate("The measured latency dropped 40% after we deployed the fix and observed the queue drain in production", require_evidence=True) is True
    assert PhaseB._passes_quality_gate("Short", require_evidence=True) is False
    # Sin require_evidence, el texto sin sustancia sigue pasando (comportamiento previo)
    assert PhaseB._passes_quality_gate("This reply has no substance at all beyond restating the obvious point the post made", require_evidence=False) is True


# ── G2: shadow checks bloquean en tier=quality ───────────────────

def _make_pb():
    from phases.deps import PhaseBDeps
    from phases.phase_b import PhaseB

    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_comments_per_post": 5, "max_comments_per_day": 10},
        agent_name="test-agent",
    )
    pb = PhaseB(deps)
    return pb


def test_g2_block_ungrounded_numeric_in_quality(tmp_path):
    """G2: un reply tier=quality con numero sin ancla en la fuente se rechaza."""
    pb = _make_pb()
    source = "The post describes a retry backoff strategy for queues under load."
    reply = "Our results show the queue drained 38% faster after switching backoff, and the retry storm ended completely."
    # El 38% no esta en la fuente -> ungrounded_numeric_specificity debe disparar
    pb._shadow_quality_log_path = tmp_path / "shadow.jsonl"
    score, reasons = pb._score_reply_draft(reply, source, block_ungrounded=True)

    assert score < 10, f"numeros sin ancla deben bloquear en tier=quality, score={score} reasons={reasons}"
    assert any("ungrounded" in r for r in reasons)


def test_g2_grounded_reply_passes_in_quality(tmp_path):
    """G2: un reply que ancla el numero a la fuente NO se bloquea."""
    pb = _make_pb()
    source = "In the post you mention the queue drained 38% faster with the new backoff."
    reply = "Exactly — the 38% you measured comes from the backoff change, and the retry budget stays bounded."
    pb._shadow_quality_log_path = tmp_path / "shadow.jsonl"
    score, reasons = pb._score_reply_draft(reply, source, block_ungrounded=True)

    assert score > 0, f"reply grounded en la fuente no debe bloquearse: {reasons}"


def test_g3_claim_check_fail_closed(tmp_path):
    """G3: si el claim checker falla (LLM caido/JSON roto), el claim NO se
    valida: el resultado es on_topic=False (fail-CLOSED), nunca on_topic=True."""
    import services.claim_checker as cc

    class BoomLLM:
        async def generate(self, **kwargs):
            raise RuntimeError("LLM down")

    result = asyncio_run(cc.check_claim(
        {"central_claim": "X", "reply_must_address": "Y"},
        "some reply",
        BoomLLM(),
        tier="flash",
    ))

    assert result["on_topic"] is False, f"fail-closed: {result}"
    assert result["score"] == 0.0


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
