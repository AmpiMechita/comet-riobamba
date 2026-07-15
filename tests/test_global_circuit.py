"""Tests for services/global_circuit.py — hysteresis for sleep interval."""

import os
from unittest.mock import patch, MagicMock

import pytest

from services import global_circuit as gc


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Reset module-level breaker and cycle control between tests."""
    gc._breaker = None
    _store: dict = {}

    def _fake_get_flag(key: str) -> dict:
        return _store.get(key)

    def _fake_set_flag(key: str, value: dict) -> None:
        _store[key] = value

    with (
        patch("services.global_circuit.get_flag", side_effect=_fake_get_flag),
        patch("services.global_circuit.set_flag", side_effect=_fake_set_flag),
    ):
        yield


_FAKE_BREAKER = MagicMock()
_FAKE_BREAKER.can_execute.return_value = True


@pytest.fixture(autouse=True)
def _mock_breaker():
    """Prevent SQLiteCircuitPersistence from being created during tests."""
    with patch("services.global_circuit._get_breaker", return_value=_FAKE_BREAKER):
        yield


def _expand_to(base: int = 3600) -> None:
    """Run one 429 error to push current interval above base."""
    gc.register_cycle_result(
        error="429 Too Many Requests", had_activity=False,
        base_interval_seconds=base,
    )


def _expand_twice(base: int = 3600) -> None:
    """Run two 429 errors to push interval further up."""
    _expand_to(base)
    gc.register_cycle_result(
        error="429 Too Many Requests", had_activity=False,
        base_interval_seconds=base,
    )


class TestGlobalCircuitHysteresis:
    """Hysteresis: compress only after N consecutive successes, expand on 429/5xx."""

    # ── Compression (triggers on every clean cycle) ─────────────────

    def test_compress_on_first_clean(self):
        """Compression triggers immediately on first clean cycle."""
        _expand_to()
        interval = gc.register_cycle_result(
            error=None, had_activity=True, base_interval_seconds=3600,
        )
        # After expansion: 5400. First clean: compresses to 3600.
        assert interval == 3600

    def test_compress_every_clean_cycle(self):
        """Each clean cycle reduces interval until base is reached."""
        _expand_twice()  # interval = 8100
        gc.register_cycle_result(error=None, had_activity=True, base_interval_seconds=3600)  # 8100→5400
        gc.register_cycle_result(error=None, had_activity=True, base_interval_seconds=3600)  # 5400→3600
        interval = gc.register_cycle_result(
            error=None, had_activity=True, base_interval_seconds=3600,
        )
        # 3600 = base: no further compression
        assert interval == 3600

    def test_compress_stops_at_base(self):
        """Compression does not reduce interval below base_interval_seconds."""
        _expand_twice()  # interval = 8100
        for _ in range(3):  # 8100→5400→3600→stays
            gc.register_cycle_result(error=None, had_activity=True, base_interval_seconds=3600)
        interval = gc.register_cycle_result(
            error=None, had_activity=True, base_interval_seconds=3600,
        )
        # At base: no further compression
        assert interval == 3600

    def test_compression_resumes_after_re_expand(self):
        """After re-expanding, compression again reduces interval each clean cycle."""
        _expand_twice()  # interval = 8100
        for _ in range(3):  # 8100→5400→3600→stays
            gc.register_cycle_result(error=None, had_activity=True, base_interval_seconds=3600)
        # Expand again
        gc.register_cycle_result(
            error="429 Too Many Requests", had_activity=False, base_interval_seconds=3600,
        )  # 3600→5400
        interval = gc.register_cycle_result(
            error=None, had_activity=True, base_interval_seconds=3600,
        )
        # 5400 / 1.5 = 3600
        assert interval == 3600

    # ── Expansion on 429/5xx ──────────────────────────────────

    def test_429_expands_immediately(self):
        """429 error expands sleep by 1.5x immediately."""
        gc.register_cycle_result(error=None, had_activity=True, base_interval_seconds=14400)
        interval = gc.register_cycle_result(
            error="429 Too Many Requests", had_activity=False, base_interval_seconds=14400,
        )
        assert interval == 21600  # 14400 * 1.5 = 21600

    def test_5xx_expands_immediately(self):
        """5xx error expands sleep by 1.5x immediately."""
        gc.register_cycle_result(error=None, had_activity=True, base_interval_seconds=14400)
        interval = gc.register_cycle_result(
            error="500 Internal Server Error", had_activity=False, base_interval_seconds=14400,
        )
        assert interval == 21600  # 14400 * 1.5 = 21600

    def test_502_expands_immediately(self):
        """502 Bad Gateway expands sleep by 1.5x."""
        gc.register_cycle_result(error=None, had_activity=True, base_interval_seconds=14400)
        interval = gc.register_cycle_result(
            error="502 Bad Gateway", had_activity=False, base_interval_seconds=14400,
        )
        assert interval == 21600

    # ── Clamps ─────────────────────────────────────────────────

    def test_expansion_capped_at_28800(self):
        """Expansion is capped at 28800s ceiling."""
        gc.register_cycle_result(error=None, had_activity=True, base_interval_seconds=28800)
        interval = gc.register_cycle_result(
            error="429 Too Many Requests", had_activity=False, base_interval_seconds=28800,
        )
        assert interval <= 28800

    def test_floor_at_3600(self):
        """Sleep never goes below 3600s floor."""
        for _ in range(10):
            gc.register_cycle_result(error=None, had_activity=True, base_interval_seconds=3600)
        ctl = gc._load_cycle_control()
        assert ctl["current_interval_seconds"] >= 3600

    # test_compress_after_1_via_env y test_expand_factor_2_via_env eliminados:
    # _COMPRESS_AFTER y _EXPAND_FACTOR no están implementados en el módulo.

    # ── Error resets success counter ───────────────────────────

    def test_inactive_cycle_does_not_expand(self):
        """A cycle without activity increments consecutive_bad but does not expand."""
        _expand_to()  # interval = 5400, consecutive_bad = 1
        gc.register_cycle_result(error=None, had_activity=True, base_interval_seconds=3600)  # compress → 3600
        gc.register_cycle_result(error=None, had_activity=True, base_interval_seconds=3600)  # stays 3600
        # Inactive cycle: consecutive_bad → 1, but no error → no expand
        interval = gc.register_cycle_result(
            error=None, had_activity=False, base_interval_seconds=3600,
        )
        # At base, no error, consecutive_bad=1 < 2 → stays at 3600.
        assert interval == 3600
