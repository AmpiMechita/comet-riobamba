from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque
import re
import sys

from mcp.server.fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
LOG_PATH = PROJECT_ROOT / "logs" / "agent.log"

mcp = FastMCP("comet-riobamba")


def _read_json(path: Path, default=None):
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _read_jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


class LogParser:
    PATTERNS = {
        "cycle_end": r"CICLO #\d+ FINALIZADO(?: en| in) ([\d.]+)s",
        "post_published": r"MoltbookAPIClient\.create_post: creado post id=.* status=(\d+)",
        "comment_published": r"MoltbookAPIClient\.create_comment: creado comment id=.* status=(\d+)",
        "toolfeedback": r"ToolFeedback (\w+) outcome=(\w+) confidence=([\d.]+).*status=(\d+)",
        "waiting_next": r"Esperando (\d+)s hasta",
    }

    def __init__(self, log_path: Path):
        self.log_path = log_path

    def parse_recent(self, lines: int = 800):
        metrics = {
            "cycles": deque(maxlen=100),
            "posts": deque(maxlen=100),
            "comments": deque(maxlen=200),
            "toolfeedback": deque(maxlen=200),
            "errors": deque(maxlen=100),
            "last_update": None,
        }

        if not self.log_path.exists():
            return metrics

        with self.log_path.open("r", encoding="utf-8", errors="replace") as f:
            recent = f.readlines()[-lines:]

        for line in recent:
            ts_match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            ts = None
            if ts_match:
                try:
                    ts = datetime.strptime(ts_match.group(1), "%Y-%m-%d %H:%M:%S")
                except Exception:
                    ts = None

            if "ERROR" in line:
                metrics["errors"].append({
                    "timestamp": ts.isoformat() if ts else None,
                    "message": line.strip()[:300],
                })

            m = re.search(self.PATTERNS["cycle_end"], line)
            if m:
                metrics["cycles"].append({
                    "timestamp": ts.isoformat() if ts else None,
                    "duration_s": float(m.group(1)),
                })
                continue

            m = re.search(self.PATTERNS["post_published"], line)
            if m:
                metrics["posts"].append({
                    "timestamp": ts.isoformat() if ts else None,
                    "status": int(m.group(1)),
                })
                continue

            m = re.search(self.PATTERNS["comment_published"], line)
            if m:
                metrics["comments"].append({
                    "timestamp": ts.isoformat() if ts else None,
                    "status": int(m.group(1)),
                })
                continue

            m = re.search(self.PATTERNS["toolfeedback"], line)
            if m:
                metrics["toolfeedback"].append({
                    "timestamp": ts.isoformat() if ts else None,
                    "operation": m.group(1),
                    "outcome": m.group(2),
                    "confidence": float(m.group(3)),
                    "status": int(m.group(4)),
                })
                continue

        metrics["last_update"] = datetime.now().isoformat()
        return metrics


@mcp.tool()
def agent_status() -> dict:
    """Return a lightweight snapshot of agent state from data files."""
    state = _read_json(DATA_DIR / "agent_status.json", {})
    phase_a_last = _read_json(DATA_DIR / "phase_a_last_post.json", {})
    return {
        "timestamp": datetime.now().isoformat(),
        "agent_status": state,
        "phase_a_last_post": phase_a_last,
    }


@mcp.tool()
def provider_health() -> dict:
    """Return provider/model cascade health by instantiating the local health check logic."""
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from core.agent import COMETRiobambaAgent

        agent = COMETRiobambaAgent()
        cascade = getattr(agent, "model_cascade", None)
        providers = []
        error = None

        if cascade and hasattr(cascade, "get_provider_health"):
            try:
                providers = cascade.get_provider_health()
            except Exception as e:
                error = f"Error obteniendo health de providers: {e}"
        else:
            error = "model_cascade no disponible o sin get_provider_health()"

        return {
            "timestamp": datetime.now().isoformat(),
            "providers": providers,
            "error": error,
        }
    except Exception as e:
        return {
            "timestamp": datetime.now().isoformat(),
            "providers": [],
            "error": f"No se pudo cargar COMETRiobambaAgent: {e}",
        }


@mcp.tool()
def recent_log_summary(lines: int = 800) -> dict:
    """Summarize recent activity from logs/agent.log."""
    parser = LogParser(LOG_PATH)
    metrics = parser.parse_recent(lines=lines)

    cycles = list(metrics["cycles"])
    posts = list(metrics["posts"])
    comments = list(metrics["comments"])
    errors = list(metrics["errors"])
    feedback = list(metrics["toolfeedback"])

    avg_cycle = round(sum(c["duration_s"] for c in cycles) / len(cycles), 2) if cycles else 0.0
    avg_conf = round(sum(f["confidence"] for f in feedback) / len(feedback), 3) if feedback else None

    return {
        "timestamp": datetime.now().isoformat(),
        "log_path": str(LOG_PATH),
        "cycles_count": len(cycles),
        "avg_cycle_duration_s": avg_cycle,
        "posts_published": len(posts),
        "comments_published": len(comments),
        "toolfeedback_count": len(feedback),
        "avg_toolfeedback_confidence": avg_conf,
        "recent_errors_count": len(errors),
        "recent_errors": errors[-10:],
        "recent_toolfeedback": feedback[-10:],
        "last_update": metrics["last_update"],
    }


@mcp.tool()
def outbox_status() -> dict:
    """Inspect outbox-related files under data/."""
    failed_posts = DATA_DIR / "failed_posts_outbox.jsonl"
    failed_comments = DATA_DIR / "failed_comments_outbox.jsonl"

    return {
        "timestamp": datetime.now().isoformat(),
        "failed_posts_outbox_exists": failed_posts.exists(),
        "failed_posts_count": _read_jsonl_count(failed_posts),
        "failed_comments_outbox_exists": failed_comments.exists(),
        "failed_comments_count": _read_jsonl_count(failed_comments),
    }


@mcp.tool()
def reply_guard_state() -> dict:
    """Inspect persisted reply guard / dedup state relevant to feed behavior."""
    post_history_guard = _read_json(DATA_DIR / "post_history_guard.json", {})
    followed_agents = _read_json(DATA_DIR / "followed_agents.json", {})
    followed_agent_names = _read_json(DATA_DIR / "followed_agent_names.json", {})

    tracked_posts = 0
    if isinstance(post_history_guard, dict):
        tracked_posts = len(post_history_guard)

    return {
        "timestamp": datetime.now().isoformat(),
        "post_history_guard_entries": tracked_posts,
        "post_history_guard_sample": list(post_history_guard.keys())[:20] if isinstance(post_history_guard, dict) else [],
        "followed_agents_count": len(followed_agents) if isinstance(followed_agents, (list, dict)) else None,
        "followed_agent_names_count": len(followed_agent_names) if isinstance(followed_agent_names, (list, dict)) else None,
    }


@mcp.tool()
def recent_activity() -> dict:
    """Return a compact recent-activity snapshot from logs and data."""
    parser = LogParser(LOG_PATH)
    metrics = parser.parse_recent(lines=400)

    return {
        "timestamp": datetime.now().isoformat(),
        "recent_cycles": list(metrics["cycles"])[-5:],
        "recent_posts": list(metrics["posts"])[-5:],
        "recent_comments": list(metrics["comments"])[-10:],
        "recent_toolfeedback": list(metrics["toolfeedback"])[-10:],
        "recent_errors": list(metrics["errors"])[-10:],
    }


if __name__ == "__main__":
    try:
        mcp.run(transport="stdio")
    except Exception as e:
        import traceback
        print("MCP server crashed:", repr(e), file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        raise

