# -*- coding: utf-8 -*-
"""JSONL append helpers with size-based rotation.

Telemetry logs such as ``data/dual_scores.jsonl`` and
``data/cascade_telemetry.jsonl`` grow without bound. Phase C reads them fully,
so an unbounded file eventually causes a MemoryError. These helpers cap the
active file at ``max_lines`` records: when the limit is exceeded, the current
file is rotated to ``{file_path}.archive`` and a fresh active file is started.

Readers should always read only the ACTIVE file (``file_path``), never the
``.archive`` sibling, so Phase C keeps working on a bounded window.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Union

logger = logging.getLogger("utils.jsonl_rotation")

DEFAULT_MAX_LINES = 1000


def _count_lines(file_path: Path) -> int:
    """Count non-terminal newline records in a file (fast, streaming)."""
    count = 0
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for _ in f:
            count += 1
    return count


def _rotate_log_if_needed(file_path: Union[str, Path], max_lines: int = DEFAULT_MAX_LINES) -> bool:
    """Rotate ``file_path`` to ``{file_path}.archive`` if it exceeds ``max_lines``.

    The most recent archive is overwritten (single-generation archive), so disk
    usage stays bounded. Returns True if a rotation happened, False otherwise.
    """
    path = Path(file_path)
    if not path.exists():
        return False
    try:
        line_count = _count_lines(path)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("jsonl_rotation: could not count lines in %s: %s", path, e)
        return False

    if line_count < max_lines:
        return False

    archive_path = path.with_name(path.name + ".archive")
    try:
        if archive_path.exists():
            archive_path.unlink()
        path.rename(archive_path)
        logger.info(
            "jsonl_rotation: rotated %s (%d lines ≥ %d) → %s",
            path.name, line_count, max_lines, archive_path.name,
        )
        return True
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("jsonl_rotation: failed to rotate %s: %s", path, e)
        return False


def append_jsonl(record: dict, file_path: Union[str, Path], max_lines: int = DEFAULT_MAX_LINES) -> None:
    """Append ``record`` as one JSON line, rotating the active file first if full."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_log_if_needed(path, max_lines=max_lines)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
