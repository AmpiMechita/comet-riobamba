# -*- coding: utf-8 -*-
"""Tests for services/telegram_control.py — command handlers, pause/resume, briefing."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ── /pause and /resume ────────────────────────────────────────────

def test_pause_creates_flag_file(tmp_path):
    """_cmd_pause creates data/.agent_paused and returns confirmation."""
    from services.telegram_control import _cmd_pause
    pause_file = tmp_path / ".agent_paused"
    with patch("services.telegram_control.Path", return_value=pause_file):
        result = _cmd_pause()
    assert "pausado" in result.lower() or "pause" in result.lower()
    assert pause_file.exists()


def test_resume_when_paused_removes_flag(tmp_path):
    """_cmd_resume removes the pause flag and confirms."""
    from services.telegram_control import _cmd_resume
    pause_file = tmp_path / ".agent_paused"
    pause_file.write_text("2026-01-01T00:00:00", encoding="utf-8")
    with patch("services.telegram_control.Path", return_value=pause_file):
        result = _cmd_resume()
    assert "reanudado" in result.lower()
    assert not pause_file.exists()


def test_resume_when_not_paused_shows_not_paused():
    """_cmd_resume without flag shows 'not paused'."""
    from services.telegram_control import _cmd_resume
    nonexistent = Path("/tmp/nonexistent_agent_paused_xyz")
    with patch("services.telegram_control.Path", return_value=nonexistent):
        result = _cmd_resume()
        assert "no estaba pausado" in result.lower()


def test_is_agent_paused_detects_flag():
    """is_agent_paused() returns True when flag exists."""
    from services.telegram_control import is_agent_paused
    with patch.object(Path, "exists", return_value=True):
        assert is_agent_paused() is True
    with patch.object(Path, "exists", return_value=False):
        assert is_agent_paused() is False


# ── handle_command dispatch ───────────────────────────────────────

def test_handle_command_unknown_returns_help():
    from services.telegram_control import handle_command
    result = handle_command("/unknown_cmd_xyz")
    assert "Comandos" in result


def test_handle_command_pause(tmp_path):
    """handle_command('/pause') dispatches to _cmd_pause and creates flag."""
    from services.telegram_control import handle_command
    pause_file = tmp_path / ".agent_paused"
    with patch("services.telegram_control.Path", return_value=pause_file):
        result = handle_command("/pause")
    assert "pausado" in result.lower()
    assert pause_file.exists()


def test_handle_command_resume(tmp_path):
    """handle_command('/resume') dispatches to _cmd_resume and removes flag."""
    from services.telegram_control import handle_command
    pause_file = tmp_path / ".agent_paused"
    pause_file.write_text("2026-01-01T00:00:00", encoding="utf-8")
    with patch("services.telegram_control.Path", return_value=pause_file):
        result = handle_command("/resume")
    assert "reanudado" in result.lower()
    assert not pause_file.exists()


def test_handle_command_health_without_agent():
    """_cmd_health called without agent shows real state (not fallback)."""
    from services.telegram_control import _cmd_health
    with (
        patch("core.state_manager.AgentState") as mock_state,
        patch("services.dedup_store.DedupStore") as mock_ds,
    ):
        mock_state.return_value.cycle_count = 42
        mock_state.return_value.posts_today = 3
        mock_state.return_value.comments_today = 15
        mock_state.return_value.consecutive_failures = 0
        result = _cmd_health(agent=None)
    assert "Cycle: 42" in result
    assert "Posts today: 3" in result
    assert "Comments today: 15" in result


def test_handle_command_case_insensitive(tmp_path):
    """handle_command lowercases the command before dispatching."""
    from services.telegram_control import handle_command
    state_file = tmp_path / "self_eval_state.json"
    today = __import__("datetime").datetime.now().date().isoformat()
    state_file.write_text(
        json.dumps({today: {"comments_published": 5, "upvotes_today": 2}}),
        encoding="utf-8",
    )
    with patch("services.telegram_control.Path", return_value=state_file):
        lower_result = handle_command("/stats")
        upper_result = handle_command("/STATS")
    assert lower_result == upper_result
    assert "5" in lower_result


def test_handle_command_with_extra_spaces(tmp_path):
    """handle_command strips whitespace and splits by spaces correctly."""
    from services.telegram_control import handle_command
    state_file = tmp_path / "self_eval_state.json"
    today = __import__("datetime").datetime.now().date().isoformat()
    state_file.write_text(
        json.dumps({today: {"comments_published": 7, "upvotes_today": 3}}),
        encoding="utf-8",
    )
    with patch("services.telegram_control.Path", return_value=state_file):
        result = handle_command("  /stats  extra  ")
    assert "7" in result
    assert "Comandos" not in result


# ── notificaciones ────────────────────────────────────────────────

def test_should_send_briefing_returns_bool():
    from services.telegram_control import should_send_briefing
    result = should_send_briefing(hour=99)
    assert isinstance(result, bool)


def test_check_engagement_spike_low_count_is_none():
    from services.telegram_control import check_engagement_spike
    result = check_engagement_spike("post-1", 2, threshold=5)
    assert result is None


def test_check_quality_issues_low_count_is_none():
    from services.telegram_control import check_quality_issues
    result = check_quality_issues(1, window_minutes=30)
    assert result is None


# ── log_proposal ──────────────────────────────────────────────────

def test_log_proposal_writes_to_file(tmp_path):
    from services.telegram_control import log_proposal
    proposals_file = tmp_path / "proposals.jsonl"
    with patch("services.telegram_control.AGENT_PROPOSALS_FILE", proposals_file):
        log_proposal("Test proposal text")
    assert proposals_file.exists()
    record = json.loads(proposals_file.read_text(encoding="utf-8").strip())
    assert record["proposal"] == "Test proposal text"
    assert "timestamp" in record


def test_cmd_pause_resume_roundtrip(tmp_path):
    from services.telegram_control import _cmd_pause, _cmd_resume
    pause_file = tmp_path / ".agent_paused"

    def fake_path(p):
        return pause_file

    with patch("services.telegram_control.Path", side_effect=fake_path):
        r1 = _cmd_pause()
        assert pause_file.exists()
        assert "pausado" in r1.lower()

    with patch("services.telegram_control.Path", side_effect=fake_path):
        r2 = _cmd_resume()
        assert not pause_file.exists()
        assert "reanudado" in r2.lower()


# ── check_recent_quality_issues ───────────────────────────────────

def _write_attempts(path, entries):
    lines = []
    for e in entries:
        lines.append(e if isinstance(e, str) else json.dumps(e))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_check_recent_quality_issues_counts_only_recent_failures(tmp_path):
    """Cuenta fallos recientes, excluyendo entradas viejas, success y líneas corruptas."""
    from datetime import datetime, timedelta, timezone
    import services.telegram_control as tc

    now = datetime.now(timezone.utc)
    recent = (now - timedelta(minutes=5)).isoformat()
    old = (now - timedelta(minutes=90)).isoformat()
    attempts_file = tmp_path / "generation_attempts.jsonl"
    _write_attempts(attempts_file, [
        {"timestamp": recent, "outcome": "validation_failed:too_short"},
        {"timestamp": recent, "outcome": "provider_error"},
        {"timestamp": recent, "outcome": "validation_failed:off_topic"},
        {"timestamp": recent, "outcome": "success"},
        {"timestamp": old, "outcome": "provider_error"},
        "{esto no es json valido",
    ])

    with patch.object(tc, "GENERATION_ATTEMPTS_FILE", attempts_file), \
         patch.dict(tc._alert_cooldowns, {}, clear=True):
        result = tc.check_recent_quality_issues(window_minutes=30)

    assert result is not None
    assert "3" in result


def test_check_recent_quality_issues_missing_file_returns_none(tmp_path):
    """Sin archivo de intentos retorna None sin error."""
    import services.telegram_control as tc
    missing = tmp_path / "no_existe.jsonl"
    with patch.object(tc, "GENERATION_ATTEMPTS_FILE", missing), \
         patch.dict(tc._alert_cooldowns, {}, clear=True):
        assert tc.check_recent_quality_issues(window_minutes=30) is None


def test_check_recent_quality_issues_below_threshold_returns_none(tmp_path):
    """Con menos de 3 rechazos recientes no hay alerta."""
    from datetime import datetime, timedelta, timezone
    import services.telegram_control as tc

    now = datetime.now(timezone.utc)
    recent = (now - timedelta(minutes=5)).isoformat()
    old = (now - timedelta(minutes=120)).isoformat()
    attempts_file = tmp_path / "generation_attempts.jsonl"
    _write_attempts(attempts_file, [
        {"timestamp": recent, "outcome": "provider_error"},
        {"timestamp": recent, "outcome": "success"},
        {"timestamp": old, "outcome": "provider_error"},
        {"timestamp": old, "outcome": "provider_error"},
        {"timestamp": old, "outcome": "provider_error"},
    ])

    with patch.object(tc, "GENERATION_ATTEMPTS_FILE", attempts_file), \
         patch.dict(tc._alert_cooldowns, {}, clear=True):
        assert tc.check_recent_quality_issues(window_minutes=30) is None
