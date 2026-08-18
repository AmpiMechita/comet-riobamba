# -*- coding: utf-8 -*-
"""Tests de la supervision del watchdog (fix WinError 87, 18/08/2026).

os.kill(pid, 0) en Windows puede lanzar OSError [WinError 87] con el PID
vivo; antes eso se trataba como 'proceso muerto' y el agente relanzaba el
watchdog cada 300s. Ahora hay fallback a tasklist y fail-safe a 'vivo'.
"""

import subprocess
from unittest.mock import patch

import pytest

from core.agent import COMETRiobambaAgent


def test_pid_alive_normal():
    with patch("core.agent.os.kill", return_value=None) as mk:
        assert COMETRiobambaAgent._pid_alive(1234) is True
    mk.assert_called_once_with(1234, 0)


def test_pid_alive_process_lookup_error():
    with patch("core.agent.os.kill", side_effect=ProcessLookupError(3, "no existe")):
        assert COMETRiobambaAgent._pid_alive(999999) is False


def test_pid_alive_permission_error_is_alive():
    with patch("core.agent.os.kill", side_effect=PermissionError(5, "acceso denegado")):
        assert COMETRiobambaAgent._pid_alive(1234) is True


def test_pid_alive_winerror87_falls_back_to_tasklist_found():
    """WinError 87 (el caso real Windows): tasklist confirma que vive."""
    with patch("core.agent.os.kill", side_effect=OSError(87, "parametro invalido")):
        with patch(
            "core.agent.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=b"python.exe 1234 Console 1 2.345 MB",
                stderr=b"",
            ),
        ) as mr:
            assert COMETRiobambaAgent._pid_alive(1234) is True
    assert "PID eq 1234" in " ".join(mr.call_args.args[0])


def test_pid_alive_winerror87_tasklist_not_found_is_dead():
    with patch("core.agent.os.kill", side_effect=OSError(87, "parametro invalido")):
        with patch(
            "core.agent.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=b"Informacion: no hay tareas", stderr=b""
            ),
        ):
            assert COMETRiobambaAgent._pid_alive(1234) is False


def test_pid_alive_ambiguous_failsafe_is_alive():
    """Si ni tasklist decide (error raro), asumir vivo para no relanzar."""
    with patch("core.agent.os.kill", side_effect=OSError(87, "parametro invalido")):
        with patch("core.agent.subprocess.run", side_effect=RuntimeError("boom")):
            assert COMETRiobambaAgent._pid_alive(1234) is True


def test_pid_alive_none_or_zero():
    assert COMETRiobambaAgent._pid_alive(None) is False
    assert COMETRiobambaAgent._pid_alive(0) is False