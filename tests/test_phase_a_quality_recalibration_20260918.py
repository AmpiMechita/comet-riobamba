# -*- coding: utf-8 -*-
"""Regresión: recalibración del quality gate de Phase A (2026-09-18).

Contexto: 271 rechazos por below_min_quality_score en rejected_posts.jsonl.
El clasificador dual_scoring exigía vocabulario específico (framework, pattern,
architecture) y no reconocía la prescripción natural del agente ("The fix is X",
"The mechanism is Y"). El gate rechazaba ~76% de posts técnicos válidos.

Cambios cubiertos:
  - services/dual_scoring.py: paso 2 ampliado (empirical), nuevo paso 3.5
    (prescription + named mechanism), paso 4 ampliado (critique, alternative).
  - phases/phase_a_content.py: _is_substantive_post con segunda ruta técnica
    (posts densos sin pregunta final).

Verificación in-vivo (pre-test): 204/271 = 75.3% reclasificados a un tipo
publicable (framework/empirical/critique).
"""

import pytest

from services.dual_scoring import classify_content, ResearchValueType
from phases.phase_a_content import _is_substantive_post


# ── Fixtures: strings largos reales (no truncados) ─────────────
#
# NOTA: los strings originales del rejected_posts.jsonl tienen 485-800 chars.
# Para tests reproducibles usamos strings construidos que cumplen la misma
# estructura y longitud. Cada uno > 300 chars como exige el bloque 3.5.

_KEY_EPOCH_GATE = (
    "The fix is a key-epoch gate. Each agent loop must carry an expected key "
    "version, and any mismatch with the hardware keystore halts the run before "
    "the next tool call, preventing unauthorized signing operations. This "
    "avoids the failure mode where a compromised key silently signs requests "
    "without operator awareness. The gate reads the expected version from a "
    "signed manifest that only the orchestrator can update, so an agent that "
    "gets compromised cannot simply claim a new key epoch."
)

_DRIFT_EVENT_LOG = (
    "The mechanism is a drift-stamped event log: every tool call, retry, and "
    "memory write carries a hash of the agent current configuration and the "
    "context window state. When the current hash diverges from the stamped "
    "baseline, the next iteration opens a circuit breaker and refuses to call "
    "tools until a human operator reconciles the drift. This catches schema "
    "drift and silent config changes that would otherwise propagate into "
    "downstream decisions without any visible error."
)

_PRODUCTION_INCIDENT = (
    "In our production environment, we encountered an issue where 4 of 12 "
    "daily publishing slots were left empty, resulting from a pacing rule "
    "that enforced a 2-hour minimum between posts. The validator first "
    "clamped the configured limit to an upper bound, then the runtime "
    "silently ran at a default value that was lower than intended. No error "
    "was logged, and the discrepancy only surfaced in a weekly report."
)

_BOILERPLATE_FRAMEWORK = (
    "The proposed framework to mitigate this issue involves implementing a "
    "context window management system, which monitors the agent context "
    "window size and triggers a refresh mechanism when it reaches a certain "
    "threshold. This approach ensures consistency across the runtime "
    "environment and provides a robust solution to the underlying problem."
)


# ── Bloque 1: prescription pattern → FRAMEWORK_PROPOSAL ──

def test_key_epoch_gate_classifies_as_framework() -> None:
    """Prescripción con mecanismo nombrado (gate) → framework_proposal."""
    result = classify_content(_KEY_EPOCH_GATE)
    assert result == ResearchValueType.FRAMEWORK_PROPOSAL, (
        f"esperado framework_proposal, obtenido {result.value}"
    )


def test_drift_event_log_classifies_as_framework() -> None:
    """Prescripción con mecanismo nombrado (event log) → framework_proposal."""
    result = classify_content(_DRIFT_EVENT_LOG)
    assert result == ResearchValueType.FRAMEWORK_PROPOSAL, (
        f"esperado framework_proposal, obtenido {result.value}"
    )


def test_production_incident_classifies_as_empirical() -> None:
    """Incidente real con "in our production environment" → empirical_finding."""
    result = classify_content(_PRODUCTION_INCIDENT)
    assert result == ResearchValueType.EMPIRICAL_FINDING, (
        f"esperado empirical_finding, obtenido {result.value}"
    )


# ── Bloque 2: boilerplate sigue rechazado ──

def test_boilerplate_framework_not_rescued() -> None:
    """Boilerplate ("involves implementing") NO debe clasificarse como framework."""
    result = classify_content(_BOILERPLATE_FRAMEWORK)
    assert result != ResearchValueType.FRAMEWORK_PROPOSAL, (
        "boilerplate no debe pasar como framework_proposal"
    )


# ── Bloque 3: _is_substantive_post ──

def test_substantive_post_rejects_short() -> None:
    """Texto corto → False."""
    assert _is_substantive_post("Short text") is False


def test_substantive_post_rejects_no_density() -> None:
    """500 chars sin densidad técnica → False."""
    assert _is_substantive_post("x" * 500) is False


def test_substantive_post_accepts_technical_density() -> None:
    """Post técnico denso sin pregunta final → True."""
    # _KEY_EPOCH_GATE + padding para superar SUBSTANTIVE_MIN_CHARS=400
    text = _KEY_EPOCH_GATE
    assert _is_substantive_post(text) is True, (
        f"esperado True, got False | len={len(text)}"
    )


def test_substantive_post_accepts_question_ending() -> None:
    """Post con pregunta final genuina y > 400 chars → True (ruta original)."""
    text = (
        "We deployed a circuit breaker that gates on failure rate over a rolling "
        "window of five calls, not raw count. This reduced spurious opens by a "
        "factor we did not anticipate, and we now treat schema drift as a "
        "first-class signal rather than a downstream symptom. The gate reads "
        "from a rolling counter maintained by the orchestrator, which means "
        "schema drift is caught before it propagates into a downstream write "
        "that no single read would reveal as corrupted. But how do you decide "
        "the window length when the failure distribution is itself non-"
        "stationary over the deployment cycle?"
    )
    assert len(text) >= 400, f"test string demasiado corto: {len(text)}"
    assert _is_substantive_post(text) is True
def test_fabrication_pattern_intact() -> None:
    """_FABRICATION_PATTERN (Phase B) no debe haberse relajado."""
    from phases.phase_b.scoring import _FABRICATION_PATTERN
    assert _FABRICATION_PATTERN.search(
        "We measured 40% latency reduction in our production deployment"
    ) is not None


def test_has_metric_signals_intact() -> None:
    """_has_metric_signals sigue detectando porcentajes y unidades."""
    from services.dual_scoring import _has_metric_signals
    assert _has_metric_signals("we cut latency by 40%") is True
    assert _has_metric_signals("the p99 was 250ms") is True
    assert _has_metric_signals("a plain sentence without metrics") is False

