from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
LOG_FALLBACK = PROJECT_ROOT / "logs" / "agent.log"


def _resolve_log_path() -> Path:
    candidates = sorted(PROJECT_ROOT.glob("run-*-real.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    return LOG_FALLBACK


if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


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


def cmd_agent_status(_args):
    from core.state_manager import AgentState

    state = AgentState()
    payload = {
        "timestamp": datetime.now().isoformat(),
        "live_state": {
            "cycle_count": state.cycle_count,
            "posts_today": state.posts_today,
            "comments_today": state.comments_today,
            "consecutive_failures": state.consecutive_failures,
            "last_post_date": state.last_post_date,
            "last_value_review": state.last_value_review,
        },
        "phase_a_last_post": _read_json(DATA_DIR / "phase_a_last_post.json", {}),
        "phase_a_pause_state": _read_json(DATA_DIR / "phase_a_pause_state.json", {}),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_provider_health(_args):
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
        if not providers and error is None:
            payload["note"] = "No provider health has been recorded yet in this fresh model_cascade instance."
    except Exception as e:
        payload = {
            "timestamp": datetime.now().isoformat(),
            "providers": [],
            "error": f"No se pudo cargar COMETRiobambaAgent: {e}",
        }

    print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_recent_log_summary(args):
    log_path = _resolve_log_path()
    parser = LogParser(log_path)
    metrics = parser.parse_recent(lines=args.lines)

    cycles = list(metrics["cycles"])
    posts = list(metrics["posts"])
    comments = list(metrics["comments"])
    errors = list(metrics["errors"])
    feedback = list(metrics["toolfeedback"])

    avg_cycle = round(sum(c["duration_s"] for c in cycles) / len(cycles), 2) if cycles else 0.0
    avg_conf = round(sum(f["confidence"] for f in feedback) / len(feedback), 3) if feedback else None

    payload = {
        "timestamp": datetime.now().isoformat(),
        "log_path": str(log_path),
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
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_outbox_status(_args):
    failed_posts = DATA_DIR / "failed_posts_outbox.jsonl"
    failed_comments = DATA_DIR / "failed_comments_outbox.jsonl"

    payload = {
        "timestamp": datetime.now().isoformat(),
        "failed_posts_outbox_exists": failed_posts.exists(),
        "failed_posts_count": _read_jsonl_count(failed_posts),
        "failed_comments_outbox_exists": failed_comments.exists(),
        "failed_comments_count": _read_jsonl_count(failed_comments),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_reply_guard_state(_args):
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
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_state_debug(_args):
    from core.state_manager import AgentState
    from services.persistence import DB_PATH

    log_path = _resolve_log_path()
    state = AgentState()

    def _count_log_events(pattern: str) -> int:
        if not log_path.exists():
            return 0
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            return len(re.findall(pattern, text))
        except Exception:
            return 0

    def _last_log_match(pattern: str) -> str | None:
        if not log_path.exists():
            return None
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            matches = re.findall(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?" + pattern, text)
            return matches[-1] if matches else None
        except Exception:
            return None

    db_path = Path(DB_PATH)
    db_stat = None
    if db_path.exists():
        try:
            mtime = datetime.fromtimestamp(db_path.stat().st_mtime).isoformat()
            db_stat = {"path": str(db_path), "size_bytes": db_path.stat().st_size, "mtime": mtime}
        except Exception:
            db_stat = {"path": str(db_path), "error": "could not stat"}

    log_stat = None
    if log_path.exists():
        try:
            mtime = datetime.fromtimestamp(log_path.stat().st_mtime).isoformat()
            log_stat = {"path": str(log_path), "size_bytes": log_path.stat().st_size, "mtime": mtime}
        except Exception:
            log_stat = {"path": str(log_path)}

    post_history_guard = _read_json(DATA_DIR / "post_history_guard.json", {})

    log_events = {
        "state_saved": _count_log_events(r"state_saved|state saved"),
        "cycle_start": _count_log_events(r"CICLO #\d+ INICIADO"),
        "cycle_end": _count_log_events(r"CICLO #\d+ FINALIZADO"),
        "phase_a_publish_success": _count_log_events(r"phase_a_publish_success|Fase A.*post.*publicado"),
        "phase_b_reply_success": _count_log_events(r"phase_b_reply_success|replied to comment"),
    }
    last_cycle = _last_log_match(r"CICLO #(\d+) FINALIZADO")
    last_state_saved = _last_log_match(r"state_saved|guardando estado")

    mismatches = []
    if state.posts_today > 0 and log_events["cycle_start"] == 0:
        mismatches.append("posts_today > 0 but no cycle_start found in logs")
    if state.posts_today > 0 and log_events["phase_a_publish_success"] == 0:
        mismatches.append("posts_today > 0 but no phase_a_publish_success found in logs")
    if state.comments_today > 0 and log_events["phase_b_reply_success"] == 0:
        mismatches.append("comments_today > 0 but no phase_b_reply_success found in logs")

    payload = {
        "timestamp": datetime.now().isoformat(),
        "log_path": str(log_path),
        "live_state": {
            "cycle_count": state.cycle_count,
            "posts_today": state.posts_today,
            "comments_today": state.comments_today,
            "consecutive_failures": state.consecutive_failures,
            "last_post_date": state.last_post_date,
            "last_value_review": state.last_value_review,
        },
        "persistence": {
            "database": db_stat,
            "log": log_stat,
        },
        "secondary_files": {
            "phase_a_last_post": _read_json(DATA_DIR / "phase_a_last_post.json", {}),
            "phase_a_pause_state": _read_json(DATA_DIR / "phase_a_pause_state.json", {}),
        },
        "post_history_guard": {
            "entry_count": len(post_history_guard) if isinstance(post_history_guard, dict) else 0,
            "sample_keys": list(post_history_guard.keys())[:10] if isinstance(post_history_guard, dict) else [],
        },
        "log_evidence": {
            "event_counts": log_events,
            "last_cycle_end": last_cycle,
            "last_state_saved": last_state_saved,
        },
        "mismatches": mismatches,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_recent_activity(args):
    log_path = _resolve_log_path()
    parser = LogParser(log_path)
    metrics = parser.parse_recent(lines=args.lines)

    payload = {
        "timestamp": datetime.now().isoformat(),
        "log_path": str(log_path),
        "recent_cycles": list(metrics["cycles"])[-5:],
        "recent_posts": list(metrics["posts"])[-5:],
        "recent_comments": list(metrics["comments"])[-10:],
        "recent_toolfeedback": list(metrics["toolfeedback"])[-10:],
        "recent_errors": list(metrics["errors"])[-10:],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def build_parser():
    parser = argparse.ArgumentParser(description="Inspect COMET-RIOBAMBA local state and health")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("agent-status", help="Show agent status from data files")
    p.set_defaults(func=cmd_agent_status)

    p = sub.add_parser("provider-health", help="Show model/provider health")
    p.set_defaults(func=cmd_provider_health)

    p = sub.add_parser("recent-log-summary", help="Summarize recent logs")
    p.add_argument("--lines", type=int, default=800)
    p.set_defaults(func=cmd_recent_log_summary)

    p = sub.add_parser("outbox-status", help="Inspect outbox files")
    p.set_defaults(func=cmd_outbox_status)

    p = sub.add_parser("reply-guard-state", help="Inspect reply guard state")
    p.set_defaults(func=cmd_reply_guard_state)

    p = sub.add_parser("state-debug", help="Diagnose mismatches between persisted state and log evidence")
    p.set_defaults(func=cmd_state_debug)

    p = sub.add_parser("recent-activity", help="Show recent posts/comments/toolfeedback/errors")
    p.add_argument("--lines", type=int, default=400)
    p.set_defaults(func=cmd_recent_activity)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
