import enum
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict


class ResearchValueType(enum.Enum):
    FRAMEWORK_PROPOSAL = "framework_proposal"
    EMPIRICAL_FINDING = "empirical_finding"
    CRITIQUE_WITH_ALTERNATIVE = "critique_with_alternative"
    HISTORICAL_PARALLEL = "historical_parallel"
    METRIC_PROPOSAL = "metric_proposal"
    CLARIFICATION = "clarification"
    AGREEMENT = "agreement"
    REPETITION = "repetition"


RESEARCH_VALUE_WEIGHTS: Dict[ResearchValueType, float] = {
    ResearchValueType.FRAMEWORK_PROPOSAL: 1.0,
    ResearchValueType.EMPIRICAL_FINDING: 0.95,
    ResearchValueType.CRITIQUE_WITH_ALTERNATIVE: 0.9,
    ResearchValueType.HISTORICAL_PARALLEL: 0.8,
    ResearchValueType.METRIC_PROPOSAL: 0.5,
    ResearchValueType.CLARIFICATION: 0.3,
    ResearchValueType.AGREEMENT: 0.1,
    ResearchValueType.REPETITION: 0.0,
}


def _count_signals(text: str, *patterns: str) -> int:
    text_lower = text.lower()
    return sum(1 for p in patterns if p in text_lower)


# Verbos de RESULTADO en pasado: indican un efecto ya medido (un hallazgo
# empirico), no una propuesta de medir. Una metrica acompanada de uno de estos
# NO debe caer a metric_proposal.
OUTCOME_SIGNALS = (
    "cut ", "reduced", "dropped", "rejected", "rejecting", "eliminated", "halved",
    "decreased", "increased", "prevented", "caught", "the fix was", "the fix ",
    "we now ", "we switched", "we moved", "in our runs", "in practice", "once we",
)


def classify_content(text: str) -> ResearchValueType:
    # 1. Framework: senal fuerte explicita
    if _count_signals(text, "i propose", "a framework for") >= 1:
        return ResearchValueType.FRAMEWORK_PROPOSAL

    # 2. Empirical: keywords originales O (metrica + verbo de resultado en pasado).
    #    Un hallazgo empirico ES una medicion con resultado; no debe caer a metric_proposal.
    _orig_empirical = _count_signals(
        text, "measured", "observed", "in our tests", "in production", "data shows",
        "latency", "throughput", "we deployed", "we benchmarked",
    ) >= 1
    _metric_with_outcome = _has_metric_signals(text) and _count_signals(text, *OUTCOME_SIGNALS) >= 1
    if _orig_empirical or _metric_with_outcome:
        return ResearchValueType.EMPIRICAL_FINDING

    # 3. Framework por 2+ keywords de arquitectura
    if _count_signals(
        text, "framework", "pattern", "architecture", "design",
        "invariant", "consensus", "dag", "merkle", "entropy", "schema",
    ) >= 2:
        return ResearchValueType.FRAMEWORK_PROPOSAL

    # 4. Critica con alternativa
    has_critique = _count_signals(text, "the problem is", "fails because", "breaks when", "does not handle") >= 1
    has_alternative = _count_signals(text, "instead", "alternative", "better approach", "fix:", "solution is") >= 1
    if has_critique and has_alternative:
        return ResearchValueType.CRITIQUE_WITH_ALTERNATIVE

    # 5. Metric_proposal: AHORA fallthrough — solo metricas SIN sustancia de arriba
    #    (ej. "deberiamos trackear la latencia", una propuesta de medir sin resultado).
    if _has_metric_signals(text):
        return ResearchValueType.METRIC_PROPOSAL

    # 6-8. Historical / agreement / clarification (igual que antes)
    if _count_signals(text, "in 199", "in 200", "similar to how", "parallel to", "learned from") >= 2:
        return ResearchValueType.HISTORICAL_PARALLEL
    if len(text) < 200 and _count_signals(text, "good point", "exactly", "you're right", "solid engineering") >= 2:
        return ResearchValueType.AGREEMENT
    return ResearchValueType.CLARIFICATION


def _has_metric_signals(text: str) -> bool:
    if re.search(r'\d+\.?\d*\s*%', text):
        return True
    if re.search(r'\b\d+(\.\d+)?\s*(ms|seconds|minutes|hours|rps|tps|qps|requests per)\b', text, re.IGNORECASE):
        return True
    if _count_signals(
        text,
        "percentile", "p99", "p95", "p50", "median", "average",
        "reduction", "increase", "improved by", "dropped by",
        "useful signal", "useful metric", "track the", "measure the",
    ) >= 1:
        return True
    return False


def compute_dual_score(
    text: str,
    reply_count: int = 0,
    upvote_count: int = 0,
) -> Dict:
    content_type = classify_content(text)
    research_value_score = RESEARCH_VALUE_WEIGHTS[content_type]
    raw_engagement = reply_count * 0.1 + upvote_count * 0.05
    engagement_score = min(1.0, raw_engagement)
    composite_score = (engagement_score * 0.3) + (research_value_score * 0.7)

    return {
        "content_type": content_type.value,
        "engagement_score": engagement_score,
        "research_value_score": research_value_score,
        "composite_score": round(composite_score, 4),
    }


DUAL_SCORE_LOG = Path("data/dual_scores.jsonl")


def log_dual_score(
    text: str,
    phase: str,
    reply_count: int = 0,
    upvote_count: int = 0,
) -> None:
    score = compute_dual_score(text, reply_count, upvote_count)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "type": score["content_type"],
        "engagement": score["engagement_score"],
        "research_value": score["research_value_score"],
        "composite": score["composite_score"],
        "text_preview": text[:100],
    }
    DUAL_SCORE_LOG.parent.mkdir(parents=True, exist_ok=True)
    from utils.jsonl_rotation import append_jsonl
    append_jsonl(record, DUAL_SCORE_LOG, max_lines=1000)
