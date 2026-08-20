# -*- coding: utf-8 -*-
"""Tests del hold de mantenimiento (data/maintenance.flag).

Verifica que:
  - el agente solicita shutdown graceful con maintenance.flag SIN borrarlo,
    y que no arranca si el flag está presente;
  - el watchdog reporta stopped=True y decide_restart=False con el flag.
Aislado con tmp_path/monkeypatch: nunca toca data/ real.
"""

import json
import time
from pathlib import Path
from unittest.mock import patch

from monitoring.watchdog import agent_status, decide_restart


class TestAgentMaintenanceFlag:
    def _agent(self, tmp_path):
        from core.agent import COMETRiobambaAgent
        # instancia mínima sin inicialización pesada
        agent = COMETRiobambaAgent.__new__(COMETRiobambaAgent)
        agent.shutdown_requested = False
        agent.stop_flag_file = tmp_path / "stop.flag"
        agent.maintenance_flag_file = tmp_path / "maintenance.flag"
        return agent

    def test_maintenance_requests_shutdown_without_unlink(self, tmp_path):
        flag = tmp_path / "maintenance.flag"
        flag.write_text("", encoding="utf-8")
        agent = self._agent(tmp_path)
        assert agent._check_maintenance_flag() is True
        assert agent.shutdown_requested is True
        # el flag NO se borra (a diferencia de stop.flag)
        assert flag.exists() is True

    def test_maintenance_hold_blocks_startup(self, tmp_path):
        flag = tmp_path / "maintenance.flag"
        flag.write_text("", encoding="utf-8")
        agent = self._agent(tmp_path)
        assert agent._maintenance_hold_active() is True

    def test_no_maintenance_flag_normal(self, tmp_path):
        agent = self._agent(tmp_path)
        assert agent._check_maintenance_flag() is False
        assert agent._maintenance_hold_active() is False


class TestWatchdogMaintenanceFlag:
    def test_agent_status_stopped_with_maintenance_flag(self, tmp_path):
        now = time.time()
        lock = tmp_path / ".agent.lock"
        health = tmp_path / "health.json"
        health.write_text(json.dumps({"cycle": 1}), encoding="utf-8")
        os_ts = now - 7200
        import os
        os.utime(health, (os_ts, os_ts))
        lock.write_text("1", encoding="utf-8")
        maint = tmp_path / "maintenance.flag"
        maint.write_text("", encoding="utf-8")
        st = agent_status(lock, health, tmp_path / "stop.flag", now, maintenance_file=maint)
        assert st["stopped"] is True

    def test_decide_restart_false_with_maintenance_flag(self, tmp_path):
        now = time.time()
        maint = tmp_path / "maintenance.flag"
        maint.write_text("", encoding="utf-8")
        health = tmp_path / "health.json"
        health.write_text(json.dumps({"cycle": 1}), encoding="utf-8")
        lock = tmp_path / ".agent.lock"
        lock.write_text("1", encoding="utf-8")
        os_ts = now - 7200
        import os
        os.utime(health, (os_ts, os_ts))
        st = agent_status(lock, health, tmp_path / "stop.flag", now, maintenance_file=maint)
        # agente "muerto" pero con maintenance flag → no reinicia
        assert st["alive"] is False
        assert decide_restart(st, last_restart_ts=None, restarts_1h=0, now=now) is False

    def test_agent_status_not_stopped_without_flag(self, tmp_path):
        now = time.time()
        lock = tmp_path / ".agent.lock"
        health = tmp_path / "health.json"
        health.write_text(json.dumps({"cycle": 1}), encoding="utf-8")
        lock.write_text("1", encoding="utf-8")
        os_ts = now - 7200
        import os
        os.utime(health, (os_ts, os_ts))
        maint = tmp_path / "no_maint.flag"
        with patch("monitoring.watchdog.pid_alive", return_value=False):
            st = agent_status(lock, health, tmp_path / "stop.flag", now, maintenance_file=maint)
        assert st["stopped"] is False