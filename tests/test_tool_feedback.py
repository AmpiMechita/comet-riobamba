"""Unit tests for services.tool_feedback — pure computation, no I/O."""

import pytest
from services.tool_feedback import (
    ToolOutcome,
    ToolResultReceipt,
    classify_outcome,
    compute_confidence,
    should_trip_circuit,
)


class TestComputeConfidence:
    def test_all_signals_present(self):
        r = ToolResultReceipt(
            tool_name="moltbook",
            operation="create_post",
            response_schema_ok=True,
            state_match=True,
            latency_ms=100.0,
            baseline_latency_ms=80.0,
            verifier_score=0.9,
        )
        score = compute_confidence(r)
        # schema=1.0*0.25 + state=1.0*0.45 + latency=0.5 + verifier=0.9*0.20
        # ratio=1.25 → latency=1.0
        # sum: 1.0*(0.25/1.0) + 1.0*(0.45/1.0) + 1.0*(0.10/1.0) + 0.9*(0.20/1.0)
        # = 0.25 + 0.45 + 0.10 + 0.18 = 0.98
        assert score == pytest.approx(0.98, abs=1e-9)
        assert r.confidence_score == pytest.approx(0.98, abs=1e-9)

    def test_latency_ratio_brackets(self):
        r = ToolResultReceipt(
            tool_name="t",
            operation="o",
            response_schema_ok=True,
            state_match=True,
            latency_ms=160.0,
            baseline_latency_ms=80.0,
        )
        score = compute_confidence(r)
        # ratio=2.0 → latency=0.0
        # schema=0.25/0.80 + state=0.45/0.80 = 0.3125 + 0.5625 = 0.875
        assert score == pytest.approx(0.875, abs=1e-9)

    def test_latency_exactly_at_1_75(self):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            response_schema_ok=True, state_match=True,
            latency_ms=140.0, baseline_latency_ms=80.0,
        )
        score = compute_confidence(r)
        # ratio=1.75 → latency=0.5
        # (0.25 + 0.45 + 0.5*0.10) / 0.80 = 0.75/0.80
        expected = (1.0 * 0.25 + 1.0 * 0.45 + 0.5 * 0.10) / 0.80
        assert score == pytest.approx(expected, abs=1e-9)

    def test_schema_and_state_only(self):
        r = ToolResultReceipt(
            tool_name="t",
            operation="o",
            response_schema_ok=False,
            state_match=False,
        )
        score = compute_confidence(r)
        # schema=0.0, state=0.0 → 0.0
        assert score == 0.0
        assert r.confidence_score == 0.0

    def test_schema_ok_state_none(self):
        r = ToolResultReceipt(
            tool_name="t",
            operation="o",
            response_schema_ok=True,
            state_match=None,
        )
        score = compute_confidence(r)
        # state_match=None means state signal absent
        # schema=1.0, single present signal → 1.0
        assert score == 1.0

    def test_all_signals_none(self):
        r = ToolResultReceipt(tool_name="t", operation="o")
        score = compute_confidence(r)
        assert score == 0.0

    def test_custom_weights(self):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            response_schema_ok=True, state_match=True,
        )
        score = compute_confidence(r, weights={"schema": 0.8, "state": 0.2})
        expected = 1.0 * 0.8 + 1.0 * 0.2
        assert score == pytest.approx(expected, abs=1e-9)


class TestClassifyOutcome:
    def test_transport_failure_no_2xx(self):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            transport_ok=False, http_status=500,
        )
        assert classify_outcome(r) == ToolOutcome.TRANSPORT_FAILURE

    def test_transport_failure_non_2xx(self):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            transport_ok=True, http_status=403,
        )
        assert classify_outcome(r) == ToolOutcome.TRANSPORT_FAILURE

    def test_logical_failure_state_mismatch(self):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            transport_ok=True, state_match=False,
        )
        assert classify_outcome(r) == ToolOutcome.LOGICAL_FAILURE

    def test_logical_failure_commit_not_confirmed(self):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            transport_ok=True, commit_confirmed=False,
        )
        assert classify_outcome(r) == ToolOutcome.LOGICAL_FAILURE

    def test_success_transport_ok_state_match(self):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            transport_ok=True, state_match=True,
        )
        assert classify_outcome(r) == ToolOutcome.SUCCESS

    def test_success_transport_ok_commit_confirmed(self):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            transport_ok=True, commit_confirmed=True,
        )
        assert classify_outcome(r) == ToolOutcome.SUCCESS

    def test_unknown_when_not_enough_info(self):
        r = ToolResultReceipt(tool_name="t", operation="o")
        assert classify_outcome(r) == ToolOutcome.UNKNOWN


class TestShouldTripCircuit:
    def test_trips_on_transport_failure(self):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            outcome=ToolOutcome.TRANSPORT_FAILURE,
        )
        assert should_trip_circuit(r) is True

    def test_trips_on_logical_failure(self):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            outcome=ToolOutcome.LOGICAL_FAILURE,
        )
        assert should_trip_circuit(r) is True

    def test_trips_on_low_confidence(self):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            outcome=ToolOutcome.SUCCESS,
            confidence_score=0.3,
        )
        assert should_trip_circuit(r) is True

    def test_does_not_trip_on_high_confidence(self):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            outcome=ToolOutcome.SUCCESS,
            confidence_score=0.85,
        )
        assert should_trip_circuit(r) is False

    def test_custom_min_confidence(self):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            outcome=ToolOutcome.SUCCESS,
            confidence_score=0.7,
        )
        assert should_trip_circuit(r, min_confidence=0.8) is True
        assert should_trip_circuit(r, min_confidence=0.5) is False

    def test_unknown_outcome_no_confidence_does_not_trip(self):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            outcome=ToolOutcome.UNKNOWN,
        )
        assert should_trip_circuit(r) is False


class TestIntegration_compute_sets_outcome:
    def test_confidence_updates_outcome_and_score(self):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            transport_ok=True,
            response_schema_ok=True,
            state_match=True,
        )
        compute_confidence(r)
        assert r.outcome == ToolOutcome.SUCCESS
        assert r.confidence_score is not None
        assert 0.0 <= r.confidence_score <= 1.0
