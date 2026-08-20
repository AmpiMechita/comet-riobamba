# -*- coding: utf-8 -*-
"""Tests del adjudicador LLM de fabricación de nombres propios.

Cubre:
  - _adjudicate_named_entity_fabrication (ETAPA 2): ruteo dedicado a Groq
    groq/compound-mini (payload: model, max_tokens=256, temperature=0),
    fallback a cascada classify → flash con mt=256, parse robusto (última
    aparición, tolera reasoning previo), fail-open ante 429/error/unparseable,
    y registro de veredictos en el shadow de medición (adjudicator_verdicts).
  - wiring en _score_reply_draft: flag AGENT_ENABLE_FABRICATION_BLOCK=1
    bloquea el draft si FABRICATION; =0 (default) es shadow (veredicto al
    shadow log, sin bloquear).

LLM mockeado (AsyncMock), determinista. Aislado con tmp_path (el shadow log se
redirige a tmp vía pb._shadow_quality_log_path). Groq queda desactivado por
defecto (conftest borra GROQ_API_KEY): los tests que ejercitan el ruteo Groq
lo encienden explícitamente parcheando requests.post.
"""

import asyncio
import json
import os

import pytest
from unittest.mock import AsyncMock, MagicMock

import services.reply_cap as rcap
from phases.phase_b import PhaseB
from phases.deps import PhaseBDeps
from phases.phase_b.orchestrator import PhaseB as _PhaseBCls

POST = "6f3b8a2c-9d4e-4a7f-9c8b-1a2b3c4d5e6f"

# Reply que dispara ungrounded_named_entity (Project Mercury no está en source).
REPLY_FAB = (
    "Formal verification for hardware, specifically in CPU design with "
    "projects like Project Mercury at AMD. The difficulty there was "
    "maintaining the golden reference against evolving microarchitectural "
    "optimizations."
)
SOURCE = (
    "Formal verification of concurrent systems requires a stable golden "
    "reference to compare against when the specification evolves."
)


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(rcap, "_REPLIES_PER_POST_PATH", tmp_path / "replies_per_post.json")
    monkeypatch.setattr(rcap, "_FOLLOWUPS_PER_POST_PATH", tmp_path / "followups_per_post.json")
    monkeypatch.setattr(rcap, "_TOTAL_REPLIES_PER_POST_PATH", tmp_path / "total_replies_per_post.json")
    monkeypatch.delenv("AGENT_ENABLE_FABRICATION_BLOCK", raising=False)
    yield


def _make_pb():
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_comments_per_post": 30, "max_comments_per_day": 400},
        agent_name="COMET-RIOBAMBA",
    )
    return PhaseB(deps)


# ── Adjudicador: contratos ───────────────────────────────────────

@pytest.mark.asyncio
async def test_adjudicator_parse_real():
    assert _PhaseBCls._parse_adjudication("REAL") == "REAL"
    assert _PhaseBCls._parse_adjudication('FABRICATION') == "FABRICATION"
    assert _PhaseBCls._parse_adjudication("FABRICATION because no source") == "FABRICATION"
    assert _PhaseBCls._parse_adjudication(" REAL ") == "REAL"
    assert _PhaseBCls._parse_adjudication("hmm maybe") is None
    assert _PhaseBCls._parse_adjudication("") is None


@pytest.mark.asyncio
async def test_adjudicator_classify_fabrication(tmp_path):
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(side_effect=["FABRICATION"])
    assert await pb._adjudicate_named_entity_fabrication(REPLY_FAB, SOURCE, {"project mercury"}) is True


@pytest.mark.asyncio
async def test_adjudicator_classify_real():
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(side_effect=["REAL"])
    assert await pb._adjudicate_named_entity_fabrication(REPLY_FAB, SOURCE, {"project mercury"}) is False


@pytest.mark.asyncio
async def test_adjudicator_fallback_classify_to_flash():
    """Si classify no parsea, fallback a flash."""
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(side_effect=["some nonsense", "FABRICATION"])
    assert await pb._adjudicate_named_entity_fabrication(REPLY_FAB, SOURCE, {"project mercury"}) is True
    assert pb.llm.generate.await_count == 2
    tiers = [c.kwargs.get("tier") for c in pb.llm.generate.await_args_list]
    assert tiers == ["classify", "flash"]


@pytest.mark.asyncio
async def test_adjudicator_fail_open_on_error():
    """Error del LLM en ambos tiers → PASA (no bloquear)."""
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
    assert await pb._adjudicate_named_entity_fabrication(REPLY_FAB, SOURCE, {"project mercury"}) is False


@pytest.mark.asyncio
async def test_adjudicator_fail_open_on_unparseable():
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(return_value="please clarify")
    assert await pb._adjudicate_named_entity_fabrication(REPLY_FAB, SOURCE, {"project mercury"}) is False


# ── Wiring: flag ON bloquea FABRICATION ──────────────────────────

@pytest.mark.asyncio
async def test_wiring_flag_on_blocks_fabrication(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_ENABLE_FABRICATION_BLOCK", "1")
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(side_effect=["FABRICATION"])
    pb._shadow_quality_log_path = tmp_path / "shadow.jsonl"
    score, reasons = await pb._score_reply_draft(REPLY_FAB, SOURCE, log_context={"post_id": POST})
    assert score < 10, f"FABRICATION con flag ON debe fallar el draft, score={score} reasons={reasons}"
    assert "fabrication_named_entity" in reasons


@pytest.mark.asyncio
async def test_wiring_flag_on_passes_real(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_ENABLE_FABRICATION_BLOCK", "1")
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(side_effect=["REAL"])
    pb._shadow_quality_log_path = tmp_path / "shadow.jsonl"
    score, reasons = await pb._score_reply_draft(REPLY_FAB, SOURCE, log_context={"post_id": POST})
    assert score == 50, f"REAL no debe bloquear, score={score} reasons={reasons}"
    assert "fabrication_named_entity" not in reasons


# ── Wiring: flag OFF (default) es shadow, no bloquea ─────────────

@pytest.mark.asyncio
async def test_wiring_flag_off_shadow_does_not_block(tmp_path):
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(side_effect=["FABRICATION"])
    pb._shadow_quality_log_path = tmp_path / "shadow.jsonl"
    score, reasons = await pb._score_reply_draft(REPLY_FAB, SOURCE, log_context={"post_id": POST})
    # shadow: el veredicto FABRICATION se registra pero NO bloquea.
    assert score == 50, f"flag OFF no debe bloquear, score={score} reasons={reasons}"
    assert "fabrication_named_entity" not in reasons
    # el shadow log registra el veredicto adjudicado.
    lines = (tmp_path / "shadow.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines, "shadow log debe existir"
    record = json.loads(lines[0])
    assert "fabrication_adjudicated" in record["checks"]


@pytest.mark.asyncio
async def test_wiring_flag_off_real_not_logged_as_fabrication(tmp_path):
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(side_effect=["REAL"])
    pb._shadow_quality_log_path = tmp_path / "shadow.jsonl"
    score, _ = await pb._score_reply_draft(REPLY_FAB, SOURCE, log_context={"post_id": POST})
    assert score == 50
    lines = (tmp_path / "shadow.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    assert "fabrication_adjudicated" not in record["checks"]
    assert "ungrounded_named_entity" in record["checks"]


# ── Wiring: fail-open del adjudicador nunca bloquea ──────────────

@pytest.mark.asyncio
async def test_wiring_fail_open_on_llm_error_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_ENABLE_FABRICATION_BLOCK", "1")
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
    pb._shadow_quality_log_path = tmp_path / "shadow.jsonl"
    score, reasons = await pb._score_reply_draft(REPLY_FAB, SOURCE, log_context={"post_id": POST})
    assert score == 50, f"error del adjudicador debe pasar (fail-open), score={score} reasons={reasons}"
    assert "fabrication_named_entity" not in reasons


# ── ETAPA 2: ruteo dedicado a Groq groq/compound-mini ────────────

@pytest.mark.asyncio
async def test_adjudicator_parse_robust_last_occurrence():
    """ETAPA 2: reasoning/scratchpad antes del veredicto y última aparición."""
    assert _PhaseBCls._parse_adjudication(
        "Let me think: the source does not mention it, could be REAL, but the "
        "reply claims a measured result. Verdict: FABRICATION"
    ) == "FABRICATION"
    assert _PhaseBCls._parse_adjudication(
        "The entity is well known, so REAL. Wait, actually FABRICATION"
    ) == "FABRICATION"
    assert _PhaseBCls._parse_adjudication(
        "FABRICATION? No — this is an established system, REAL."
    ) == "REAL"
    assert _PhaseBCls._parse_adjudication(
        'I lean toward "FABRICATION". Final answer: REAL'
    ) == "REAL"
    assert _PhaseBCls._parse_adjudication(
        "considering... the claim is fabricated. fabrication"
    ) == "FABRICATION"
    assert _PhaseBCls._parse_adjudication("  REAL  ") == "REAL"
    assert _PhaseBCls._parse_adjudication(None) is None


@pytest.mark.asyncio
async def test_adjudicator_groq_routes_first(tmp_path, monkeypatch):
    """Groq decide; la cascada NO se consulta."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(return_value="REAL")
    pb._adjudicate_via_groq = MagicMock(return_value="FABRICATION")
    assert await pb._adjudicate_named_entity_fabrication(REPLY_FAB, SOURCE, {"project mercury"}) is True
    pb.llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_adjudicator_groq_payload_model_and_tokens(tmp_path, monkeypatch):
    """El payload HTTP a Groq usa groq/compound-mini, max_tokens=256, temp=0."""
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "FABRICATION"}}]}

    def _fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setattr("phases.phase_b.orchestrator.requests.post", _fake_post)
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(return_value="REAL")
    assert await pb._adjudicate_named_entity_fabrication(REPLY_FAB, SOURCE, {"project mercury"}) is True
    assert captured["payload"]["model"] == "groq/compound-mini"
    assert captured["payload"]["max_tokens"] == 256
    assert captured["payload"]["temperature"] == 0.0
    assert captured["payload"]["messages"][0]["role"] == "system"
    pb.llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_adjudicator_groq_429_fail_open(tmp_path, monkeypatch):
    """429 de compound-mini (TPM) → fail-open: PASA si la cascada también cae."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")

    def _fake_post(*a, **k):
        raise RuntimeError("HTTP 429 Too Many Requests (compound-mini TPM)")

    monkeypatch.setattr("phases.phase_b.orchestrator.requests.post", _fake_post)
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
    assert await pb._adjudicate_named_entity_fabrication(REPLY_FAB, SOURCE, {"project mercury"}) is False
    assert pb.llm.generate.await_count == 2


@pytest.mark.asyncio
async def test_adjudicator_groq_unparseable_falls_back_to_cascade(tmp_path, monkeypatch):
    """Groq devuelve basura → fallback a cascada classify → flash."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(side_effect=["please clarify", "FABRICATION"])
    pb._adjudicate_via_groq = MagicMock(return_value="hmm maybe")
    assert await pb._adjudicate_named_entity_fabrication(REPLY_FAB, SOURCE, {"project mercury"}) is True
    tiers = [c.kwargs.get("tier") for c in pb.llm.generate.await_args_list]
    assert tiers == ["classify", "flash"]


@pytest.mark.asyncio
async def test_adjudicator_cascade_fallback_uses_256_tokens():
    """Fallback a cascada usa max_tokens=256 (no 8)."""
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(return_value="REAL")
    assert await pb._adjudicate_named_entity_fabrication(REPLY_FAB, SOURCE, {"project mercury"}) is False
    assert pb.llm.generate.await_args.kwargs["max_tokens"] == 256
    assert pb.llm.generate.await_args.kwargs["temperature"] == 0.0


# ── ETAPA 2: shadow de medición de veredictos ────────────────────

@pytest.mark.asyncio
async def test_adjudicator_logs_verdict_shadow_groq(tmp_path, monkeypatch):
    """Veredicto Groq registrado en el shadow (route=groq)."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(return_value="REAL")
    pb._adjudicator_verdict_log_path = tmp_path / "verdicts.jsonl"
    pb._adjudicate_via_groq = MagicMock(return_value="FABRICATION")
    assert await pb._adjudicate_named_entity_fabrication(REPLY_FAB, SOURCE, {"project mercury"}) is True
    lines = (tmp_path / "verdicts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["route"] == "groq"
    assert record["model"] == "groq/compound-mini"
    assert record["verdict"] == "FABRICATION"
    assert record["reply_preview"] == REPLY_FAB[:200]


@pytest.mark.asyncio
async def test_adjudicator_logs_fail_open_shadow(tmp_path):
    """Sin Groq y cascada rota → fail-open registrado en shadow."""
    pb = _make_pb()
    pb.llm = MagicMock()
    pb.llm.generate = AsyncMock(return_value="gibberish no verdict here")
    pb._adjudicator_verdict_log_path = tmp_path / "verdicts.jsonl"
    assert await pb._adjudicate_named_entity_fabrication(REPLY_FAB, SOURCE, {"project mercury"}) is False
    lines = (tmp_path / "verdicts.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    assert record["route"] == "fail-open"
    assert record["verdict"] == "fail-open"
