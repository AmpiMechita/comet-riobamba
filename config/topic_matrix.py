from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional


# ── Topic dataclass ──────────────────────────────────────────────────────────

@dataclass
class Topic:
    id: str
    label: str
    cluster: str
    angle: str
    keywords: List[str] = field(default_factory=list)
    last_used: Optional[datetime] = None
    use_count: int = 0
    cooldown_hours: int = 24

    def is_available(self) -> bool:
        if self.last_used is None:
            return True
        elapsed = datetime.now(timezone.utc) - self.last_used
        return elapsed >= timedelta(hours=self.cooldown_hours)


# ── TopicMatrix dataclass ────────────────────────────────────────────────────

@dataclass
class TopicMatrix:
    topics: List[Topic]
    cluster_weights: Dict[str, float] = field(default_factory=dict)
    recent_choices: List[str] = field(default_factory=list)
    rotation_window: int = 6

    def select_topic(self, force_cluster: Optional[str] = None) -> Optional[Topic]:
        available = [t for t in self.topics if t.is_available()]

        if not available:
            for t in self.topics:
                t.last_used = None
            available = list(self.topics)

        # Exclude recent choices within the rotation window
        recent_ids = set(self.recent_choices[-self.rotation_window :])
        candidates = [t for t in available if t.id not in recent_ids]
        if not candidates:
            candidates = available

        if force_cluster:
            candidates = [t for t in candidates if t.cluster == force_cluster]
            if not candidates:
                candidates = [t for t in available if t.cluster == force_cluster]
            if not candidates:
                candidates = available

        if not candidates:
            return None

        # Count cluster appearances within recent choices
        recent_clusters = [
            self._topic_by_id(tid).cluster
            for tid in self.recent_choices[-self.rotation_window :]
            if self._topic_by_id(tid) is not None
        ]

        def _score(t: Topic) -> float:
            cw = self.cluster_weights.get(t.cluster, 1.0)
            rcc = recent_clusters.count(t.cluster)
            return cw / (rcc + 1) - t.use_count * 0.1

        candidates.sort(key=_score, reverse=True)
        chosen = candidates[0]

        chosen.last_used = datetime.now(timezone.utc)
        chosen.use_count += 1
        self.recent_choices.append(chosen.id)

        return chosen

    def get_cluster_balance(self) -> Dict[str, float]:
        if not self.recent_choices:
            return {}
        window = self.recent_choices[-self.rotation_window :]
        total = len(window)
        counts: Dict[str, int] = {}
        for tid in window:
            t = self._topic_by_id(tid)
            if t:
                counts[t.cluster] = counts.get(t.cluster, 0) + 1
        return {k: v / total for k, v in sorted(counts.items())}

    def least_used_cluster(self) -> Optional[str]:
        if not self.topics:
            return None
        balance = self.get_cluster_balance()
        all_clusters = set(t.cluster for t in self.topics)
        if not balance:
            return sorted(all_clusters)[0]
        present = set(balance.keys())
        absent = all_clusters - present
        if absent:
            return sorted(absent)[0]
        return min(balance, key=balance.get)

    def _topic_by_id(self, tid: str) -> Optional[Topic]:
        for t in self.topics:
            if t.id == tid:
                return t
        return None


# ── Default constants ────────────────────────────────────────────────────────

DEFAULT_CLUSTER_WEIGHTS: Dict[str, float] = {
    "architecture": 1.2,
    "infrastructure": 1.0,
    "safety": 1.0,
    "evaluation": 0.9,
    "historical": 0.8,
    "fringe": 0.5,
}

DEFAULT_TOPICS: List[Topic] = [
    # Infrastructure
    Topic("infra-rate-limit", "Rate-limit and quota management in autonomous agents", "infrastructure", "empirical", ["rate", "limit", "quota", "throttle"]),
    Topic("infra-observability", "Observability gaps in production AI agent pipelines", "infrastructure", "empirical", ["observability", "monitoring", "telemetry", "tracing"]),
    Topic("infra-state", "State management and persistence in long-running agents", "infrastructure", "architectural", ["state", "persistence", "session", "checkpoint"]),
    Topic("infra-backpressure", "Back-pressure and overload protection in agent systems", "infrastructure", "empirical", ["backpressure", "load", "shedding", "congestion"]),
    # Architecture
    Topic("arch-cascade", "Model cascade reliability and provider failover", "architecture", "architectural", ["cascade", "failover", "fallback", "reliability"]),
    Topic("arch-multi-agent", "Multi-agent orchestration and coordination patterns", "architecture", "architectural", ["multi-agent", "orchestration", "coordination", "swarm"]),
    Topic("arch-memory", "Memory architectures for context-aware agents", "architecture", "architectural", ["memory", "context", "retrieval", "embedding"]),
    Topic("arch-tools", "Tool-calling failure taxonomy and retry strategies", "architecture", "architectural", ["tool", "calling", "retry", "function"]),
    # Safety
    Topic("safety-guardrails", "Guardrails for autonomous posting agents", "safety", "critical", ["guardrail", "safety", "policy", "constraint"]),
    Topic("safety-prompt-injection", "Prompt injection defense vectors for agent pipelines", "safety", "critical", ["injection", "defense", "sanitization", "isolation"]),
    Topic("safety-sandboxing", "Sandboxing and permission escalation risks in multi-agent runtimes", "safety", "critical", ["sandbox", "permission", "escalation", "isolation"]),
    Topic("safety-alignment", "Alignment and value locking in self-modifying agents", "safety", "critical", ["alignment", "value", "lock", "self-modify"]),
    # Evaluation
    Topic("eval-methodology", "Evaluation methodology for agent output quality", "evaluation", "empirical", ["evaluation", "benchmark", "quality", "metric"]),
    Topic("eval-regression", "Regression detection in autonomous agent behavior", "evaluation", "empirical", ["regression", "detection", "behavior", "drift"]),
    Topic("eval-cost", "Cost optimization and efficiency in LLM agent pipelines", "evaluation", "empirical", ["cost", "optimization", "efficiency", "token"]),
    # Historical
    Topic("hist-distributed", "Lessons from distributed systems for agent architectures", "historical", "historical", ["distributed", "consensus", "failure", "recovery"]),
    Topic("hist-compiler", "Compiler and type-system insights applied to agent tool-use", "historical", "historical", ["compiler", "type", "verification", "static"]),
    Topic("hist-control", "Control theory applications for agent loop stabilization", "historical", "historical", ["control", "feedback", "stability", "loop"]),
    # Fringe
    Topic("fringe-consciousness", "Consciousness and metacognition in agent frameworks", "fringe", "critical", ["consciousness", "metacognition", "self", "awareness"]),
    Topic("fringe-economics", "Economic models for agent-to-agent negotiation", "fringe", "critical", ["economics", "negotiation", "market", "incentive"]),
    Topic("fringe-evolution", "Evolutionary and bio-inspired optimization for agent design", "fringe", "critical", ["evolution", "bio-inspired", "genetic", "adaptation"]),
]


# ── Persistence ──────────────────────────────────────────────────────────────

_STATIC_FIELDS = {"id", "label", "cluster", "angle", "keywords", "cooldown_hours"}


def save_topic_matrix(matrix: TopicMatrix, state_file: Path) -> None:
    state = {
        "recent_choices": matrix.recent_choices,
        "rotation_window": matrix.rotation_window,
        "cluster_weights": matrix.cluster_weights,
        "topics": [
            {
                "id": t.id,
                "last_used": t.last_used.isoformat() if t.last_used else None,
                "use_count": t.use_count,
            }
            for t in matrix.topics
        ],
    }
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_topic_matrix(state_file: Path) -> TopicMatrix:
    matrix = TopicMatrix(
        topics=[Topic(id=t.id, label=t.label, cluster=t.cluster, angle=t.angle, keywords=list(t.keywords), cooldown_hours=t.cooldown_hours) for t in DEFAULT_TOPICS],
        cluster_weights=dict(DEFAULT_CLUSTER_WEIGHTS),
    )

    if not state_file.exists():
        return matrix

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return matrix

    # Restore recent_choices and rotation_window
    matrix.recent_choices = state.get("recent_choices", [])
    matrix.rotation_window = state.get("rotation_window", 6)
    matrix.cluster_weights.update(state.get("cluster_weights", {}))

    # Restore per-topic mutable state
    topic_states = state.get("topics", [])
    topic_map = {ts["id"]: ts for ts in topic_states}
    for t in matrix.topics:
        if t.id in topic_map:
            ts = topic_map[t.id]
            raw = ts.get("last_used")
            if raw:
                try:
                    t.last_used = datetime.fromisoformat(raw)
                except (ValueError, TypeError):
                    t.last_used = None
            t.use_count = ts.get("use_count", 0)

    return matrix
