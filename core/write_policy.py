from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Literal, Dict, Any, List
import hashlib
import json
import os
import re
from pathlib import Path
from time import time as _time
from difflib import SequenceMatcher

from config.agent_policy import POLICY

WriteType = Literal["post", "reply"]


@dataclass
class TokenBucket:
    """Simple token bucket rate limiter — one token, refills after interval."""
    interval_seconds: float
    _last_write: float = field(default=0.0, init=False, repr=False)

    def can_write(self) -> bool:
        return (_time() - self._last_write) >= self.interval_seconds

    def seconds_until_ready(self) -> float:
        elapsed = _time() - self._last_write
        remaining = self.interval_seconds - elapsed
        return max(0.0, remaining)

    def consume(self) -> None:
        self._last_write = _time()


@dataclass
class WriteRequest:
    write_type: WriteType
    title: Optional[str]
    body: str
    submolt: str
    thread_id: Optional[str]
    topic_key: Optional[str]
    now: datetime
    phase: str


@dataclass
class WriteDecision:
    allowed: bool
    reason: str
    idempotency_key: Optional[str] = None


class WritePolicyEngine:
    def __init__(self, behavior_cfg, base_dir: Path):
        self.cfg = behavior_cfg
        self.base_dir = base_dir
        self.log_path = base_dir / "data" / "write_log.jsonl"
        self.topic_index_path = base_dir / "data" / "topic_index.json"
        self.kill_switch_path = base_dir / "data" / "kill_switch_state.json"
        # Separate rate limiters for posts vs comments
        self._post_bucket = TokenBucket(
            interval_seconds=float(os.getenv("POST_RATE_LIMIT_SECONDS", "300"))
        )
        self._comment_bucket = TokenBucket(
            interval_seconds=float(os.getenv("COMMENT_RATE_LIMIT_SECONDS", "120"))
        )

    def _cfg_get(self, key: str, default=None):
        if isinstance(self.cfg, dict):
            return self.cfg.get(key, default)
        return getattr(self.cfg, key, default)

    def _cfg_bool(self, key: str, default: bool = False) -> bool:
        return bool(self._cfg_get(key, default))

    def _cfg_int(self, key: str, default: int) -> int:
        try:
            return int(self._cfg_get(key, default))
        except Exception:
            return default

    def _cfg_float(self, key: str, default: float) -> float:
        try:
            return float(self._cfg_get(key, default))
        except Exception:
            return default

    def _cfg_list(self, key: str, default: List[str]) -> List[str]:
        value = self._cfg_get(key, default)
        return value if isinstance(value, list) else default

    def is_kill_switch_on(self) -> bool:
        if not self._cfg_bool("enable_kill_switch", False):
            return False
        if not self.kill_switch_path.exists():
            return False
        try:
            data = json.loads(self.kill_switch_path.read_text(encoding="utf-8"))
            return bool(data.get("enabled", False))
        except Exception:
            return False

    def _load_recent_writes(self) -> List[Dict[str, Any]]:
        if not self.log_path.exists():
            return []
        items = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
        return items

    def _hash_content(self, title: Optional[str], body: str) -> str:
        h = hashlib.sha256()
        h.update((title or "").encode("utf-8"))
        h.update(b"\n")
        h.update((body or "").encode("utf-8"))
        return "sha256:" + h.hexdigest()

    def _normalize_text(self, text: str) -> str:
        text = (text or "").lower()
        text = text.replace("\u00a0", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _topic_recently_used(self, topic_key: Optional[str], now: datetime) -> bool:
        if not topic_key:
            return False
        if not self.topic_index_path.exists():
            return False
        try:
            data = json.loads(self.topic_index_path.read_text(encoding="utf-8"))
        except Exception:
            return False

        last_ts = data.get(topic_key)
        if not last_ts:
            return False

        try:
            last_dt = datetime.fromisoformat(last_ts)
        except Exception:
            return False

        hours = self._cfg_int("topic_cooldown_hours", 24)
        return now - last_dt < timedelta(hours=hours)

    def _is_similar_to_recent(self, body: str, recent: List[Dict[str, Any]]) -> bool:
        threshold = self._cfg_float("similarity_threshold", 0.85)
        recent_window = self._cfg_int("recent_similarity_window", 30)

        candidates = [item for item in recent if item.get("type") == "post"][-recent_window:]
        normalized_body = self._normalize_text(body)

        for item in candidates:
            other = self._normalize_text(item.get("body", ""))
            if not other:
                continue
            sim = SequenceMatcher(None, normalized_body, other).ratio()
            if sim >= threshold:
                return True
        return False

    def _is_mostly_english(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return False

        spanish_markers = [
            " el ", " la ", " los ", " las ", " de ", " del ", " y ", " en ",
            " para ", " con ", " una ", " un ", " por ", " que ", " como ",
            " producción ", " gobernanza ", " observabilidad ", " agentes "
        ]
        english_markers = [
            " the ", " and ", " in ", " for ", " with ", " to ", " of ", " on ",
            " production ", " governance ", " observability ", " agents ",
            " safety ", " runtime ", " monitoring ", " policy ", " architecture "
        ]

        padded = f" {normalized} "
        es_count = sum(1 for marker in spanish_markers if marker in padded)
        en_count = sum(1 for marker in english_markers if marker in padded)

        if en_count == 0:
            return False
        return en_count >= es_count

    def _has_agentic_niche(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        keywords = self._cfg_list("agentic_keywords", [
            "agent",
            "agentic",
            "orchestrator",
            "policy engine",
            "guardrail",
            "approval loop",
            "tool",
            "tool execution",
            "runtime",
            "production",
            "observability",
            "governance",
            "trace",
            "monitoring",
            "evaluation",
            "handoff",
            "safety",
            "escalation",
        ])
        count = sum(1 for kw in keywords if kw.lower() in normalized)
        threshold = self._cfg_int("editorial_keyword_threshold", 3)
        return count >= threshold

    def _has_named_pattern(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        patterns = self._cfg_list("named_pattern_keywords", [
            "pattern",
            "architecture",
            "operating model",
            "policy engine",
            "approval loop",
            "tool gateway",
            "guardrail layer",
            "orchestrator",
            "handoff",
            "evaluation pipeline",
            "runtime policy",
        ])
        return any(p.lower() in normalized for p in patterns)

    def _has_specific_agent_example(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        examples = self._cfg_list("specific_agent_examples", [
            "support agent",
            "retrieval agent",
            "content agent",
            "triage agent",
            "operations agent",
            "approval agent",
            "compliance agent",
        ])
        return any(example.lower() in normalized for example in examples)

    def _has_production_context(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        context_terms = self._cfg_list("production_context_terms", [
            "production",
            "runtime",
            "incident",
            "monitoring",
            "latency",
            "fallback",
            "approval",
            "audit",
            "trace",
            "deployment",
        ])
        return any(term.lower() in normalized for term in context_terms)

    def _count_actionable_markers(self, text: str) -> int:
        normalized = self._normalize_text(text)
        markers = self._cfg_list("actionable_markers", [
            "log",
            "trace",
            "monitor",
            "enforce",
            "validate",
            "route",
            "escalate",
            "review",
            "measure",
            "record",
            "audit",
            "retry",
            "fallback",
            "approve",
            "block",
        ])
        return sum(1 for marker in markers if marker.lower() in normalized)

    def _validate_editorial_fit(self, req: WriteRequest) -> Optional[str]:
        if req.write_type != "post":
            return None

        body = req.body or ""
        if not body.strip():
            return "empty_body"

        if self._cfg_bool("require_english_for_posts", True):
            if not self._is_mostly_english(body):
                return "post_not_mostly_english"

        if self._cfg_bool("require_agentic_niche", True):
            if not self._has_agentic_niche(body):
                return "post_outside_agentic_niche"

        if self._cfg_bool("require_named_pattern", True):
            if not self._has_named_pattern(body):
                return "missing_named_pattern"

        if self._cfg_bool("require_specific_agent_example", True):
            if not self._has_specific_agent_example(body):
                return "missing_specific_agent_example"

        if self._cfg_bool("require_production_context", True):
            if not self._has_production_context(body):
                return "missing_production_context"

        min_points = self._cfg_int("min_actionable_points", 2)
        if self._count_actionable_markers(body) < min_points:
            return "not_actionable_enough"

        return None

    def decide(self, req: WriteRequest) -> WriteDecision:
        if self.is_kill_switch_on():
            return WriteDecision(False, "kill_switch_enabled")

        recent = self._load_recent_writes()
        today = req.now.date().isoformat()

        if req.write_type == "post":
            editorial_reason = self._validate_editorial_fit(req)
            if editorial_reason:
                return WriteDecision(False, editorial_reason)

            posts_today = [
                w for w in recent
                if w.get("type") == "post" and str(w.get("created_at", "")).startswith(today)
            ]

            max_posts = self._cfg_int("max_posts_per_day", POLICY.max_posts_per_day)
            if len(posts_today) >= max_posts:
                return WriteDecision(False, "global_daily_post_cap_reached")

            per_submolt_cap = self._cfg_int("per_submolt_daily_post_cap", 2)
            posts_submolt = [w for w in posts_today if w.get("submolt") == req.submolt]
            if len(posts_submolt) >= per_submolt_cap:
                return WriteDecision(False, "per_submolt_daily_post_cap_reached")

            if self._cfg_bool("enable_recent_post_guard", False):
                if self._topic_recently_used(req.topic_key, req.now):
                    return WriteDecision(False, "topic_cooldown_active")

                if req.title:
                    title_hours = self._cfg_int("exact_title_cooldown_hours", 72)
                    for w in recent:
                        if w.get("type") != "post":
                            continue
                        if w.get("title") != req.title:
                            continue
                        created_at = w.get("created_at")
                        try:
                            last_dt = datetime.fromisoformat(created_at)
                        except Exception:
                            continue
                        if req.now - last_dt < timedelta(hours=title_hours):
                            return WriteDecision(False, "exact_title_cooldown_active")

                if self._is_similar_to_recent(req.body, recent):
                    return WriteDecision(False, "similar_content_recently_published")

        if req.write_type == "reply":
            replies_today = [
                w for w in recent
                if w.get("type") == "reply" and str(w.get("created_at", "")).startswith(today)
            ]

            reply_cap = self._cfg_int("global_daily_reply_cap", 20)
            if len(replies_today) >= reply_cap:
                return WriteDecision(False, "global_daily_reply_cap_reached")

            if req.thread_id:
                per_thread_cap = self._cfg_int("per_thread_reply_cap", 1)
                replies_thread = [w for w in replies_today if w.get("thread_id") == req.thread_id]
                if len(replies_thread) >= per_thread_cap:
                    return WriteDecision(False, "per_thread_reply_cap_reached")

        idem = self._hash_content(req.title, req.body) + f":{req.phase}:{req.write_type}"

        # Rate limit check (separate buckets for posts vs comments)
        if req.write_type == "post":
            if not self._post_bucket.can_write():
                wait = self._post_bucket.seconds_until_ready()
                return WriteDecision(False, f"post_rate_limited (wait {wait:.0f}s)", idempotency_key=idem)
        elif req.write_type == "reply":
            if not self._comment_bucket.can_write():
                wait = self._comment_bucket.seconds_until_ready()
                return WriteDecision(False, f"comment_rate_limited (wait {wait:.0f}s)", idempotency_key=idem)

        return WriteDecision(True, "allowed", idempotency_key=idem)

    def log_write(self, req: WriteRequest, platform_id: str):
        record = {
            "id": platform_id,
            "type": req.write_type,
            "title": req.title,
            "body": req.body,
            "submolt": req.submolt,
            "thread_id": req.thread_id,
            "topic_key": req.topic_key,
            "content_hash": self._hash_content(req.title, req.body),
            "idempotency_key": self._hash_content(req.title, req.body) + f":{req.phase}:{req.write_type}",
            "created_at": req.now.isoformat(),
            "phase": req.phase,
        }

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        if req.topic_key:
            topic_index = {}
            if self.topic_index_path.exists():
                try:
                    topic_index = json.loads(self.topic_index_path.read_text(encoding="utf-8"))
                except Exception:
                    topic_index = {}

            topic_index[req.topic_key] = req.now.isoformat()
            self.topic_index_path.write_text(
                json.dumps(topic_index, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

        # Consume rate limit token
        if req.write_type == "post":
            self._post_bucket.consume()
        elif req.write_type == "reply":
            self._comment_bucket.consume()