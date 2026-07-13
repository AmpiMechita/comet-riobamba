"""Tests for the degraded-mode re-alert cooldown in services/model_cascade.py.

Covers the persisted-state + cooldown behaviour introduced to avoid a single
one-shot Telegram alert during a sustained paid-cascade outage:

1. First entry into degraded mode → 1 alert, since_ts + last_alert_ts saved.
2. Second failure within the cooldown window → NO re-alert.
3. Failure after the cooldown elapsed → re-alert, message includes elapsed min.
4. Successful recovery via generate() → state cleared, degraded_mode = False.
5. Telegram send failure → last_alert_ts NOT advanced (retries next cycle).
6. Process restart with degraded_mode_state.json on disk → state re-hydrated.

Time is controlled by monkeypatching services.model_cascade.time.time so no
real waits occur.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import services.model_cascade as mc_mod
from services.model_cascade import ModelCascade, ProviderConfig
from config.credentials import Credentials
from utils.resilience import CircuitBreaker


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    """Redirect the degraded-state file to a temp path for the whole test."""
    p = tmp_path / "degraded_mode_state.json"
    monkeypatch.setattr(mc_mod, "_DEGRADED_STATE_FILE", str(p))
    return p


@pytest.fixture
def fake_clock(monkeypatch):
    """Controllable time.time() for services.model_cascade."""
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(mc_mod.time, "time", lambda: clock["t"])
    return clock


@pytest.fixture
def telegram():
    """Telegram stub that records every send_alert call."""
    tg = MagicMock()
    tg.sent = []
    tg.send_alert = lambda title, message, level="ERROR": tg.sent.append(
        {"title": title, "message": message, "level": level}
    )
    return tg


def _make_cascade(telegram=None):
    """Build a ModelCascade with no real providers and a stubbed telegram client."""
    c = MagicMock(spec=Credentials)
    c.ollama_url = "http://localhost:11434/v1"
    c.ollama_model = "qwen2.5:1.5b"
    c.ollama_timeout = 60
    c.ollama_cloud_model = None
    c.tier_opus = None
    c.tier_sonnet = None
    c.tier_haiku = None
    c.tier_openrouter = None
    c.cerebras_api_key = ""
    c.groq_api_key = ""
    c.anthropic_api_key = ""
    c.deepseek_api_key = ""
    with patch("services.model_cascade.Credentials.from_env", return_value=c):
        mc = ModelCascade()
    mc.providers = []
    mc.circuit_breakers = {}
    mc._append_telemetry_jsonl = lambda record: None
    if telegram is not None:
        mc._get_telegram_client = lambda: telegram
    return mc


def _add_provider(mc, name):
    p = ProviderConfig(name=name, url="http://test.local", model="m", api_key="k")
    mc.providers.append(p)
    mc.circuit_breakers[name] = CircuitBreaker(
        name=f"model_cascade.{name}", failure_threshold=99, recovery_timeout=1
    )


# ── 1. First entry → 1 alert, state saved ────────────────────────


def test_first_entry_sends_alert_and_persists_state(state_file, fake_clock, telegram, monkeypatch):
    monkeypatch.setenv("DEGRADED_ALERT_COOLDOWN_MINUTES", "30")
    mc = _make_cascade(telegram)

    mc._enter_degraded_mode(attempted=["tier_premium:m", "tier_fallback:m"], last_error=RuntimeError("boom"))

    assert len(telegram.sent) == 1
    assert telegram.sent[0]["level"] == "ERROR"
    assert "agotada" in telegram.sent[0]["message"].lower()
    assert mc.degraded_mode is True

    state = json.loads(Path(state_file).read_text(encoding="utf-8"))
    assert state["is_degraded"] is True
    assert state["since_ts"] == fake_clock["t"]
    assert state["last_alert_ts"] == fake_clock["t"]


# ── 2. Second failure within cooldown → no re-alert ──────────────


def test_within_cooldown_does_not_realert(state_file, fake_clock, telegram, monkeypatch):
    monkeypatch.setenv("DEGRADED_ALERT_COOLDOWN_MINUTES", "30")
    mc = _make_cascade(telegram)

    mc._enter_degraded_mode(attempted=["x"], last_error=RuntimeError("e1"))
    assert len(telegram.sent) == 1
    first_ts = json.loads(Path(state_file).read_text(encoding="utf-8"))["last_alert_ts"]

    # +10 min (< 30 min cooldown)
    fake_clock["t"] += 10 * 60
    mc._enter_degraded_mode(attempted=["x"], last_error=RuntimeError("e2"))

    assert len(telegram.sent) == 1, "must NOT re-alert within cooldown"
    state = json.loads(Path(state_file).read_text(encoding="utf-8"))
    assert state["last_alert_ts"] == first_ts, "last_alert_ts must not advance within cooldown"
    assert state["is_degraded"] is True


# ── 3. Failure after cooldown → re-alert with elapsed minutes ────


def test_after_cooldown_realerts_with_elapsed_minutes(state_file, fake_clock, telegram, monkeypatch):
    monkeypatch.setenv("DEGRADED_ALERT_COOLDOWN_MINUTES", "30")
    mc = _make_cascade(telegram)

    mc._enter_degraded_mode(attempted=["x"], last_error=RuntimeError("e1"))
    since_ts = json.loads(Path(state_file).read_text(encoding="utf-8"))["since_ts"]

    # +31 min (> 30 min cooldown)
    fake_clock["t"] += 31 * 60
    mc._enter_degraded_mode(attempted=["x"], last_error=RuntimeError("e2"))

    assert len(telegram.sent) == 2, "must re-alert after cooldown elapsed"
    second = telegram.sent[1]["message"]
    assert "SIGUE agotada" in second
    assert "31 min" in second, f"expected elapsed minutes in message, got: {second}"

    state = json.loads(Path(state_file).read_text(encoding="utf-8"))
    assert state["last_alert_ts"] == fake_clock["t"]
    assert state["since_ts"] == since_ts, "since_ts must remain the original episode start"


# ── 4. Successful recovery clears state ──────────────────────────


@pytest.mark.asyncio
async def test_recovery_clears_state(state_file, fake_clock, telegram, monkeypatch):
    monkeypatch.setenv("DEGRADED_ALERT_COOLDOWN_MINUTES", "30")
    mc = _make_cascade(telegram)

    # Enter degraded mode first.
    mc._enter_degraded_mode(attempted=["x"], last_error=RuntimeError("e1"))
    assert mc.degraded_mode is True
    assert json.loads(Path(state_file).read_text(encoding="utf-8"))["is_degraded"] is True

    # A working provider that returns a result on the next generate().
    _add_provider(mc, "tier_premium")
    with (
        patch.object(mc, "_call_with_retries", return_value="ok"),
        patch.object(mc, "_is_circuit_open", return_value=False),
    ):
        result = await mc.generate(prompt="hello", tier="premium")

    assert result == "ok"
    assert mc.degraded_mode is False
    state = json.loads(Path(state_file).read_text(encoding="utf-8"))
    assert state["is_degraded"] is False
    assert state["since_ts"] is None
    assert state["last_alert_ts"] is None


# ── 5. Telegram send failure → last_alert_ts not advanced ────────


def test_send_failure_does_not_advance_last_alert_ts(state_file, fake_clock, monkeypatch):
    monkeypatch.setenv("DEGRADED_ALERT_COOLDOWN_MINUTES", "30")

    failing_tg = MagicMock()
    def _boom(title, message, level="ERROR"):
        raise RuntimeError("telegram down")
    failing_tg.send_alert = _boom

    mc = _make_cascade(failing_tg)
    mc._enter_degraded_mode(attempted=["x"], last_error=RuntimeError("e1"))

    state = json.loads(Path(state_file).read_text(encoding="utf-8"))
    assert state["is_degraded"] is True, "degraded state persists even if alert fails"
    assert state["last_alert_ts"] == 0.0, "failed send must NOT advance last_alert_ts"

    # Next attempt (still within nominal cooldown) should retry immediately,
    # because last_alert_ts is still 0.0 (treated as first alert).
    ok_tg = MagicMock()
    ok_tg.sent = []
    ok_tg.send_alert = lambda title, message, level="ERROR": ok_tg.sent.append(message)
    mc._get_telegram_client = lambda: ok_tg

    fake_clock["t"] += 60  # +1 min only, far below cooldown
    mc._enter_degraded_mode(attempted=["x"], last_error=RuntimeError("e2"))

    assert len(ok_tg.sent) == 1, "must retry the alert without waiting the full cooldown"
    state2 = json.loads(Path(state_file).read_text(encoding="utf-8"))
    assert state2["last_alert_ts"] == fake_clock["t"]


# ── 6. Restart re-hydrates state from disk ───────────────────────


def test_restart_rehydrates_degraded_state(state_file, fake_clock, telegram, monkeypatch):
    monkeypatch.setenv("DEGRADED_ALERT_COOLDOWN_MINUTES", "30")

    # First process: enters degraded mode and persists state.
    mc1 = _make_cascade(telegram)
    mc1._enter_degraded_mode(attempted=["x"], last_error=RuntimeError("e1"))
    assert len(telegram.sent) == 1
    saved = json.loads(Path(state_file).read_text(encoding="utf-8"))
    assert saved["is_degraded"] is True

    # Simulate a restart: a brand-new ModelCascade should read the state file
    # and come up already knowing it is degraded.
    mc2 = _make_cascade(telegram)
    assert mc2.degraded_mode is True, "restart must re-hydrate degraded_mode from disk"

    # And it should honour the persisted cooldown: a failure +10 min after the
    # first alert (across the restart) must NOT re-alert.
    fake_clock["t"] += 10 * 60
    mc2._enter_degraded_mode(attempted=["x"], last_error=RuntimeError("e2"))
    assert len(telegram.sent) == 1, "cooldown must survive the restart"

    # After the cooldown (+31 min total) it re-alerts.
    fake_clock["t"] += 21 * 60
    mc2._enter_degraded_mode(attempted=["x"], last_error=RuntimeError("e3"))
    assert len(telegram.sent) == 2


# ── 7. Restart with clean state → not degraded ───────────────────


def test_restart_without_state_is_not_degraded(state_file, monkeypatch):
    # No state file on disk → fresh cascade must not think it is degraded.
    assert not Path(state_file).exists()
    mc = _make_cascade()
    assert mc.degraded_mode is False
