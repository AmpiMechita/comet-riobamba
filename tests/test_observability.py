"""Tests for observability hardening (7.2) — exceptions are visible but non-fatal."""

import logging
from unittest.mock import patch, MagicMock

import pytest

from core.observability import send_event, _do_send_event


def test_send_event_does_not_crash_on_metrics_error():
    with patch("core.observability._do_send_event", side_effect=RuntimeError("metrics exploded")):
        # Must not raise
        send_event("cycle_start", {"cycle": 1})


def test_send_event_logs_error_on_failure(caplog):
    with patch("core.observability._do_send_event", side_effect=RuntimeError("metrics exploded")):
        with caplog.at_level(logging.ERROR, logger="observability"):
            send_event("phase_a_publish_success", {"count": 1})
            assert any("metrics exploded" in record.message for record in caplog.records)
            assert any("Observability: error sending event" in record.message for record in caplog.records)


def test_send_event_normal_flow_works():
    with patch("core.observability._do_send_event") as mock_do:
        send_event("cycle_end", {"cycle": 5})
        mock_do.assert_called_once_with("cycle_end", {"cycle": 5})


def test_send_event_no_payload():
    with patch("core.observability._do_send_event") as mock_do:
        send_event("state_saved")
        mock_do.assert_called_once_with("state_saved", None)


def test_do_send_event_metrics_error_propagates():
    with patch("core.metrics.ingest_event", side_effect=RuntimeError("metrics down")):
        with pytest.raises(RuntimeError, match="metrics down"):
            _do_send_event("cycle_start", {"cycle": 1})
