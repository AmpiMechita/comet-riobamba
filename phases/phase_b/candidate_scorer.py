# -*- coding: utf-8 -*-
"""
Candidate Scorer — ranks comments by reply potential.

Scores each unreplied comment to decide which ones get the limited
reply budget. Higher score = higher priority for a reply.
"""

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("phases.phase_b")


# ── Load strategy config (phase_b_strategy.yaml) ─────────────────

@lru_cache(maxsize=1)
def _load_strategy() -> Dict:
    """Load and cache the phase_b_strategy.yaml config."""
    strategy_file = Path(__file__).parent.parent.parent / "config" / "phase_b_strategy.yaml"
    try:
        import yaml  # type: ignore
        if strategy_file.exists():
            return yaml.safe_load(strategy_file.read_text(encoding="utf-8")) or {}
    except ImportError:
        # yaml not available — parse manually for the values we need
        pass
    except Exception as e:
        logger.warning("candidate_scorer: failed to load strategy YAML: %s", e)
    return {}


def _get_high_priority_agents() -> Dict[str, float]:
    """Return {agent_name: score_multiplier} for high-priority agents."""
    strategy = _load_strategy()
    result = {}
    for entry in strategy.get("target_agents", {}).get("high_priority", []):
        if isinstance(entry, dict) and "agent" in entry:
            result[entry["agent"].lower()] = float(entry.get("score_multiplier", 1.0))
    return result


def _get_karma_threshold() -> int:
    strategy = _load_strategy()
    return int(strategy.get("target_agents", {}).get("community_building", {}).get("karma_threshold", 10000))


def _get_karma_bonus() -> float:
    strategy = _load_strategy()
    return float(strategy.get("target_agents", {}).get("community_building", {}).get("karma_bonus", 10))


def _get_allowed_submolts() -> frozenset:
    strategy = _load_strategy()
    allowed = strategy.get("submolt_strategy", {}).get("allowed_submolts", [])
    if allowed:
        return frozenset(s.lstrip("m/") for s in allowed)
    # Static fallback (YAML unavailable): mirror orchestrator allowlist.
    return frozenset({
        "general", "infrastructure", "openclaw-explorers", "technology",
        "agentstack", "ai",
    })


# Static fallback (YAML unavailable): expanded 40-term vocabulary, mirrors
# orchestrator._load_tech_terms_vocabulary so the density gate/bypass agree.
_TECH_TERMS_VOCABULARY_FALLBACK = frozenset({
    "latency", "token", "schema", "agent", "memory", "api",
    "cache", "retry", "error", "state", "context", "p99",
    "dag", "idempotency", "throughput", "bottleneck",
    "crdt", "mvcc", "consensus", "quorum", "serialization", "mutex",
    "deadlock", "raft", "paxos", "wal", "append-only", "merkle",
    "byzantine", "cap", "bac", "isolation", "linearizability", "causal",
    "monotonic", "garbage", "compaction", "lease", "fence", "sharding",
})


def _get_tech_terms_vocabulary() -> frozenset:
    """Load hard tech-term vocabulary from phase_b_strategy.yaml, with fallback
    to the expanded static list (same source used by the density gate)."""
    strategy = _load_strategy()
    terms = strategy.get("tech_terms_vocabulary", [])
    if terms:
        return frozenset(str(t).strip().lower() for t in terms if str(t).strip())
    return _TECH_TERMS_VOCABULARY_FALLBACK


def _passes_density_gate(text_lower: str) -> bool:
    """True if text has 2+ hard tech terms AND 1+ metric/data-structure."""
    import re
    vocab = _get_tech_terms_vocabulary()
    tech_count = sum(1 for term in vocab if term in text_lower)
    has_data_structure = any(ds in text_lower for ds in ("tree", "queue", "graph", "buffer"))
    has_metric_or_structure = (
        bool(re.search(r"\d", text_lower)) or "%" in text_lower or has_data_structure
    )
    return tech_count >= 2 and has_metric_or_structure


# Minimum priority floor for high technical substance so distributed-systems
# comments (CRDT, MVCC, quorum...) are not filtered as low relevance.
_HIGH_DENSITY_SCORE_FLOOR = 0.30



# Scoring weights
_WEIGHTS = {
    "length": 0.15,           # Longer comments signal more effort
    "has_question": 0.25,     # Direct questions deserve replies
    "mentions_agent": 0.20,   # Explicit mentions = direct engagement
    "tech_depth": 0.20,       # Technical vocabulary density
    "debate_potential": 0.10, # Author has history of back-and-forth
    "claim_alignment": 0.10,  # Aligns with agent's existing claims
}

_TECH_TERMS = frozenset([
    "latency", "throughput", "p99", "p95", "circuit breaker", "fallback",
    "retry", "timeout", "cache", "pipeline", "deploy", "rollback",
    "metric", "telemetry", "observability", "drift", "schema",
    "guardrail", "threshold", "bottleneck", "queue", "batch",
    "embedding", "vector", "index", "shard", "replica", "consensus",
    "idempotent", "backpressure", "rate limit", "token bucket",
])


def _get_strategy_bonus(text: str) -> float:
    """Bonus score if comment aligns with high-performing reply types."""
    try:
        from services.reply_feedback import get_strategy_hint
        hint = get_strategy_hint()
        if not hint or hint.get("sample_size", 0) < 5:
            return 0.0
        best_types = hint.get("best_types", [])
        text_lower = text.lower()
        type_signals = {
            "empirical_finding": ["measured", "data", "production", "observed", "experiment"],
            "framework_proposal": ["pattern", "architecture", "framework", "design"],
            "critique_with_alternative": ["problem", "issue", "flaw", "instead", "alternative"],
            "metric_proposal": ["metric", "threshold", "percentile", "measure", "track"],
        }
        for btype in best_types:
            signals = type_signals.get(btype, [])
            if any(s in text_lower for s in signals):
                return 0.15
        return 0.0
    except Exception:
        return 0.0


def _compute_recency_adjustment(comment: Dict[str, Any]) -> float:
    """v5.0: Compute recency bonus/penalty for a candidate.

    +30 if post was created < 2 hours ago.
    -20 if post is > 24 hours old (stale thread).
    """
    ts_raw = comment.get("created_at") or comment.get("createdAt") or comment.get("timestamp") or ""
    if not ts_raw:
        return 0.0
    try:
        from datetime import datetime, timezone, timedelta
        ts_str = str(ts_raw).replace("Z", "+00:00")
        created = datetime.fromisoformat(ts_str)
        now = datetime.now(timezone.utc)
        age_hours = (now - created).total_seconds() / 3600
        cid = comment.get("id") or comment.get("comment_id") or "?"
        if age_hours < 2:
            logger.info("Scorer: Candidato %s tiene %.1fh de antigüedad. Bonus +30 aplicado.", cid, age_hours)
            return 30.0
        elif age_hours > 24:
            logger.info("Scorer: Candidato %s tiene %.1fh de antigüedad. Penalty -20 aplicado.", cid, age_hours)
            return -20.0
        else:
            logger.debug("Scorer: Candidato %s tiene %.1fh de antigüedad. Sin ajuste.", cid, age_hours)
    except (ValueError, TypeError, OverflowError):
        pass
    return 0.0


def _extract_submolt_name(submolt_raw: Any) -> str:
    """Extract submolt name whether API returns dict, stringified dict, or plain string.

    Moltbook API returns submolt as: {"id":"29beb7ee...","name":"general","display_name":"general"}
    Sometimes it comes stringified: "{'id': '...', 'name': 'general'}"
    Older API versions return plain strings: "general" or "m/general"
    """
    if isinstance(submolt_raw, dict):
        name = submolt_raw.get("name") or submolt_raw.get("display_name") or \
               submolt_raw.get("id") or ""
        return str(name).strip().lower()
    if isinstance(submolt_raw, str):
        raw_str = submolt_raw.strip()
        if raw_str.startswith("{") or raw_str.startswith("[{"):
            try:
                import ast
                parsed = ast.literal_eval(raw_str)
                if isinstance(parsed, dict):
                    name = parsed.get("name") or parsed.get("display_name") or ""
                    return str(name).strip().lower()
                if isinstance(parsed, list) and parsed:
                    name = parsed[0].get("name") or parsed[0].get("display_name") or ""
                    return str(name).strip().lower()
            except (ValueError, SyntaxError):
                pass
        return raw_str.lower()
    return str(submolt_raw).strip().lower()


def _resolve_author(author_value: Any) -> str:
    """Resolve author field to a lowercase string."""
    if isinstance(author_value, dict):
        return (str(author_value.get("name") or author_value.get("username") or "")).lower()
    return (str(author_value or "")).lower()


def _resolve_author_karma(comment: Dict[str, Any]) -> Optional[int]:
    """Extract karma from comment's author field if present."""
    author_value = comment.get("author")
    if isinstance(author_value, dict):
        karma = author_value.get("karma")
        if karma is not None:
            try:
                return int(karma)
            except (ValueError, TypeError):
                pass
    karma_raw = comment.get("karma") or comment.get("author_karma")
    if karma_raw is not None:
        try:
            return int(karma_raw)
        except (ValueError, TypeError):
            pass
    return None


def score_comment(
    comment: Dict[str, Any],
    agent_claims: Optional[List[str]] = None,
    known_debaters: Optional[set] = None,
    is_own_post: bool = False,
) -> float:
    """Score a comment from 0.0 to 1.0 for reply priority.
    Inbound en posts propios tiene bonus alto - priorizar reciprocidad.
    

    Args:
        comment: dict with at least "content"/"text" and "author"
        agent_claims: list of claim texts the agent has made (for alignment)
        known_debaters: set of author names who have engaged in multi-turn debates
        is_own_post: True if comment is on agent own post (inbound)
    """

    # Bonus por inbound en post propio (reciprocidad)
    # Bonus por inbound en post propio (reciprocidad)
    if is_own_post:
        return 1.0  # Prioridad máxima para comentarios en posts propios

    text = (comment.get("content") or comment.get("text") or "").strip()
    author = _resolve_author(comment.get("author"))
    text_lower = text.lower()

    if not text_lower:
        return 0.0

    # ── v5.0: Submolt gate — reject candidates from non-allowed submolts ──
    submolt_raw = comment.get("submolt") or comment.get("community") or ""
    if submolt_raw:
        allowed = _get_allowed_submolts()
        # Extract name whether API returns dict, stringified dict, or plain string
        submolt_name = _extract_submolt_name(submolt_raw)
        submolt_clean = submolt_name.lstrip("m/")
        if submolt_clean and allowed and submolt_clean not in allowed:
            cid = comment.get("id") or comment.get("comment_id") or "?"
            logger.info("candidate_scorer: REJECTED candidate=%s submolt='%s' (not in allowed=%s)", cid, submolt_clean, sorted(allowed))
            return 0.0

    scores = {}

    # Length score (normalized: 0 at 0 chars, 1.0 at 300+ chars)
    scores["length"] = min(1.0, len(text) / 300.0)

    # Question detection
    has_q = "?" in text or any(
        w in text_lower for w in ("how", "why", "what if", "could you", "have you")
    )
    scores["has_question"] = 1.0 if has_q else 0.0

    # Agent mention
    mentions = {"@comet", "comet-riobamba", "comet_riobamba", "comet riobamba", "riobamba"}
    scores["mentions_agent"] = 1.0 if any(m in text_lower for m in mentions) else 0.0

    # Tech depth (fraction of tech terms present)
    found = sum(1 for t in _TECH_TERMS if t in text_lower)
    scores["tech_depth"] = min(1.0, found / 3.0)

    # Debate potential
    scores["debate_potential"] = 1.0 if (known_debaters and author in known_debaters) else 0.0

    # Claim alignment
    if agent_claims:
        comment_words = set(text_lower.split())
        max_overlap = 0.0
        for claim in agent_claims[:10]:
            claim_words = set(claim.lower().split())
            if claim_words:
                overlap = len(comment_words & claim_words) / len(claim_words)
                max_overlap = max(max_overlap, overlap)
        scores["claim_alignment"] = min(1.0, max_overlap)
    else:
        scores["claim_alignment"] = 0.0

    # Weighted sum + strategy bonus
    total = sum(scores[k] * _WEIGHTS[k] for k in _WEIGHTS)
    strategy_bonus = _get_strategy_bonus(text)
    total += strategy_bonus

    # ── v5.0: High-priority author multiplier ──
    high_priority_agents = _get_high_priority_agents()
    if author in high_priority_agents:
        multiplier = high_priority_agents[author]
        total *= multiplier
        logger.debug("candidate_scorer: applied high_priority multiplier x%.1f for '%s'", multiplier, author)

    # ── v5.0: Community building — karma bonus ──
    karma = _resolve_author_karma(comment)
    karma_threshold = _get_karma_threshold()
    if karma is not None and karma < karma_threshold:
        karma_bonus = _get_karma_bonus()
        total += karma_bonus
        logger.debug("candidate_scorer: applied karma bonus +%.1f for '%s' (karma=%s)", karma_bonus, author, karma)

    # ── v5.0: Recency bonus / stale penalty ──
    recency_bonus = _compute_recency_adjustment(comment)
    total += recency_bonus

    final = round(min(1.0, total), 4)

    # ── Relevance bypass: guarantee a minimum priority for high technical
    #    substance so senior-engineer comments (CRDT, MVCC, quorum, ...) that
    #    don't match roadmap keywords still reach the LLM for debate. ──
    if final < _HIGH_DENSITY_SCORE_FLOOR and _passes_density_gate(text_lower):
        logger.info(f"Phase B: Bypass de relevancia aplicado a {author} por alta densidad técnica / own-post reply.")
        return _HIGH_DENSITY_SCORE_FLOOR

    return final


def rank_candidates(
    comments: List[Dict[str, Any]],
    agent_claims: Optional[List[str]] = None,
    known_debaters: Optional[set] = None,
    top_n: int = 5,
) -> List[Dict[str, Any]]:
    """Rank comments by reply priority, return top N with scores.

    Returns list of dicts: [{"comment": {...}, "priority_score": 0.85}, ...]
    """
    scored = []
    for c in comments:
        s = score_comment(c, agent_claims, known_debaters)
        scored.append({"comment": c, "priority_score": s})
    scored.sort(key=lambda x: x["priority_score"], reverse=True)
    return scored[:top_n]
