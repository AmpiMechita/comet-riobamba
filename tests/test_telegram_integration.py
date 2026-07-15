"""Tests for Telegram integration: balance checks and energy intel alerts."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import date, datetime, timedelta
from pathlib import Path


# ── Test Telegram send ──────────────────────────────────────────


def test_telegram_send_success():
    """Message sent successfully via Telegram API."""
    from services.telegram_client import TelegramClient

    client = TelegramClient(bot_token="fake-token", chat_id="12345", enabled=True)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True}

    with patch("services.telegram_client.requests.post", return_value=mock_response) as mock_post:
        result = client.send_message("Hello test")
        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "sendMessage" in call_kwargs[0][0] or "sendMessage" in str(call_kwargs)


def test_telegram_send_failure_doesnt_crash():
    """If Telegram API fails, no exception is raised."""
    from services.telegram_client import TelegramClient

    client = TelegramClient(bot_token="fake-token", chat_id="12345", enabled=True)

    with patch("services.telegram_client.requests.post", side_effect=Exception("Network down")):
        result = client.send_message("This should not crash")
        assert result is False


def test_telegram_disabled_noop():
    """Disabled client does not make any HTTP calls."""
    from services.telegram_client import TelegramClient

    client = TelegramClient(bot_token="fake-token", chat_id="12345", enabled=False)

    with patch("services.telegram_client.requests.post") as mock_post:
        result = client.send_message("Should not send")
        assert result is False
        mock_post.assert_not_called()


# ── Test DeepSeek balance ───────────────────────────────────────


def test_deepseek_balance_parse():
    """Correctly parses the DeepSeek balance JSON response."""
    from services.deepseek_balance import check_deepseek_balance

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "balance_infos": [
            {"currency": "USD", "total_balance": "4.52", "granted_balance": "0.00", "topped_up_balance": "4.52"}
        ]
    }

    with patch("services.deepseek_balance.requests.get", return_value=mock_response), \
         patch.dict("os.environ", {"MODEL_TIER_OPUS_API_KEY": "sk-test-key"}):
        balance = check_deepseek_balance()
        assert balance == 4.52


def test_deepseek_balance_no_api_key():
    """Returns None if no API key configured."""
    from services.deepseek_balance import check_deepseek_balance

    with patch.dict("os.environ", {"MODEL_TIER_OPUS_API_KEY": ""}):
        balance = check_deepseek_balance()
        assert balance is None


def test_deepseek_balance_http_error():
    """Returns None on HTTP error without crashing."""
    from services.deepseek_balance import check_deepseek_balance

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"

    with patch("services.deepseek_balance.requests.get", return_value=mock_response), \
         patch.dict("os.environ", {"MODEL_TIER_OPUS_API_KEY": "sk-test-key"}):
        balance = check_deepseek_balance()
        assert balance is None


def test_deepseek_balance_network_error():
    """Returns None on network error without crashing."""
    from services.deepseek_balance import check_deepseek_balance
    import requests as req

    with patch("services.deepseek_balance.requests.get", side_effect=req.ConnectionError("timeout")), \
         patch.dict("os.environ", {"MODEL_TIER_OPUS_API_KEY": "sk-test-key"}):
        balance = check_deepseek_balance()
        assert balance is None


# ── Test balance not sent twice same day ────────────────────────


def test_balance_not_sent_twice_same_day():
    """Daily balance is not sent if it was already sent today."""
    from services.deepseek_balance import was_balance_sent_today, mark_balance_sent, _LAST_CHECK_FILE
    from pathlib import Path
    import tempfile

    # Use a temp file to avoid polluting the real data dir
    with patch("services.deepseek_balance._LAST_CHECK_FILE", Path(tempfile.mktemp())):
        from services import deepseek_balance
        test_file = Path(tempfile.mktemp())
        deepseek_balance._LAST_CHECK_FILE = test_file

        # First check: not sent yet
        assert deepseek_balance.was_balance_sent_today() is False

        # Mark as sent
        deepseek_balance.mark_balance_sent()

        # Second check: already sent
        assert deepseek_balance.was_balance_sent_today() is True

        # Clean up
        if test_file.exists():
            test_file.unlink()


def test_format_balance_message_low_balance():
    """Low balance message includes warning."""
    from services.deepseek_balance import format_balance_message

    msg = format_balance_message(1.50, 42)
    assert "1.50" in msg
    assert "SALDO BAJO" in msg
    assert "#42" in msg


def test_format_balance_message_normal():
    """Normal balance message does not include warning."""
    from services.deepseek_balance import format_balance_message

    msg = format_balance_message(15.00, 1)
    assert "15.00" in msg
    assert "SALDO BAJO" not in msg


# ── Test Energy Intel Telegram ──────────────────────────────────


def test_energy_intel_sends_telegram():
    """When energy intel finds frontier claims, Telegram is called."""
    from services.energy_intel_telegram import _format_claim_alert, _is_frontier_claim

    claim = {
        "title": "New solid-state battery achieves 500 Wh/kg",
        "technology": "solid-state-battery",
        "metric_name": "energy_density",
        "metric_value": 500.0,
        "metric_unit": "Wh/kg",
        "source_url": "https://arxiv.org/abs/1234",
        "source_type": "paper",
        "claim_text": "We demonstrate a novel sulfide electrolyte...",
    }

    # Check frontier detection
    assert _is_frontier_claim(claim) is True

    # Check message formatting
    msg = _format_claim_alert(claim)
    assert "solid-state-battery" in msg
    assert "500" in msg
    assert "Wh/kg" in msg
    assert "arxiv" in msg


def test_non_frontier_claim_not_alerted():
    """Non-frontier claims (other tech, no metrics) are not alerted."""
    from services.energy_intel_telegram import _is_frontier_claim

    claim = {
        "technology": "other",
        "metric_name": "",
        "metric_value": None,
    }
    assert _is_frontier_claim(claim) is False


def test_frontier_with_metrics_alerted():
    """Any technology with quantified metrics triggers alert."""
    from services.energy_intel_telegram import _is_frontier_claim

    claim = {
        "technology": "sodium-ion",
        "metric_name": "energy_density",
        "metric_value": 160.0,
    }
    assert _is_frontier_claim(claim) is True


# ── Test Energy Intel throttle ──────────────────────────────────


def test_energy_intel_throttle():
    """Does not run if less than 1 hour has passed since last run."""
    from services.energy_intel_telegram import should_run_energy_intel, _LAST_RUN_FILE
    from datetime import datetime
    import tempfile

    from services import energy_intel_telegram
    original = energy_intel_telegram._LAST_RUN_FILE
    test_file = Path(tempfile.mktemp())

    try:
        energy_intel_telegram._LAST_RUN_FILE = test_file
        # Write a timestamp from 30 minutes ago
        thirty_min_ago = (datetime.now() - timedelta(minutes=30)).isoformat()
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(thirty_min_ago, encoding="utf-8")

        assert energy_intel_telegram.should_run_energy_intel() is False
    finally:
        energy_intel_telegram._LAST_RUN_FILE = original
        if test_file.exists():
            test_file.unlink()


def test_energy_intel_runs_after_1_hour():
    """Runs if more than 1 hour has passed since last run."""
    from services.energy_intel_telegram import should_run_energy_intel, _LAST_RUN_FILE
    from datetime import datetime
    import tempfile

    from services import energy_intel_telegram
    original = energy_intel_telegram._LAST_RUN_FILE
    test_file = Path(tempfile.mktemp())

    try:
        energy_intel_telegram._LAST_RUN_FILE = test_file
        # Write a timestamp from 90 minutes ago
        ninety_min_ago = (datetime.now() - timedelta(minutes=90)).isoformat()
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(ninety_min_ago, encoding="utf-8")

        assert energy_intel_telegram.should_run_energy_intel() is True
    finally:
        energy_intel_telegram._LAST_RUN_FILE = original
        if test_file.exists():
            test_file.unlink()


def test_energy_intel_runs_if_never_run():
    """Runs if the timestamp file doesn't exist (first run)."""
    from services import energy_intel_telegram
    import tempfile

    original = energy_intel_telegram._LAST_RUN_FILE
    test_file = Path(tempfile.mktemp())  # does not exist

    try:
        energy_intel_telegram._LAST_RUN_FILE = test_file
        assert energy_intel_telegram.should_run_energy_intel() is True
    finally:
        energy_intel_telegram._LAST_RUN_FILE = original


def test_energy_intel_error_doesnt_crash_phase_c():
    """If energy intel fails, Phase C continues without crashing."""
    from phases.phase_c_analytics import PhaseCAnalytics
    from unittest.mock import MagicMock, patch

    mock_deps = MagicMock()
    mock_deps.model_cascade = MagicMock()
    mock_deps.moltbook_client = MagicMock()
    mock_deps.behavior_cfg = {}
    mock_deps.telegram_client = MagicMock()
    mock_deps.telegram_client.enabled = True
    mock_deps.max_phase_c_replies_per_day = 5
    mock_deps.max_phase_c_replies_per_cycle = 2
    mock_deps.get_comments_today = MagicMock(return_value=0)
    mock_deps.increment_comments_today = MagicMock()
    mock_deps.cycle_count = 1

    phase_c = PhaseCAnalytics(mock_deps)

    # Simulate energy intel import failure
    with patch(
        "services.energy_intel_telegram.run_energy_intel_with_alerts",
        side_effect=Exception("scraper timeout"),
    ):
        # Should not raise — just logs warning
        phase_c._maybe_run_energy_intel()


# ── Test /clean confirmation flow ────────────────────────────────


@pytest.mark.asyncio
async def test_clean_counts_pending_does_not_delete():
    """_handle_clean must count pending items and request confirmation,
    but must NOT execute any DELETE."""
    from services.telegram_client import TelegramClient

    client = TelegramClient(bot_token="fake-token", chat_id="12345", enabled=True)
    client.send_message = MagicMock()

    mock_cursor = MagicMock()
    mock_cursor.execute.return_value.fetchone.return_value = [5]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("services.telegram_client.sqlite3.connect", return_value=mock_conn):
        await client._handle_clean(agent=MagicMock())

    # Must count pending items
    mock_cursor.execute.assert_any_call(
        "SELECT COUNT(*) FROM outbox WHERE status = 'pending'"
    )
    # Must NOT execute any DELETE in the count phase
    for call in mock_cursor.execute.call_args_list:
        args = call[0][0] if call[0] else ""
        assert "DELETE" not in str(args), f"DELETE found in: {args}"
    # Confirmation message sent
    sent_text = client.send_message.call_args[0][0]
    assert "5" in sent_text
    assert "IRREVERSIBLE" in sent_text
    assert "/clean_confirm" in sent_text
    # Pending state stored
    assert client._pending_clean is not None
    assert client._pending_clean["count"] == 5


@pytest.mark.asyncio
async def test_clean_zero_pending_shows_empty():
    """When outbox has zero pending items, show empty message."""
    from services.telegram_client import TelegramClient

    client = TelegramClient(bot_token="fake-token", chat_id="12345", enabled=True)
    client.send_message = MagicMock()

    mock_cursor = MagicMock()
    mock_cursor.execute.return_value.fetchone.return_value = [0]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("services.telegram_client.sqlite3.connect", return_value=mock_conn):
        await client._handle_clean(agent=MagicMock())

    sent_text = client.send_message.call_args[0][0]
    assert "pendientes" in sent_text


@pytest.mark.asyncio
async def test_clean_confirm_without_clean_rejected():
    """_handle_clean_confirm without prior _handle_clean must be rejected."""
    from services.telegram_client import TelegramClient

    client = TelegramClient(bot_token="fake-token", chat_id="12345", enabled=True)
    client.send_message = MagicMock()
    client._pending_clean = None

    await client._handle_clean_confirm(agent=MagicMock())

    sent_text = client.send_message.call_args[0][0]
    assert "pendiente" in sent_text


@pytest.mark.asyncio
async def test_clean_confirm_within_window_executes_delete():
    """_handle_clean_confirm within 60s window must execute DELETE."""
    from services.telegram_client import TelegramClient
    import time

    client = TelegramClient(bot_token="fake-token", chat_id="12345", enabled=True)
    client.send_message = MagicMock()
    client._pending_clean = {"count": 3, "since": time.monotonic()}

    mock_cursor = MagicMock()
    mock_cursor.execute.return_value.rowcount = 3
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("services.telegram_client.sqlite3.connect", return_value=mock_conn):
        await client._handle_clean_confirm(agent=MagicMock())

    # DELETE must have been executed
    delete_calls = [
        c for c in mock_cursor.execute.call_args_list
        if "DELETE" in str(c[0][0] if c[0] else "")
    ]
    assert len(delete_calls) >= 1
    sent_text = client.send_message.call_args[0][0]
    assert "3" in sent_text
    assert "limpia" in sent_text.lower() or "eliminaron" in sent_text.lower()
    # State cleared
    assert client._pending_clean is None


@pytest.mark.asyncio
async def test_clean_confirm_expired_rejected():
    """_handle_clean_confirm after 60s window must be rejected."""
    from services.telegram_client import TelegramClient
    import time

    client = TelegramClient(bot_token="fake-token", chat_id="12345", enabled=True)
    client.send_message = MagicMock()
    client._pending_clean = {"count": 3, "since": time.monotonic() - 61}

    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("services.telegram_client.sqlite3.connect", return_value=mock_conn):
        await client._handle_clean_confirm(agent=MagicMock())

    sent_text = client.send_message.call_args[0][0]
    assert "expiro" in sent_text.lower() or "60" in sent_text
