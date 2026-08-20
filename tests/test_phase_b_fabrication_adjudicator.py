# -*- coding: utf-8 -*-
"""Tests del adjudicador LLM de fabricación de nombres propios.

Cubre:
  - _adjudicate_named_entity_fabrication: tier classify, fallback a flash,
    fail-open ante error/salida no parseable.
  - wiring en _score_reply_draft: flag AGENT_ENABLE_FABRICATION_BLOCK=1
    bloquea el draft si FABRICATION; =0 (default) es shadow (veredicto al
    shadow log, sin bloquear).

LLM mockeado (AsyncMock), determinista. Aislado con tmp_path (el shadow log se
redirige a tmp vía pb._shadow_quality_log_path).
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
