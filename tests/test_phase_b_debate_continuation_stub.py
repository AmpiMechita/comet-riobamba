"""
Tests de integracion para el debate continuation en posts propios.

Contexto: el agente publica un post, la comunidad comenta con preguntas y el
agente debe sostener el debate (hasta MAX_TURNS_PER_THREAD=4 turnos). El
bloque vive DENTRO de _process_own_post (orchestrator.py, "Debate
continuation"): tras procesar la cola del ciclo, si el hilo sigue abierto
(can_continue_thread: hay pregunta sin cerrar, turnos < 4, no cerrado) y el
comentario aun no fue respondido (strict dedup), genera y publica una reply
adicional enhebrada.

Historico: este archivo era un stub con xfail pidiendo _load_agent_comment_ids
y _execute_debate_continuations como metodos del modulo monolitico
phases/phase_b.py. Ese modulo ya no existe (refactor a paquete, commit
705643c); la persistencia existe (orchestrator:658/670) y el debate se
ejecuta dentro del flujo propio. Estos tests validan el comportamiento REAL.
"""
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.conversation_state as cs
import services.dedup_store as ds
from phases.deps import PhaseBDeps
from phases.phase_b import PhaseB

POST = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Aisla dedup store, conversation_state y counters a tmp (nunca tocar
    data/ real: los IDs de produccion en el dedup durable falseaban el
    strict-dedup del bloque debate)."""
    monkeypatch.setattr(ds.DedupStore, "_default_db_path", tmp_path / "comet_dedup.db")
    monkeypatch.setattr(cs, "CONVERSATIONS_PATH", tmp_path / "conversations.json")
    import services.reply_cap as rcap
    monkeypatch.setattr(rcap, "_REPLIES_PER_POST_PATH", tmp_path / "replies_per_post.json")
    monkeypatch.setattr(rcap, "_FOLLOWUPS_PER_POST_PATH", tmp_path / "followups_per_post.json")
    monkeypatch.setattr(rcap, "_TOTAL_REPLIES_PER_POST_PATH", tmp_path / "total_replies_per_post.json")
    yield


def _make_pb():
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={
            "max_comments_per_post": 50,
            "max_comments_per_day": 50,
            "max_comment_replies_per_cycle": 50,
            "max_feed_replies_per_day": 3,
            "delay_between_comments": 0,
        },
        agent_name="COMET-RIOBAMBA",
        get_comments_today=lambda: 0,
        increment_comments_today=lambda: 0,
    )
    pb = PhaseB(deps)
    pb.llm = MagicMock()
    pb.api = MagicMock()
    pb.api.create_comment.return_value = {"success": True, "id": "r1", "status": 201}
    pb._get_own_post_ids = lambda: {POST}
    return pb


def _comment(cid, author="user1", text="But how does the rate limiter behave under load?",
             created="2026-08-12T10:00:00Z"):
    return {
        "id": cid, "author": {"name": author},
        "content": text, "text": text, "created_at": created,
    }


def _wire_fake_post_own_reply(pb):
    calls = []

    async def fake_post_own_reply(post_id, comment_id, author, comment_text, thread_history=""):
        calls.append((comment_id, comment_text))
        pb._replied_comment_ids.add(f"{post_id}:{comment_id}")
        pb._dedup.mark_replied(f"{post_id}:{comment_id}")
        return {"status": "ok", "post_id": post_id, "comment_id": comment_id}

    pb._post_own_reply = fake_post_own_reply
    return calls


# ── Debate continuation: flujo real del orchestrator ──────────────

@pytest.mark.asyncio
async def test_debate_continuation_replies_when_loop_skipped_comment():
    """Comentario con pregunta que el triage del loop rechaza (low_value) pero
    el hilo queda abierto: el bloque debate continuation lo rescata y
    responde enhebrado (una reply, turno registrado)."""
    pb = _make_pb()
    calls = _wire_fake_post_own_reply(pb)
    pb._decide_reply = MagicMock(return_value=MagicMock(should_reply=False, reason="low_value", score=0.1))
    pb._generate_own_post_reply = AsyncMock(return_value="Debate continuation: the rate limiter uses a token bucket.")
    pb.api.fetch_post_comments.return_value = [_comment("c1")]

    results = await pb._process_own_post(POST)

    assert len(results) == 1, f"el debate continuation debe publicar 1 reply, got {len(results)}"
    assert results[0]["comment_id"] == "c1"
    assert calls == [("c1", "But how does the rate limiter behave under load?")]
    thread = cs.get_or_create_thread(POST)
    assert thread["turns_in_thread"] == 1, f"turno debe registrarse, got {thread}"


@pytest.mark.asyncio
async def test_debate_continuation_no_double_reply_to_same_comment():
    """El loop ya respondio al comentario: el strict dedup impide que el
    bloque debate publique una SEGUNDA reply al mismo comment_id."""
    pb = _make_pb()
    calls = _wire_fake_post_own_reply(pb)
    pb._decide_reply = MagicMock(return_value=MagicMock(should_reply=True, reason="test", score=0.9))
    pb._generate_own_post_reply = AsyncMock(return_value="Reply to the rate limiter question.")
    pb.api.fetch_post_comments.return_value = [_comment("c1")]

    results = await pb._process_own_post(POST)

    assert len(results) == 1, "1 sola reply al comentario (loop), no 2"
    assert len(calls) == 1, f"no debe duplicarse la respuesta, got {calls}"


@pytest.mark.asyncio
async def test_debate_continuation_closes_thread_on_semantic_duplicate():
    """La reply propuesta por el bloque es duplicado semantico de un reply
    previo del agente en el hilo → NO se publica y el hilo se cierra."""
    pb = _make_pb()
    calls = _wire_fake_post_own_reply(pb)
    pb._decide_reply = MagicMock(return_value=MagicMock(should_reply=False, reason="low_value", score=0.1))
    pb._generate_own_post_reply = AsyncMock(return_value="A token-bucket rate limiter caps the blast radius.")
    # Reply previo del agente con el mismo argumento (duplicado semantico).
    pb.api.fetch_post_comments.return_value = [
        _comment("c0", author="COMET-RIOBAMBA",
                 text="A token-bucket rate limiter caps the blast radius."),
        _comment("c1", text="But how does the rate limiter behave under load?"),
    ]

    results = await pb._process_own_post(POST)

    assert len(results) == 0, f"duplicado semantico NO debe publicarse, got {len(results)}"
    assert calls == [], f"_post_own_reply no debe llamarse, got {calls}"
    assert cs.is_thread_closed(POST), "el hilo debe cerrarse tras duplicado"


@pytest.mark.asyncio
async def test_debate_continuation_respects_closed_thread():
    """Hilo cerrado (gracias/aporte final del interlocutor): el bloque debate
    continuation NO agrega una segunda respuesta (can_continue_thread=False);
    el loop principal sigue respondiendo comentarios dirigidos (esa es la
    politica de cierre: corta la CONTINUACION, no el reply directo)."""
    pb = _make_pb()
    calls = _wire_fake_post_own_reply(pb)
    pb._decide_reply = MagicMock(return_value=MagicMock(should_reply=True, reason="test", score=0.9))
    pb._generate_own_post_reply = AsyncMock(return_value="A token-bucket rate limiter caps the blast radius.")
    cs.close_thread(POST)
    pb.api.fetch_post_comments.return_value = [
        _comment("c1", text="Thanks, that helps a lot!"),
    ]

    results = await pb._process_own_post(POST)

    # 1 reply directa del loop, 0 extra del bloque debate (hilo cerrado).
    assert len(results) == 1
    assert len(calls) == 1, f"hilo cerrado no debe continuar el debate, got {calls}"
    assert cs.can_continue_thread(POST) is False


@pytest.mark.asyncio
async def test_debate_continuation_has_no_open_question_skips():
    """Comentario sin pregunta (afirmacion) → open_questions=False → el
    bloque debate no dispara (no se fabrica un debate que no existe)."""
    pb = _make_pb()
    calls = _wire_fake_post_own_reply(pb)
    pb._decide_reply = MagicMock(return_value=MagicMock(should_reply=True, reason="test", score=0.9))
    pb._generate_own_post_reply = AsyncMock(return_value="Interesting point, agreed.")
    pb.api.fetch_post_comments.return_value = [
        _comment("c1", text="This is an interesting approach to rate limiting."),
    ]

    results = await pb._process_own_post(POST)

    # El loop responde el comentario (1), pero el bloque debate NO agrega
    # una segunda respuesta por falta de pregunta abierta.
    assert len(results) == 1
    assert len(calls) == 1, f"no debe haber continuation sin pregunta, got {calls}"


@pytest.mark.asyncio
async def test_debate_continuation_respects_max_turns():
    """MAX_TURNS_PER_THREAD alcanzado (4): can_continue_thread=False → sin
    mas replies en el hilo, aunque haya preguntas abiertas."""
    from services.conversation_state import MAX_TURNS_PER_THREAD

    pb = _make_pb()
    calls = _wire_fake_post_own_reply(pb)
    pb._decide_reply = MagicMock(return_value=MagicMock(should_reply=False, reason="low_value", score=0.1))
    pb._generate_own_post_reply = AsyncMock(return_value="Another turn in the debate.")
    for _ in range(MAX_TURNS_PER_THREAD):
        cs.register_agent_reply(POST)
    cs.update_open_questions(POST, "Still one question?")
    pb.api.fetch_post_comments.return_value = [
        _comment("c1", text="But how does the rate limiter behave under load?"),
    ]

    results = await pb._process_own_post(POST)

    assert results == [], f"max turns alcanzado: no mas replies, got {len(results)}"
    assert calls == []
    assert cs.can_continue_thread(POST) is False


# ── Persistencia de agent_comment_ids (dependencia del debate) ────

def test_agent_comment_ids_load_save_roundtrip():
    """_load_agent_comment_ids / _save_agent_comment_ids existen y hacen
    roundtrip (el debate continuation depende de conocer nuestros comment
    IDs para detectar respuestas dirigidas a nosotros)."""
    from phases.phase_b.orchestrator import (
        _load_agent_comment_ids,
        _save_agent_comment_ids,
    )

    _pid = str(uuid.uuid4())
    _save_agent_comment_ids({_pid: ["c-a", "c-b"]})
    try:
        loaded = _load_agent_comment_ids()
        assert loaded.get(_pid) == ["c-a", "c-b"], f"roundtrip fallo: {loaded}"
    finally:
        _save_agent_comment_ids({})  # limpiar estado global
