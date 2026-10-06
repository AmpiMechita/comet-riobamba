#!/usr/bin/env python
"""Read-only Python syntax/warning lint for COMET-RIOBAMBA.

Enumerates Git-visible Python files (tracked + untracked, excluding ignored files),
parses them without importing project modules, captures SyntaxWarning instances,
and emits JSON. It does not write repository, service, database, network, or
external state.
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import tokenize
import warnings
from pathlib import Path
from typing import Any


class LintError(RuntimeError):
    pass


def _git_visible_python(root: Path) -> list[str]:
    proc = subprocess.run(
        [
            "git",
            "ls-files",
            "-c",
            "-o",
            "--exclude-standard",
            "--",
            "*.py",
        ],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="strict",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.rstrip("\r\n") or proc.stdout.rstrip("\r\n")
        raise LintError(f"git ls-files failed: {detail}")
    return sorted(
        {
            path
            for path in proc.stdout.splitlines()
            if path and (root / path).is_file()
        }
    )


def lint_file(root: Path, rel: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warning_rows: list[dict[str, Any]] = []
    path = root / rel

    try:
        with tokenize.open(path) as fh:
            source = fh.read()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SyntaxWarning)
            ast.parse(source, filename=rel)
        for item in caught:
            if issubclass(item.category, SyntaxWarning):
                warning_rows.append(
                    {
                        "path": rel,
                        "line": item.lineno,
                        "category": item.category.__name__,
                        "message": str(item.message),
                    }
                )
    except (SyntaxError, UnicodeError, OSError) as exc:
        errors.append(
            {
                "path": rel,
                "line": getattr(exc, "lineno", None),
                "offset": getattr(exc, "offset", None),
                "error": getattr(exc, "msg", str(exc)),
            }
        )

    return errors, warning_rows


def run(root: Path) -> dict[str, Any]:
    files = _git_visible_python(root)
    errors: list[dict[str, Any]] = []
    warning_rows: list[dict[str, Any]] = []

    for rel in files:
        file_errors, file_warnings = lint_file(root, rel)
        errors.extend(file_errors)
        warning_rows.extend(file_warnings)

    return {
        "files": len(files),
        "parsed_ok": len(files) - len({row["path"] for row in errors}),
        "syntax_errors": errors,
        "syntax_warnings": warning_rows,
        "ok": not errors and not warning_rows,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only AST/SyntaxWarning lint for Git-visible Python files."
    )
    parser.add_argument("--compact", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parents[2]

    try:
        result = run(root)
    except (LintError, OSError, UnicodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 3

    if args.compact:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
