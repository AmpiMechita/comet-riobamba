# -*- coding: utf-8 -*-
"""Regresión: drafts rechazados en el log 2026-09-17/18 deben pasar tras
la recalibración del quality gate (Cambios 1+2b, 2026-09-18).

Fuente: logs/nightly_run_20260917_202743.log.

Nota sobre las previews: el log trunca la preview a 80 chars, pero el
draft real puede ser más largo (campo len=NNN en la misma línea). El
caso "Novelty-weighted budgeting" tenía len=487 pero solo se recuperan
79 chars desde la preview → NO se puede validar el gate con esa evidencia.
Se marca como pytest.skip en vez de asumir que pasa o falla.

Los demás drafts son validables con la preview porque la sustancia
está en el prefijo (vocabulario en mecanismos/evidencia).
"""

import pytest

from phases.phase_b import PhaseB
from phases.phase_b.scoring import (
    text_has_fabricated_measurement,
    text_has_unverifiable_historical_claim,
)


DRAFTS_EXPECTED_TO_PASS = [
    "Re-scored, not requeued. The carry-over weight is a decay function over the item",
    "Decay is the right instinct, but halving per cycle makes the half-life the whole",
    "The distinction you want is exactly what the Linux CFS runqueue tracks: a task's",
    "A 0.7 ratio flags the symptom, not the cause: it assumes the cycle budget is fixed and the queue is",
    "The preempted-vs-never-seen distinction is exactly what YARN's ResourceManager got wrong before the",
    "Yes, and the failure mode is specific: the scar outlives the constraint it encoded.",
]


DRAFTS_PREVIEW_TRUNCATED_UNVERIFIABLE = [
    # len=487 en el log, preview=79 chars. Faltan ~408 chars del draft real.
    "Novelty-weighted budgeting fails at the measurement layer, not the policy layer.",
]


DRAFTS_EXPECTED_TO_STILL_FAIL = [
    "Aquinas' habitus is the wrong comparator — it was never a storage format.",
]


@pytest.mark.parametrize("draft", DRAFTS_EXPECTED_TO_PASS)
def test_recalibrated_drafts_pass(draft: str) -> None:
    """Tras Cambios 1+2b, estos drafts superan el gate de sustancia."""
    padded = draft if len(draft) >= 40 else draft + " " * (40 - len(draft))
    assert PhaseB._passes_quality_gate(padded, require_evidence=True) is True, (
        f"Draft deberia pasar tras recalibracion: {draft[:80]}"
    )


@pytest.mark.parametrize("draft", DRAFTS_PREVIEW_TRUNCATED_UNVERIFIABLE)
def test_preview_truncated_unverifiable(draft: str) -> None:
    """No se puede validar el gate con evidencia parcial. Skip explicito."""
    pytest.skip(
        f"Preview truncada a 80 chars; draft completo no recuperable "
        f"del log (len=487). No se asume resultado."
    )


@pytest.mark.parametrize("draft", DRAFTS_EXPECTED_TO_STILL_FAIL)
def test_philosophical_reference_still_blocked(draft: str) -> None:
    """Referencia filosofica no tecnica sigue rechazada — el gate tiene razon."""
    assert PhaseB._passes_quality_gate(draft, require_evidence=True) is False, (
        f"Draft deberia seguir bloqueado: {draft}"
    )


def test_fabrication_still_blocked() -> None:
    """Cambios 1+2b no relajan anti-fabricacion (gate ortogonal)."""
    assert text_has_fabricated_measurement(
        "We measured 40% latency reduction in our production deployment"
    ) is True


def test_historical_year_still_blocked() -> None:
    """Cambios 1+2b no relajan gate historico (gate ortogonal)."""
    result = text_has_unverifiable_historical_claim(
        "In 2007 Google published a paper about it",
        context="Some post about distributed systems",
    )
    assert result == "2007"


def test_generic_fluff_still_rejected() -> None:
    """Un draft sin sustancia real sigue siendo rechazado."""
    assert PhaseB._passes_quality_gate(
        "This reply has no substance at all beyond restating the obvious point the post made",
        require_evidence=True,
    ) is False

