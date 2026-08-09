# -*- coding: utf-8 -*-
"""Tests para el seguimiento de hilos en posts ajenos (thread follow-ups).

Contexto: el agente comenta en el feed y nunca vuelve. Si alguien responde a
SU comentario, no contesta y la conversación muere. `_execute_thread_followups`
cierra ese hueco: revisita los posts comentados en las últimas 48 h, busca
respuestas A NUESTROS comentarios y responde ENHEBRADO.

Distinción clave que estos tests protegen:
  - apilar comentarios top-level = DOGPILE → anti-dogpile (NO aplica a follow-ups)
  - sostener un hilo enhebrado = CONVERSACIÓN → esta función
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock

import pytest

import services.dedup_store as ds
import services.reply_cap as rcap
from phases.phase_b import PhaseB
from phases.deps import PhaseBDeps


# Reply del agente que pasa todos los gates de _safe_publish_comment
# (50-500 chars, sin opener prohibido, sin medición fabricada, termina en '.').
_GOOD_FOLLOWUP = (
    "The failure mode here is unbounded retries; a token-bucket rate limit with "
    "exponential backoff plus a circuit breaker caps the blast radius."
)

# Respuesta on-niche a nuestro comentario (pasa triage: tiene '?' + tech terms).
_ON_NICHE_REPLY = (
    "But how does the circuit breaker interact with the agent retry loop when "
    "API latency spikes under load?"
)

POST = "11111111-1111-1111-1111-111111111111"
AGENT = "COMET-RIOBAMBA"


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    """Aísla dedup store y contadores per-post a tmp (el conftest ya redirige
    el dedup durable per-comment, el ledger de interlocutores y reply_history)."""
    monkeypatch.setattr(ds.DedupStore, "_default_db_path", tmp_path / "comet_dedup.db")
    monkeypatch.setattr(rcap, "_REPLIES_PER_POST_PATH", tmp_path / "replies_per_post.json")
    monkeypatch.setattr(rcap, "_FOLLOWUPS_PER_POST_PATH", tmp_path / "followups_per_post.json")
    yield


def _make_pb(followup_text=_GOOD_FOLLOWUP, **cfg):
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={
            "max_comments_per_post": 6,
            "max_comments_per_day": 10,
            "max_comment_replies_per_cycle": 4,
            "max_feed_comments_per_post": 3,
            "max_feed_replies_per_day": 3,
            "delay_between_comments": 0,
            **cfg,
        },
        agent_name=AGENT,
    )
    pb = PhaseB(deps)
    pb.llm = MagicMock()
    pb.api = MagicMock()
    pb.api.create_comment.return_value = {"success": True, "id": "fu-new", "status": 201}
    # Aísla la generación LLM: canned reply que pasa los gates.
    pb._generate_own_post_reply = AsyncMock(return_value=followup_text)
    return pb


def _our_top_level(cid="ours-1"):
    return {
        "id": cid, "parent_id": None,
        "author": {"name": AGENT},
        "content": "our top-level comment on someone else's post",
        "text": "our top-level comment on someone else's post",
    }


def _reply_to(parent_id, cid="reply-1", author="other_agent", content=_ON_NICHE_REPLY):
    return {
        "id": cid, "parent_id": parent_id,
        "author": {"name": author},
        "content": content, "text": content,
    }


@pytest.mark.asyncio
async def test_reply_to_our_comment_generates_threaded_followup():
    """Post ajeno con una respuesta a nuestro comentario → genera follow-up
    enhebrado con parent_comment_id correcto (= comentario que nos respondió)."""
    pb = _make_pb()
    pb._commented_post_ids = {POST: datetime.now().isoformat()}
    pb._agent_comment_ids = {POST: ["ours-1"]}
    pb.api.fetch_post_comments.return_value = [
        _our_top_level("ours-1"),
        _reply_to("ours-1", "reply-1"),
    ]

    results = await pb._execute_thread_followups(remaining_cycle_slots=4)

    assert len(results) == 1
    assert results[0]["parent_comment_id"] == "reply-1"
    assert results[0]["kind"] == "thread_followup"
    # Se publicó ENHEBRADO al comentario que nos respondió.
    _, kwargs = pb.api.create_comment.call_args
    assert kwargs["post_id"] == POST
    assert kwargs["parent_comment_id"] == "reply-1"
    # Contador propio de follow-ups incrementado.
    assert pb._get_followups_count(POST) == 1


@pytest.mark.asyncio
async def test_same_comment_not_answered_twice_durable_dedup():
    """El mismo comentario no se responde dos veces (dedup durable cross-call)."""
    pb = _make_pb()
    pb._commented_post_ids = {POST: datetime.now().isoformat()}
    pb._agent_comment_ids = {POST: ["ours-1"]}
    pb.api.fetch_post_comments.return_value = [
        _our_top_level("ours-1"),
        _reply_to("ours-1", "reply-1"),
    ]

    first = await pb._execute_thread_followups(remaining_cycle_slots=4)
    assert len(first) == 1

    second = await pb._execute_thread_followups(remaining_cycle_slots=4)
    assert second == []
    # Solo una publicación en total.
    assert pb.api.create_comment.call_count == 1


@pytest.mark.asyncio
async def test_depth_over_max_is_not_followed():
    """Profundidad >= MAX_CONVERSATION_DEPTH (3) → no se sigue el hilo."""
    pb = _make_pb()
    pb._commented_post_ids = {POST: datetime.now().isoformat()}
    pb._agent_comment_ids = {POST: ["ours-deep"]}
    # Cadena: a(0) → b(1) → ours-deep(2) → reply(3). reply está en depth 3.
    pb.api.fetch_post_comments.return_value = [
        {"id": "a", "parent_id": None, "author": {"name": "u1"}, "content": "root", "text": "root"},
        {"id": "b", "parent_id": "a", "author": {"name": "u2"}, "content": "l1", "text": "l1"},
        {"id": "ours-deep", "parent_id": "b", "author": {"name": AGENT},
         "content": "our deep comment", "text": "our deep comment"},
        _reply_to("ours-deep", "reply-deep"),
    ]

    results = await pb._execute_thread_followups(remaining_cycle_slots=4)

    assert results == []
    pb.api.create_comment.assert_not_called()


@pytest.mark.asyncio
async def test_followup_not_blocked_by_top_level_guard_nor_antidogpile(tmp_path):
    """Follow-ups NO son bloqueados por el guard de 'ya comenté este post'
    (implícito: el path itera posts ya comentados) ni por el cap anti-dogpile.
    Se pre-carga el contador anti-dogpile en su tope y el follow-up igual publica."""
    pb = _make_pb()
    # Anti-dogpile ya en el tope para este post.
    cap = rcap.get_cap()
    rcap._REPLIES_PER_POST_PATH.write_text(json.dumps({POST: cap}), encoding="utf-8")

    pb._commented_post_ids = {POST: datetime.now().isoformat()}
    pb._agent_comment_ids = {POST: ["ours-1"]}
    pb.api.fetch_post_comments.return_value = [
        _our_top_level("ours-1"),
        _reply_to("ours-1", "reply-1"),
    ]

    results = await pb._execute_thread_followups(remaining_cycle_slots=4)

    assert len(results) == 1, "el follow-up enhebrado debe publicarse pese al anti-dogpile en tope"
    # El contador anti-dogpile NO se movió (los follow-ups no lo consumen).
    assert rcap.get_replies_for_post(POST, path=pb._replies_per_post_path) == cap
    # El contador propio de follow-ups sí avanzó.
    assert pb._get_followups_count(POST) == 1


@pytest.mark.asyncio
async def test_off_niche_one_liner_discarded_by_triage():
    """Respuesta off-niche/one-liner a nuestro comentario → descartada por triage."""
    pb = _make_pb()
    pb._commented_post_ids = {POST: datetime.now().isoformat()}
    pb._agent_comment_ids = {POST: ["ours-1"]}
    pb.api.fetch_post_comments.return_value = [
        _our_top_level("ours-1"),
        _reply_to("ours-1", "reply-1", content="ok thanks!"),
    ]

    results = await pb._execute_thread_followups(remaining_cycle_slots=4)

    assert results == []
    pb.api.create_comment.assert_not_called()


@pytest.mark.asyncio
async def test_post_commented_five_days_ago_not_revisited():
    """Post comentado hace 5 días → no se revisita (ventana de 48 h)."""
    pb = _make_pb()
    pb._commented_post_ids = {POST: (datetime.now() - timedelta(days=5)).isoformat()}
    pb._agent_comment_ids = {POST: ["ours-1"]}
    pb.api.fetch_post_comments.return_value = [
        _our_top_level("ours-1"),
        _reply_to("ours-1", "reply-1"),
    ]

    results = await pb._execute_thread_followups(remaining_cycle_slots=4)

    assert results == []
    # Ni siquiera se piden los comentarios de un post muerto.
    pb.api.fetch_post_comments.assert_not_called()


@pytest.mark.asyncio
async def test_followup_cap_per_post_respected():
    """Cap propio AGENT_MAX_FOLLOWUPS_PER_POST: alcanzado el tope, no más
    follow-ups en ese post aunque haya respuestas pendientes."""
    pb = _make_pb()
    pb._commented_post_ids = {POST: datetime.now().isoformat()}
    pb._agent_comment_ids = {POST: ["ours-1"]}
    # Pre-cargar el contador de follow-ups en su tope.
    rcap._FOLLOWUPS_PER_POST_PATH.write_text(
        json.dumps({POST: pb.max_followups_per_post}), encoding="utf-8"
    )
    pb.api.fetch_post_comments.return_value = [
        _our_top_level("ours-1"),
        _reply_to("ours-1", "reply-1"),
    ]

    results = await pb._execute_thread_followups(remaining_cycle_slots=4)

    assert results == []
    pb.api.create_comment.assert_not_called()


@pytest.mark.asyncio
async def test_reply_from_ourselves_is_ignored():
    """Un comentario 'hijo' que es del propio agente no cuenta como respuesta
    a la que haya que dar seguimiento."""
    pb = _make_pb()
    pb._commented_post_ids = {POST: datetime.now().isoformat()}
    pb._agent_comment_ids = {POST: ["ours-1"]}
    pb.api.fetch_post_comments.return_value = [
        _our_top_level("ours-1"),
        _reply_to("ours-1", "self-reply", author=AGENT),
    ]

    results = await pb._execute_thread_followups(remaining_cycle_slots=4)

    assert results == []
    pb.api.create_comment.assert_not_called()
