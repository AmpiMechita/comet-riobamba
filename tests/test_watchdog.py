"""Tests para monitoring/watchdog.py — lógica pura de decisiones (18/08/2026).

Cubre: parsing de telemetría (circuitos), conteo de errores por ventana,
cooldown compartido de alertas, estado del agente, decisión de auto-reinicio,
e inactividad de publicación. Se evita la red y los procesos externos.
"""
import json
import time
from unittest.mock import patch

import pytest

from monitoring.watchdog import (
    agent_status,
    check_cooldown,
    count_error_lines,
    decide_restart,
    inactivity_flag,
    parse_iso,
    parse_telemetry,
)


# ── parse_iso ──────────────────────────────────────────────────────

def test_parse_iso_with_tz():
    assert parse_iso("2026-08-18T10:49:37+00:00") is not None


def test_parse_iso_with_long_fraction():
    assert parse_iso("2026-08-18T06:37:04.4060388-05:00") is not None


def test_parse_iso_naive():
    assert parse_iso("2026-08-18 06:36:51") is not None


def test_parse_iso_invalid():
    assert parse_iso("no-es-fecha") is None
    assert parse_iso(None) is None


# ── parse_telemetry ────────────────────────────────────────────────

def _tl(tier, success, ts, error=None):
    return json.dumps({"ts": ts, "tier": tier, "success": success,
                       "error": error})


def test_parse_telemetry_counts_fails_and_oks_in_window():
    now = time.time()
    rows = [
        _tl("flash", "fail", _iso(now - 60)),
        _tl("flash", "fail", _iso(now - 120)),
        _tl("flash", "fail", _iso(now - 180)),
        _tl("flash", "ok", _iso(now - 90)),
        _tl("classify", "ok", _iso(now - 60)),
    ]
    fails, oks = parse_telemetry(rows, 600, now)
    assert fails["flash"] == 3
    assert oks["flash"] == 1
    assert oks["classify"] == 1


def test_parse_telemetry_ignores_stale_rows():
    now = time.time()
    rows = [_tl("flash", "fail", _iso(now - 900))]
    fails, oks = parse_telemetry(rows, 600, now)
    assert fails == {}
    assert oks == {}


def test_parse_telemetry_ignores_garbage_and_rejects_ok_false():
    now = time.time()
    rows = [
        "not json",
        _tl("flash", False, _iso(now - 10)),
        _tl("flash", "fail", _iso(now - 20)),
    ]
    fails, oks = parse_telemetry(rows, 600, now)
    assert fails["flash"] == 2
    assert oks == {}


def _iso(ts, offset="-05:00"):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)) + offset


# ── count_error_lines ──────────────────────────────────────────────

def test_count_error_lines_window_only():
    now = time.time()
    lines = [
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 3600)) + " ERROR boom",
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 60)) + " ERROR boom",
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 120)) + " CRITICAL boom",
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 30)) + " INFO fine",
    ]
    assert count_error_lines(lines, 3600, now) == 2


def test_count_error_lines_unparseable_counts_recent():
    assert count_error_lines(["garbage ERROR line"], 3600, time.time()) == 1


# ── check_cooldown ─────────────────────────────────────────────────

def test_cooldown_first_alert_allowed():
    assert check_cooldown([], "watchdog-circuit-open", 30, time.time()) is True


def test_cooldown_blocks_reenvio_dentro_de_ventana():
    now = time.time()
    entries = [{"ts": _iso(now - 600), "type": "watchdog-circuit-open"}]
    assert check_cooldown(entries, "watchdog-circuit-open", 30, now) is False


def test_cooldown_allows_despues_de_ventana():
    now = time.time()
    entries = [{"ts": _iso(now - 2000), "type": "watchdog-circuit-open"}]
    assert check_cooldown(entries, "watchdog-circuit-open", 30, now) is True


# ── agent_status ───────────────────────────────────────────────────

def test_agent_status_alive_with_fresh_health(tmp_path):
    lock = tmp_path / ".agent.lock"
    health = tmp_path / "health.json"
    health.write_text(json.dumps({"cycle": 42}), encoding="utf-8")
    lock.write_text("999999", encoding="utf-8")
    st = agent_status(lock, health, tmp_path / "stop.flag", time.time())
    assert st["alive"] is True
    assert st["cycle_no"] == 42
    assert st["stopped"] is False


def test_agent_status_dead_with_stale_health_and_dead_lock(tmp_path):
    now = time.time()
    lock = tmp_path / ".agent.lock"
    health = tmp_path / "health.json"
    health.write_text(json.dumps({"cycle": 1}), encoding="utf-8")
    # health.json con 30 min de antigüedad
    os_ts = now - 1800
    import os
    os.utime(health, (os_ts, os_ts))
    lock.write_text("1", encoding="utf-8")  # pid muerto
    with patch("monitoring.watchdog.pid_alive", return_value=False):
        st = agent_status(lock, health, tmp_path / "stop.flag", now)
    assert st["alive"] is False
    assert st["health_fresh_s"] > 900


def test_agent_status_stopped_flag(tmp_path):
    now = time.time()
    lock = tmp_path / ".agent.lock"
    health = tmp_path / "health.json"
    stop = tmp_path / "stop.flag"
    health.write_text(json.dumps({"cycle": 1}), encoding="utf-8")
    os_ts = now - 7200
    import os
    os.utime(health, (os_ts, os_ts))
    stop.write_text("", encoding="utf-8")
    st = agent_status(lock, health, stop, now)
    assert st["stopped"] is True


# ── decide_restart ─────────────────────────────────────────────────

def test_restart_when_lock_dead_and_health_stale():
    status = {"alive": False, "stopped": False, "lock_alive": False,
              "health_fresh_s": 1800}
    assert decide_restart(status, None, 0, time.time()) is True


def test_restart_no_si_lock_pid_vivo():
    # Lock vivo = agente corriendo (aunque un ciclo tarde >10 min)
    status = {"alive": False, "stopped": False, "lock_alive": True,
              "health_fresh_s": 1800}
    assert decide_restart(status, None, 0, time.time()) is False


def test_restart_si_lock_vivo_pero_congelado_2h():
    # Seguridad: lock vivo + health congelado >2h = agente colgado de verdad
    status = {"alive": False, "stopped": False, "lock_alive": True,
              "health_fresh_s": 7500}
    assert decide_restart(status, None, 0, time.time()) is True


def test_restart_no_si_stop_flag():
    status = {"alive": False, "stopped": True, "lock_alive": False,
              "health_fresh_s": 1800}
    assert decide_restart(status, None, 0, time.time()) is False


def test_restart_no_si_health_reciente():
    # Gracia post-arranque: lock aún no escrito pero health fresco
    status = {"alive": False, "stopped": False, "lock_alive": False,
              "health_fresh_s": 100}
    assert decide_restart(status, None, 0, time.time()) is False


def test_restart_no_si_cooldown_activo():
    status = {"alive": False, "stopped": False, "lock_alive": False,
              "health_fresh_s": 1800}
    now = time.time()
    assert decide_restart(status, now - 60, 0, now) is False


def test_restart_no_si_max_hora_alcanzado():
    status = {"alive": False, "stopped": False, "lock_alive": False,
              "health_fresh_s": 1800}
    now = time.time()
    assert decide_restart(status, None, 2, now) is False


def test_restart_si_lock_muerto_sin_health():
    # El lock-PID muerto es la autoridad: sin health.json no bloquea
    status = {"alive": False, "stopped": False, "lock_alive": False,
              "health_fresh_s": None}
    assert decide_restart(status, None, 0, time.time()) is True


# ── inactivity_flag ────────────────────────────────────────────────

def test_inactivity_true_con_ceros():
    assert inactivity_flag({"comments_published": 0, "posts_published": 0},
                           {"posts_published": 0}, 13.0) is True


def test_inactivity_false_si_hay_comments():
    assert inactivity_flag({"comments_published": 8, "posts_published": 0},
                           {"posts_published": 0}, 13.0) is False


def test_inactivity_false_si_posts_recientes():
    assert inactivity_flag({"comments_published": 0, "posts_published": 1},
                           {"posts_published": 0}, 13.0) is False
    assert inactivity_flag({"comments_published": 0, "posts_published": 0},
                           {"posts_published": 2}, 13.0) is False


def test_inactivity_false_antes_de_12h():
    assert inactivity_flag({"comments_published": 0, "posts_published": 0},
                           {"posts_published": 0}, 10.0) is False


def test_inactivity_false_sin_metricas_de_hoy_antes_de_24h():
    assert inactivity_flag(None, {"posts_published": 0}, 13.0) is False