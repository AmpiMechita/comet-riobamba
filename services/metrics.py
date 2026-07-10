import logging
from collections import Counter
from threading import Lock

logger = logging.getLogger(__name__)
_lock = Lock()
_counters = Counter()

def incr(name: str, value: int = 1, **tags):
    key = name
    if tags:
        parts = [f"{k}={tags[k]}" for k in sorted(tags)]
        key = f"{name}|{'|'.join(parts)}"
    with _lock:
        _counters[key] += value

def set_value(name: str, value, **tags):
    key = name
    if tags:
        parts = [f"{k}={tags[k]}" for k in sorted(tags)]
        key = f"{name}|{'|'.join(parts)}"
    with _lock:
        _counters[key] = value

def snapshot():
    with _lock:
        return dict(_counters)

def log_metrics_snapshot(prefix: str = "METRICS"):
    data = snapshot()
    ordered = " ".join(f"{k}={data[k]}" for k in sorted(data))
    logger.info(f"{prefix} {ordered}")