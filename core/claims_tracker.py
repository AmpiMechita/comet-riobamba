import json
import math
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


# ── Tech indicators for claim extraction ─────────────────────────────────────

TECH_INDICATORS = frozenset({
    "agent", "loop", "latency", "circuit breaker", "schema", "tool",
    "cascade", "failover", "guardrail", "prompt", "injection", "sandbox",
    "orchestration", "memory", "retry", "timeout", "cache", "token",
    "pipeline", "deployment", "rollback", "metric", "telemetry",
    "throughput", "quota", "throttle", "fallback", "checkpoint",
    "stateful", "stateless", "observability", "drift", "recovery",
    "escalation", "permission", "isolation", "embedding", "retrieval",
})


@dataclass
class Claim:
    id: str
    text: str
    topic_cluster: str
    first_made: str
    last_reinforced: str
    reinforcement_count: int = 0
    evolution_stage: str = "initial"


def _normalize_claim(text: str) -> str:
    normalized = text.lower().strip()
    for prefix in ("the ", "a ", "an ", "we ", "this ", "our ", "that "):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break
    return normalized.strip()


# ── Self-cliché filter ───────────────────────────────────────────

_SELF_CLICHE_PATTERNS = [
    "your rollback note is the key point",
    "recovery time matters more than raw throughput",
    "reliability is achieved through redundancy",
    "production is handled by circuit breakers",
    "edge cases are handled by circuit breakers",
    "when netflix deployed conductor",
    "when google deployed",
    "the fix is a",
    "the solution is a",
    "the key metric is",
    "how do you measure",
    "how do you differentiate",
    "what metric would you use",
    "what threshold would you set",
    "great point",
    "i agree",
]


def _is_self_cliche(claim_text: str) -> bool:
    """Reject claims that are the agent's own repetitive patterns."""
    claim_lower = claim_text.lower()
    return any(pattern in claim_lower for pattern in _SELF_CLICHE_PATTERNS)


def _jaccard_similarity(a: str, b: str) -> float:
    set_a = set(a.split())
    set_b = set(b.split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


class ClaimsTracker:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._claims: List[Claim] = []
        self._next_id = 1
        self._load()
        self._ensure_file_exists()
        self.purge_cliches()

    def purge_cliches(self) -> int:
        """Remove claims that match known self-cliché patterns. Returns count removed."""
        before = len(self._claims)
        self._claims = [c for c in self._claims if not _is_self_cliche(c.text)]
        after = len(self._claims)
        removed = before - after
        if removed > 0:
            self._save()
        return removed

    def extract_claims(self, text: str, topic_cluster: str) -> List[str]:
        raw_claims = []

        sentences = re.split(r'(?<=[.!?])\s+', text)
        for s in sentences:
            s = s.strip()
            if len(s) < 40:
                continue
            s_lower = s.lower()
            if not any(indicator in s_lower for indicator in TECH_INDICATORS):
                continue
            normalized = _normalize_claim(s)
            raw_claims.append(normalized)

        return raw_claims

    def register_claims(self, text: str, topic_cluster: str, source: str = "external") -> Dict:
        extracted = self.extract_claims(text, topic_cluster)
        new_count = 0
        reinforced_count = 0
        similar_found: List[str] = []
        now = datetime.now(timezone.utc).isoformat()

        for claim_text in extracted:
            # Filter self-clichés
            if _is_self_cliche(claim_text):
                continue
            # Stricter filter for own replies
            if source == "own_reply":
                if any(claim_text.startswith(q) for q in ["how ", "what ", "can ", "should "]):
                    continue
                if len(claim_text) < 60:
                    continue
            matched = False
            for existing in self._claims:
                sim = _jaccard_similarity(claim_text, existing.text)
                if sim >= 0.6:
                    existing.reinforcement_count += 1
                    existing.last_reinforced = now
                    if existing.evolution_stage == "initial":
                        existing.evolution_stage = "refined"
                    reinforced_count += 1
                    similar_found.append(existing.id)
                    matched = True
                    break

            if not matched:
                new_claim = Claim(
                    id=f"claim_{self._next_id:04d}",
                    text=claim_text,
                    topic_cluster=topic_cluster,
                    first_made=now,
                    last_reinforced=now,
                    reinforcement_count=1,
                    evolution_stage="initial",
                )
                self._claims.append(new_claim)
                self._next_id += 1
                new_count += 1

        if new_count > 0 or reinforced_count > 0:
            self._save()

        return {
            "new": new_count,
            "reinforced": reinforced_count,
            "similar_found": similar_found,
        }

    def get_context_for_reply(self, topic_cluster: str) -> str:
        matching = [
            c for c in self._claims if c.topic_cluster == topic_cluster
        ]
        matching.sort(key=lambda c: c.reinforcement_count, reverse=True)

        if not matching:
            return ""

        lines = ["YOUR PREVIOUS CLAIMS ON THIS TOPIC (do not repeat without evolution):"]
        for c in matching[:5]:
            stage = c.evolution_stage
            lines.append(
                f"- [{stage}] {c.text} (stated {c.reinforcement_count}x)"
            )
        return "\n".join(lines)

    def _load(self) -> None:
        state_file = self.data_dir / "data" / "claims_tracker.json"
        if not state_file.exists():
            return
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            raw = data.get("claims", [])
            self._claims = [Claim(**c) for c in raw]
            self._next_id = data.get("next_id", len(self._claims) + 1)
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            self._claims = []
            self._next_id = 1

    def _ensure_file_exists(self) -> None:
        state_file = self.data_dir / "data" / "claims_tracker.json"
        if not state_file.exists():
            self._save()

    def _save(self) -> None:
        state_file = self.data_dir / "data" / "claims_tracker.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "next_id": self._next_id,
            "claims": [asdict(c) for c in self._claims],
        }
        state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
