# -*- coding: utf-8 -*-
"""Tests for utils/resilience.py — callback on_open del CircuitBreaker."""

from utils.resilience import CircuitBreaker, CircuitState


def test_on_open_called_once_on_closed_to_open_transition():
    """on_open se dispara exactamente una vez en CLOSED→OPEN, no en fallos posteriores."""
    calls = []
    cb = CircuitBreaker(name="cb_test", failure_threshold=3, recovery_timeout=60, on_open=calls.append)

    cb.record_failure()
    cb.record_failure()
    assert calls == []
    assert cb.state == CircuitState.CLOSED

    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert calls == ["cb_test"]

    cb.record_failure()
    cb.record_failure()
    assert calls == ["cb_test"]


def test_on_open_exception_does_not_break_record_failure():
    """Un callback que lanza no interrumpe la transición a OPEN."""
    def boom(name):
        raise RuntimeError("boom")

    cb = CircuitBreaker(name="cb_boom", failure_threshold=1, recovery_timeout=60, on_open=boom)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN


def test_on_open_none_is_safe():
    """Sin callback (default None) el breaker funciona igual que antes."""
    cb = CircuitBreaker(name="cb_none", failure_threshold=2, recovery_timeout=60)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN


def test_on_open_fires_on_force_open_transition_only():
    """force_open (rate-limit/4xx) también dispara on_open, pero solo en la transición."""
    calls = []
    cb = CircuitBreaker(name="cb_force", failure_threshold=5, recovery_timeout=60, on_open=calls.append)

    cb.force_open(reason="rate_limit", duration_seconds=3600)
    assert cb.state == CircuitState.OPEN
    assert calls == ["cb_force"]

    cb.force_open(reason="rate_limit_again")  # ya estaba OPEN → no re-dispara
    assert calls == ["cb_force"]
