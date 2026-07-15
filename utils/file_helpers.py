# -*- coding: utf-8 -*-
"""Shared file-system utilities used across the agent."""

import json
import os
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, data: Any, **json_kwargs) -> None:
    """Write JSON atomically: temp file + os.replace().

    Guarantees the destination file is never left in a truncated/corrupt
    state even if the process is interrupted mid-write.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, **json_kwargs)
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
