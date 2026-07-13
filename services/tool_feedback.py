"""Tool-level feedback signals for classifying operation outcomes and
tripping circuit breakers.  Pure computation — no I/O, no COMET imports."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


class ToolOutcome(enum.Enum):
    SUCCESS = "success"
    LOGICAL_FAILURE = "logical_failure"
    TRANSPORT_FAILURE = "transport_failure"
    UNKNOWN = "unknown"


@dataclass
class ToolResultReceipt:
    tool_name: str
    operation: str
    request_id: Optional[str] = None
    http_status: Optional[int] = None
    transport_ok: bool = False
    response_schema_ok: bool = False
    response_notes: Optional[str] = None
    expected_state_desc: Optional[str] = None
    observed_state_desc: Optional[str] = None
    state_match: Optional[bool] = None
    idempotency_key: Optional[str] = None
    commit_marker: Optional[str] = None
    commit_confirmed: Optional[bool] = None
    latency_ms: Optional[float] = None
    baseline_latency_ms: Optional[float] = None
    verifier_model: Optional[str] = None
    verifier_score: Optional[float] = None
    confidence_score: Optional[float] = None
    outcome: ToolOutcome = ToolOutcome.UNKNOWN
    extra: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


def compute_confidence(
    receipt: ToolResultReceipt,
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """Compute a normalised confidence score (0.0–1.0) from available signals.

    Signals used (with default weights):
        schema   (0.25) — 1.0 if *response_schema_ok*, 0.0 if False, else ignored.
        state    (0.45) — 1.0 if *state_match* is True, 0.0 if False, 0.5 if None.
        latency  (0.10) — ratio-based: ≤1.25× baseline → 1.0; ≤1.75× → 0.5; else 0.0.
        verifier (0.20) — *verifier_score* clamped to [0.0, 1.0].

    Weights are renormalised to sum to 1.0 over the signals that are present.
    The result is stored on *receipt.confidence_score* and *receipt.outcome*
    is updated via `classify_outcome`.
    """
    _default_weights = {"schema": 0.25, "state": 0.45, "latency": 0.10, "verifier": 0.20}
    if weights is None:
        weights = _default_weights

    signals: Dict[str, float] = {}

    if receipt.response_schema_ok is not None:
        signals["schema"] = 1.0 if receipt.response_schema_ok else 0.0

    if receipt.state_match is not None:
        signals["state"] = 1.0 if receipt.state_match else 0.0

    if receipt.latency_ms is not None and receipt.baseline_latency_ms is not None:
        ratio = receipt.latency_ms / receipt.baseline_latency_ms
        if ratio <= 1.25:
            signals["latency"] = 1.0
        elif ratio <= 1.75:
            signals["latency"] = 0.5
        else:
            signals["latency"] = 0.0

    if receipt.verifier_score is not None:
        signals["verifier"] = max(0.0, min(1.0, receipt.verifier_score))

    present = [k for k in signals if k in weights]
    if not present:
        receipt.confidence_score = 0.0
        receipt.outcome = classify_outcome(receipt)
        return 0.0

    used_weights = {k: weights[k] for k in present}
    total = sum(used_weights.values())
    if total == 0:
        receipt.confidence_score = 0.0
        receipt.outcome = classify_outcome(receipt)
        return 0.0

    norm = sum(signals[k] * (used_weights[k] / total) for k in present)
    score = max(0.0, min(1.0, norm))
    receipt.confidence_score = score
    receipt.outcome = classify_outcome(receipt)
    return score


def classify_outcome(receipt: ToolResultReceipt) -> ToolOutcome:
    """Classify the outcome based on transport and logical signals."""
    if receipt.http_status is not None:
        if not receipt.transport_ok or receipt.http_status >= 400:
            return ToolOutcome.TRANSPORT_FAILURE

    if receipt.transport_ok:
        if receipt.state_match is not None and not receipt.state_match:
            return ToolOutcome.LOGICAL_FAILURE
        if receipt.commit_confirmed is not None and not receipt.commit_confirmed:
            return ToolOutcome.LOGICAL_FAILURE
        if (receipt.state_match is None or receipt.state_match) and (
            receipt.commit_confirmed is None or receipt.commit_confirmed
        ):
            return ToolOutcome.SUCCESS

    return ToolOutcome.UNKNOWN


def should_trip_circuit(
    receipt: ToolResultReceipt,
    min_confidence: float = 0.6,
) -> bool:
    """Return True if the receipt warrants tripping a circuit breaker."""
    if receipt.outcome in (ToolOutcome.TRANSPORT_FAILURE, ToolOutcome.LOGICAL_FAILURE):
        return True
    if receipt.confidence_score is not None and receipt.confidence_score < min_confidence:
        return True
    return False
