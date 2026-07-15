"""Tests for services/tool_quality_metrics.py — ATQS KPI aggregation."""

from services.tool_feedback import ToolOutcome, ToolResultReceipt
from services.tool_quality_metrics import ToolQualityWindow, update_window


def test_atqs_empty_window():
    w = ToolQualityWindow()
    assert w.atqs() is None


def test_high_conf_increments_atqs():
    w = ToolQualityWindow()
    r = ToolResultReceipt(
        tool_name="t", operation="o",
        confidence_score=0.95,
        outcome=ToolOutcome.SUCCESS,
    )
    update_window(w, r)
    assert w.total_calls == 1
    assert w.high_conf_calls == 1
    assert w.atqs() == 1.0


def test_low_conf_does_not_increment_high_conf():
    w = ToolQualityWindow()
    r = ToolResultReceipt(
        tool_name="t", operation="o",
        confidence_score=0.2,
        outcome=ToolOutcome.UNKNOWN,
    )
    update_window(w, r)
    assert w.total_calls == 1
    assert w.high_conf_calls == 0
    assert w.low_conf_calls == 1
    assert w.atqs() == 0.0


def test_failures_counters():
    w = ToolQualityWindow()
    r1 = ToolResultReceipt(
        tool_name="t", operation="o",
        confidence_score=0.9,
        outcome=ToolOutcome.LOGICAL_FAILURE,
    )
    r2 = ToolResultReceipt(
        tool_name="t", operation="o",
        confidence_score=0.1,
        outcome=ToolOutcome.TRANSPORT_FAILURE,
    )
    update_window(w, r1)
    update_window(w, r2)
    assert w.total_calls == 2
    assert w.logical_failures == 1
    assert w.transport_failures == 1
    assert w.atqs() == 0.5


def test_confidence_none_no_impact():
    w = ToolQualityWindow()
    r = ToolResultReceipt(
        tool_name="t", operation="o",
        confidence_score=None,
        outcome=ToolOutcome.UNKNOWN,
    )
    update_window(w, r)
    assert w.total_calls == 1
    assert w.high_conf_calls == 0
    assert w.low_conf_calls == 0


def test_multiple_high_confidence():
    w = ToolQualityWindow()
    for _ in range(3):
        r = ToolResultReceipt(
            tool_name="t", operation="o",
            confidence_score=0.8,
            outcome=ToolOutcome.SUCCESS,
        )
        update_window(w, r)
    assert w.total_calls == 3
    assert w.high_conf_calls == 3
    assert w.atqs() == 1.0


def test_custom_thresholds():
    w = ToolQualityWindow()
    r = ToolResultReceipt(
        tool_name="t", operation="o",
        confidence_score=0.7,
        outcome=ToolOutcome.SUCCESS,
    )
    update_window(w, r, high_threshold=0.85)
    assert w.high_conf_calls == 0  # 0.7 < 0.85
    assert w.low_conf_calls == 0   # 0.7 >= 0.4
    assert w.atqs() == 0.0


def test_outcome_not_failure_no_increment():
    w = ToolQualityWindow()
    r = ToolResultReceipt(
        tool_name="t", operation="o",
        confidence_score=0.5,
        outcome=ToolOutcome.SUCCESS,
    )
    update_window(w, r)
    assert w.logical_failures == 0
    assert w.transport_failures == 0
