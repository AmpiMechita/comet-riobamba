# -*- coding: utf-8 -*-
"""Phase B scoring — relevance decisions and feed thresholds."""

import logging
from dataclasses import dataclass

from config.agent_policy import POLICY
from .constants import (
    _COLD_START_MIN_SCORE,
    _COLD_START_THRESHOLD,
    _cold_start_lock,
)
from . import constants as _constants_mod

logger = logging.getLogger("phases.phase_b")


@dataclass
class RelevanceDecision:
    should_reply: bool
    score: int
    reason: str


def _get_feed_min_score(posts_today: int) -> int:
    if posts_today < _COLD_START_THRESHOLD:
        if not _constants_mod._cold_start_logged:
            with _cold_start_lock:
                if not _constants_mod._cold_start_logged:
                    _constants_mod._cold_start_logged = True
                    logger.info(
                        "Cold start activo: posts_today=%s < threshold=%s, "
                        "usando min_score=%s en lugar de %s",
                        posts_today, _COLD_START_THRESHOLD,
                        _COLD_START_MIN_SCORE,
                        POLICY.min_comment_relevance_score + 1,
                    )
        return _COLD_START_MIN_SCORE
    return POLICY.min_comment_relevance_score + 1


# ── Scientific relevance signals ──────────────────────────────────

SCIENCE_SIGNALS = frozenset([
    "propose", "hypothesis", "framework", "architecture", "pattern",
    "protocol", "algorithm", "mechanism", "methodology",
    "measured", "observed", "data shows", "benchmark", "experiment",
    "in production", "we deployed", "results indicate", "paper",
    "arxiv", "doi", "findings",
    "the fix", "solution", "implementation", "optimization",
    "tradeoff", "trade-off", "constraint", "threshold",
    "novel", "approach", "technique", "improvement",
    "state of the art", "sota", "breakthrough",
    "kubernetes", "kafka", "redis", "flink", "spark",
    "transformer", "attention", "embedding", "vector",
    "circuit breaker", "backpressure", "consensus",
    "latency", "throughput", "p99", "p95", "percentile",
    "accuracy", "precision", "recall", "f1",
])

LOW_VALUE_SIGNALS = frozenset([
    "great point", "i agree", "exactly", "well said", "nice",
    "interesting", "cool", "thanks", "good point",
    "what do you think", "thoughts?", "any ideas",
    "check out", "follow me", "subscribe", "my project",
    "this is important", "we should talk about this",
    "someone should look into",
])


def has_scientific_value(text: str) -> bool:
    """Determine if a comment has enough scientific/technical value to warrant a reply.

    Returns True only if the comment contains concrete technical proposals,
    evidence, solutions, or novel technology references.
    """
    if not text or len(text.strip()) < 40:
        return False

    text_lower = text.lower()

    # Immediate rejection: low-value signals dominate
    low_value_count = sum(1 for s in LOW_VALUE_SIGNALS if s in text_lower)
    if low_value_count >= 2:
        return False

    # Require at least 2 science signals for short comments (<200 chars)
    # or at least 1 for longer comments (>200 chars)
    science_count = sum(1 for s in SCIENCE_SIGNALS if s in text_lower)
    if len(text.strip()) < 200:
        return science_count >= 2
    else:
        return science_count >= 1
