"""Tests del gate de integridad #3 — SHADOW ONLY (Fase 2, no bloquea).

Contrato fijado por el audit de gates (16/8/2026): las replies de Phase B
pasan limpias hoy por dos huecos que estos tests fijan:

  A) FABRICACION de 3ra persona: "...formal verification for hardware,
     specifically in CPU design with projects like Project Mercury at AMD..."
     → entidad propia (Project Mercury) sin grounding en la fuente.
  B) ANALOGIA-DRIFT / atribucion causal de segunda mano: "...echoes the
     challenges faced in early genetic programming, where fitness functions
     could inadvertently reward undesirable behaviors..."
  C) MECANISMO-OK (debe quedar limpia): gate sobre delta agente/entorno.
  D) CONCEPTO-GENERAL-OK (debe quedar limpia): analogia estructural
     "same failure mode as a circuit breaker that never re-closes".

Fase 2 = SOLO shadow logging (data/shadow_quality_checks.jsonl via
_score_reply_draft): los detectores flaggean, NO bloquean. La calibracion
decide la activacion como penalty despues.

Aislado con tmp_path (el shadow log se redirige a tmp via
pb._shadow_quality_log_path). No escribe en data/ real.
"""

import json
import pytest
from unittest.mock import MagicMock

import services.reply_cap as rcap
from phases.phase_b import PhaseB
from phases.deps import PhaseBDeps
from phases.phase_b.scoring import (
    _extract_named_entities,
    _reply_has_ungrounded_named_entity,
    _reply_has_secondhand_causal_attribution,
)

# UUID realista para que el shadow log NO filtre la entrada como sintetica.
POST = "6f3b8a2c-9d4e-4a7f-9c8b-1a2b3c4d5e6f"

A_FABRICACION = (
    "Formal verification for hardware, specifically in CPU design with "
    "projects like Project Mercury at AMD. The difficulty there was "
    "maintaining the golden reference against evolving microarchitectural "
    "optimizations."
)
B_ANALOGIA_DRIFT = (
    "The emergent specification argument echoes the challenges faced in "
    "early genetic programming, where fitness functions could inadvertently "
    "reward undesirable behaviors if not carefully constrained."
)
C_MECANISMO_OK = (
    "Version-aware constraints break under prompt-template swaps; gate on "
    "the delta between agent behavior and environment state, reject when "
    "the deviation exceeds the observed baseline."
)
D_CONCEPTO_OK = "This is the same failure mode as a circuit breaker that never re-closes."

SOURCE = (
    "Emergent specifications drift away from the intended contract as the "
    "codebase evolves and the verification harness rewrites expectations."
)


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(rcap, "_REPLIES_PER_POST_PATH", tmp_path / "replies_per_post.json")
    monkeypatch.setattr(rcap, "_FOLLOWUPS_PER_POST_PATH", tmp_path / "followups_per_post.json")
    monkeypatch.setattr(rcap, "_TOTAL_REPLIES_PER_POST_PATH", tmp_path / "total_replies_per_post.json")
    yield


def _make_pb():
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_comments_per_post": 30, "max_comments_per_day": 400},
        agent_name="COMET-RIOBAMBA",
    )
    return PhaseB(deps)


# ── Detectores: contratos sobre los 4 ejemplos ──────────────────

def test_extract_named_entities_finds_multiword_proper_nouns():
    ents = _extract_named_entities(A_FABRICACION)
    assert "project mercury" in ents, f"debe extraer 'Project Mercury', obtuvo {ents}"


def test_ungrounded_named_entity_flags_A_and_not_others():
    assert _reply_has_ungrounded_named_entity(A_FABRICACION, SOURCE) is True
    assert _reply_has_ungrounded_named_entity(B_ANALOGIA_DRIFT, SOURCE) is False
    assert _reply_has_ungrounded_named_entity(C_MECANISMO_OK, SOURCE) is False
    assert _reply_has_ungrounded_named_entity(D_CONCEPTO_OK, SOURCE) is False


def test_grounded_named_entity_passes():
    grounded = "Project Mercury kept its golden reference in sync with the spec."
    source_with_entity = SOURCE + " AMD's Project Mercury team measured this drift."
    assert _reply_has_ungrounded_named_entity(grounded, source_with_entity) is False


def test_secondhand_causal_attribution_flags_B_and_not_others():
    assert _reply_has_secondhand_causal_attribution(B_ANALOGIA_DRIFT) is True
    assert _reply_has_secondhand_causal_attribution(A_FABRICACION) is False
    assert _reply_has_secondhand_causal_attribution(C_MECANISMO_OK) is False
    assert _reply_has_secondhand_causal_attribution(D_CONCEPTO_OK) is False


# ── Integracion: shadow log recibe los hits, SIN bloquear ───────

def test_shadow_log_records_new_hits_without_blocking(tmp_path):
    pb = _make_pb()
    pb._shadow_quality_log_path = tmp_path / "shadow_quality_checks.jsonl"

    score_a, reasons_a = pb._score_reply_draft(A_FABRICACION, SOURCE, log_context={"post_id": POST})
    score_b, reasons_b = pb._score_reply_draft(B_ANALOGIA_DRIFT, SOURCE, log_context={"post_id": POST})
    score_c, _ = pb._score_reply_draft(C_MECANISMO_OK, SOURCE, log_context={"post_id": POST})
    score_d, _ = pb._score_reply_draft(D_CONCEPTO_OK, SOURCE, log_context={"post_id": POST})

    # Shadow only: el score NO se toca (permissive mode intacto).
    assert score_a == score_b == score_c == score_d == 50
    assert reasons_a == [] and reasons_b == []

    records = [json.loads(line) for line in (tmp_path / "shadow_quality_checks.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    hits_by_preview = {}
    for r in records:
        key = next(
            (k for k in ("A", "B", "C", "D")
             if r["reply_preview"].startswith(A_FABRICACION[:20] if k == "A" else
                                           B_ANALOGIA_DRIFT[:20] if k == "B" else
                                           C_MECANISMO_OK[:20] if k == "C" else
                                           D_CONCEPTO_OK[:20])),
            None,
        )
        if key:
            hits_by_preview[key] = set(r["checks"])

    assert "ungrounded_named_entity" in hits_by_preview.get("A", set()), f"A debe loguear ungrounded_named_entity: {hits_by_preview}"
    assert "secondhand_causal_attribution" in hits_by_preview.get("B", set()), f"B debe loguear secondhand_causal_attribution: {hits_by_preview}"
    for key in ("C", "D"):
        hits = hits_by_preview.get(key, set())
        assert "ungrounded_named_entity" not in hits, (
            f"{key} NO debe loguear ungrounded_named_entity: {hits}"
        )
        assert "secondhand_causal_attribution" not in hits, (
            f"{key} NO debe loguear secondhand_causal_attribution: {hits}"
        )
