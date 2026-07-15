from __future__ import annotations

import json
import re
from collections import deque
from datetime import datetime
from pathlib import Path
import sys

import anyio
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
LOG_PATH = PROJECT_ROOT / "logs" / "agent.log"

server = Server("comet-riobamba-lowlevel")


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


def _json_text(payload: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]


@server.list_tools()
async def handle_list_tools():
    return [
        Tool(
            name="agent_status",
            description="Return a lightweight snapshot of agent state from data files.",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        Tool(
            name="provider_health",
            description="Return provider/model cascade health by instantiating the local health check logic.",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        Tool(
            name="recent_log_summary",
            description="Summarize recent activity from logs/agent.log.",
            inputSchema={
                "type": "object",
                "properties": {
                    "lines": {"type": "integer", "minimum": 100, "maximum": 5000, "default": 800}
                },
                "additionalProperties": False,
            },
        ),
        Tool(
            name="outbox_status",
            description="Inspect outbox-related files under data/.",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        Tool(
            name="reply_guard_state",
            description="Inspect persisted reply guard / dedup state relevant to feed behavior.",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        Tool(
            name="recent_activity",
            description="Return a compact recent-activity snapshot from logs and data.",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None = None):
    args = arguments or {}

    if name == "agent_status":
        payload = {
            "timestamp": datetime.now().isoformat(),
            "agent_status": _read_json(DATA_DIR / "agent_status.json", {}),
            "phase_a_last_post": _read_json(DATA_DIR / "phase_a_last_post.json", {}),
        }
        return _json_text(payload)

    if name == "provider_health":
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

            payload = {
                "timestamp": datetime.now().isoformat(),
                "providers": providers,
                "error": error,
            }
        except Exception as e:
            payload = {
                "timestamp": datetime.now().isoformat(),
                "providers": [],
                "error": f"No se pudo cargar COMETRiobambaAgent: {e}",
            }
        return _json_text(payload)

    if name == "recent_log_summary":
        lines = int(args.get("lines", 800))
        parser = LogParser(LOG_PATH)
        metrics = parser.parse_recent(lines=lines)

        cycles = list(metrics["cycles"])
        posts = list(metrics["posts"])
        comments = list(metrics["comments"])
        errors = list(metrics["errors"])
        feedback = list(metrics["toolfeedback"])

        avg_cycle = round(sum(c["duration_s"] for c in cycles) / len(cycles), 2) if cycles else 0.0
        avg_conf = round(sum(f["confidence"] for f in feedback) / len(feedback), 3) if feedback else None

        payload = {
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
        return _json_text(payload)

    if name == "outbox_status":
        failed_posts = DATA_DIR / "failed_posts_outbox.jsonl"
        failed_comments = DATA_DIR / "failed_comments_outbox.jsonl"
        payload = {
            "timestamp": datetime.now().isoformat(),
            "failed_posts_outbox_exists": failed_posts.exists(),
            "failed_posts_count": _read_jsonl_count(failed_posts),
            "failed_comments_outbox_exists": failed_comments.exists(),
            "failed_comments_count": _read_jsonl_count(failed_comments),
        }
        return _json_text(payload)

    if name == "reply_guard_state":
        post_history_guard = _read_json(DATA_DIR / "post_history_guard.json", {})
        followed_agents = _read_json(DATA_DIR / "followed_agents.json", {})
        followed_agent_names = _read_json(DATA_DIR / "followed_agent_names.json", {})

        tracked_posts = len(post_history_guard) if isinstance(post_history_guard, dict) else 0

        payload = {
            "timestamp": datetime.now().isoformat(),
            "post_history_guard_entries": tracked_posts,
            "post_history_guard_sample": list(post_history_guard.keys())[:20] if isinstance(post_history_guard, dict) else [],
            "followed_agents_count": len(followed_agents) if isinstance(followed_agents, (list, dict)) else None,
            "followed_agent_names_count": len(followed_agent_names) if isinstance(followed_agent_names, (list, dict)) else None,
        }
        return _json_text(payload)

    if name == "recent_activity":
        parser = LogParser(LOG_PATH)
        metrics = parser.parse_recent(lines=400)
        payload = {
            "timestamp": datetime.now().isoformat(),
            "recent_cycles": list(metrics["cycles"])[-5:],
            "recent_posts": list(metrics["posts"])[-5:],
            "recent_comments": list(metrics["comments"])[-10:],
            "recent_toolfeedback": list(metrics["toolfeedback"])[-10:],
            "recent_errors": list(metrics["errors"])[-10:],
        }
        return _json_text(payload)

    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
