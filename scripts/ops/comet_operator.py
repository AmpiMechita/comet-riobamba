#!/usr/bin/env python
"""Read-only reproducible operator for COMET-RIOBAMBA.

This CLI reads repository/service guards and can fail closed when supplied
expectations do not match. It does not write repository, service, database,
network, or external state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SERVICE_DEFAULT = "CometRiobamba"
PROTECTED_SCORING = Path("phases/phase_b/scoring.py")


class OperatorError(RuntimeError):
    pass


def _run(
    args: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> str:
    proc = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="strict",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit={proc.returncode}"
        raise OperatorError(f"command failed: {args[0]}: {detail}")
    return proc.stdout.rstrip("\r\n")


def _git(root: Path, *args: str) -> str:
    return _run(["git", *args], cwd=root)


def _git_status(root: Path) -> str:
    return _git(root, "status", "--porcelain=v1", "--untracked-files=all")


def _summarize_git_status(raw_status: str) -> dict[str, Any]:
    lines = [line for line in raw_status.splitlines() if line]
    tracked = [line for line in lines if not line.startswith("??")]
    return {
        "tracked_changes": len(tracked),
        "staged_changes": sum(line[0] not in " ?" for line in tracked),
        "unstaged_changes": sum(line[1] not in " ?" for line in tracked),
        "untracked": sum(line.startswith("??") for line in lines),
        "paths": [line[3:] if len(line) >= 4 else line for line in lines],
    }

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _service_snapshot(root: Path, service_name: str) -> dict[str, Any]:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        raise OperatorError("PowerShell executable not found")
    code = (
        "$serviceName = $env:COMET_OPERATOR_SERVICE_NAME;"
        "$s=Get-CimInstance Win32_Service | Where-Object { $_.Name -eq $serviceName };"
        "if($null -eq $s){throw 'SERVICE_NOT_FOUND'};"
        "$s|Select-Object Name,State,ProcessId,StartMode|ConvertTo-Json -Compress"
    )
    env = os.environ.copy()
    env["COMET_OPERATOR_SERVICE_NAME"] = service_name
    raw = _run(
        [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", code],
        cwd=root,
        env=env,
    )
    data = json.loads(raw)
    return {
        "name": str(data["Name"]),
        "status": str(data["State"]),
        "pid": int(data["ProcessId"]),
        "start_mode": str(data["StartMode"]),
    }


def snapshot(root: Path, service_name: str) -> dict[str, Any]:
    git_root = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    if git_root != root.resolve():
        raise OperatorError(
            f"repo root mismatch: expected={root.resolve()} actual={git_root}"
        )

    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "branch", "--show-current")
    detached = not bool(branch)
    raw_status = _git_status(root)
    git_summary = _summarize_git_status(raw_status)

    scoring = root / PROTECTED_SCORING
    if not scoring.is_file():
        raise OperatorError(
            f"protected file missing: {PROTECTED_SCORING.as_posix()}"
        )

    return {
        "repo_root": str(git_root),
        "head": head,
        "branch": branch,
        "detached": detached,
        "git": git_summary,
        "service": _service_snapshot(root, service_name),
        "protected": {
            PROTECTED_SCORING.as_posix(): {"sha256": _sha256(scoring)}
        },
    }


def evaluate(snap: dict[str, Any], args: argparse.Namespace) -> list[str]:
    failures: list[str] = []

    def expect(label: str, actual: Any, wanted: Any) -> None:
        if wanted is not None and actual != wanted:
            failures.append(f"{label}: expected={wanted!r} actual={actual!r}")

    expect("head", snap["head"], args.expect_head)
    expect("branch", snap["branch"], args.expect_branch)
    expect(
        "git.tracked_changes",
        snap["git"]["tracked_changes"],
        args.expect_tracked_changes,
    )
    expect("git.untracked", snap["git"]["untracked"], args.expect_untracked)
    expect(
        "git.staged_changes",
        snap["git"]["staged_changes"],
        args.expect_staged_changes,
    )
    expect(
        "git.unstaged_changes",
        snap["git"]["unstaged_changes"],
        args.expect_unstaged_changes,
    )
    expect(
        "service.start_mode",
        snap["service"]["start_mode"],
        args.expect_service_start_mode,
    )

    scoring = snap["protected"][PROTECTED_SCORING.as_posix()]["sha256"]
    wanted_scoring = (
        args.expect_scoring_sha256.upper()
        if args.expect_scoring_sha256
        else None
    )
    expect("protected.scoring.sha256", scoring, wanted_scoring)

    if args.require_service_stopped:
        if (
            snap["service"]["status"] != "Stopped"
            or snap["service"]["pid"] != 0
            or snap["service"]["start_mode"] != "Manual"
        ):
            failures.append(
                "service: expected status='Stopped' pid=0 start_mode='Manual' "
                f"actual status={snap['service']['status']!r} "
                f"pid={snap['service']['pid']!r} "
                f"start_mode={snap['service']['start_mode']!r}"
            )

    return failures


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only COMET-RIOBAMBA operator snapshot and guard checker."
        )
    )
    parser.add_argument("--service-name", default=SERVICE_DEFAULT)
    parser.add_argument("--expect-head")
    parser.add_argument("--expect-branch")
    parser.add_argument("--expect-tracked-changes", type=int)
    parser.add_argument("--expect-staged-changes", type=int)
    parser.add_argument("--expect-unstaged-changes", type=int)
    parser.add_argument("--expect-untracked", type=int)
    parser.add_argument("--expect-service-start-mode")
    parser.add_argument("--expect-scoring-sha256")
    parser.add_argument("--require-service-stopped", action="store_true")
    parser.add_argument("--compact", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parents[2]

    try:
        snap = snapshot(root, args.service_name)
        failures = evaluate(snap, args)
    except (OperatorError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 3

    result = {"ok": not failures, "failures": failures, "snapshot": snap}
    if args.compact:
        print(
            json.dumps(
                result, ensure_ascii=False, separators=(",", ":")
            )
        )
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
