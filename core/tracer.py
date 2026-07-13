"""Append-only local span-level tracing for Phase B decisions."""
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("core.tracer")

TRACES_DIR = Path("traces")


def _trace_path() -> Path:
    today = datetime.now().strftime("%Y%m%d")
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    return TRACES_DIR / f"phase_b_{today}.jsonl"


class Span:
    """Lightweight tracing span. Usage: with Span('phase_b_reply', post_id=..., comment_id=...) as span: ... span.set('outcome', 'published')"""
    
    def __init__(self, name: str, **attrs):
        self.name = name
        self.attrs = attrs
        self.start = time.monotonic()
        self._extra: Dict[str, Any] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed_ms = int((time.monotonic() - self.start) * 1000)
        record = {"span": self.name, "timestamp": datetime.now().isoformat(), "latency_ms": elapsed_ms, **self.attrs, **self._extra}
        if exc_type:
            record["error"] = f"{exc_type.__name__}: {exc_val}" if exc_val else exc_type.__name__
        try:
            path = _trace_path()
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.debug("Tracer: failed to write span: %s", e)

    def set(self, key: str, value: Any) -> None:
        self._extra[key] = value
