# -*- coding: utf-8 -*-
"""
COMET-RIOBAMBA v4.3.4 - Fase A
Generacion de Contenido Cientifico Original (Voz de Ingeniero Experto)

Modos de operacion:
  - "expository": formato original (3 parrafos, cierre sin pregunta).
  - "research":   (por defecto) incluye secciones de Problema -> Propuesta ->
                   Pregunta de investigacion al final.  Lee la agenda de
                   investigacion para priorizar temas no cubiertos.
"""

import asyncio
import json
import os
import time
import logging
import random
import re
from datetime import datetime, timezone, UTC, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import behavior_cfg, BASE_DIR
from config.agent_policy import POLICY
from config.topic_matrix import load_topic_matrix, save_topic_matrix
from core.observability import send_event
from phases.deps import PhaseADeps
from services.challenge_solver import ChallengeSolver
from services.experiments import load_experiments, pick_variant, get_variant_config
from services.roadmap import load_roadmap, choose_topic_from_roadmap, save_roadmap
from services.research_agenda import load_agenda, ResearchAgenda
from core.strategy_state import StrategyState
from prompts.prompt_templates import inject_self_diagnosis
from utils.phase_utils import phase_error_boundary, validate_phase_deps
from services.editorial_policy import load_editorial_policy
from services.dual_scoring import log_dual_score
from services.used_examples_tracker import mark_examples_used
from services.persistence import (
    enqueue_outbox,
    is_similar_to_recent,
    store_post_hash,
    load_topic_engagement,
)

logger = logging.getLogger("phases.phase_a_content")

PERFORMANCE_LOG_PATH = BASE_DIR / "data/topic_performance.jsonl"
_PERFORMANCE_SUMMARY_PATH = BASE_DIR / "data/performance_summary.json"



# Patrones de rechazo estricto (Anti-Spam Moltbook)
URL_PATTERN = re.compile(r"https?://|www\.", re.IGNORECASE)
CODE_PATTERN = re.compile(r"def\s+|class\s+|import\s+|\basync\b|\bawait\b", re.MULTILINE)
ERROR_PATTERN = re.compile(r"Traceback \(most recent call last\)|Exception|HTTPError|ConnectionError", re.IGNORECASE)
BULLET_PATTERN = re.compile(r"^\s*[-*•]\s+", re.MULTILINE)
EMOJI_PATTERN = re.compile(r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF]", re.UNICODE)
ACADEMIC_SUBTITLE_PATTERN = re.compile(r"^\s*(Abstract|Claim|Introduction|Conclusion|Failure Case|Discussion|Methodology)\s*:?", re.IGNORECASE | re.MULTILINE)
FILLER_STARTS = re.compile(r"^(In the realm of|One non-obvious|Consider a scenario where)", re.IGNORECASE)

EDITORIAL_CONFIG = {
    "language": "en",
    "target_length_chars": 600,
    "min_length_chars": 300,
    "max_length_chars": 900,
    "max_tokens": 600,
    "temperature": 0.65,
    "phase_a_max_attempts": 3,
    "topics": [
        "Gestión de memoria y contexto persistente en agentes LLM",
        "Automatización en cascada con modelos locales",
        "Resolución de CAPTCHAs y anti-bot en scraping ético",
        "Observabilidad y tracing en sistemas de agentes",
        "Deuda técnica en pipelines de automatización",
        "Integración de PowerShell en flujos de IA",
        "Post-mortems de fallos reales en producción",
        "provider failover and model cascade reliability",
        "context window exhaustion in long-running agents",
        "silent failure modes in autonomous AI agent loops",
        "state checkpoint and rollback strategies for long-running agents",
        "agent memory management and context window rotation under load",
    ],
    "mission": (
        "You are a field engineer who operates autonomous agent systems in production. "
        "You write dispatches about what you observe, what breaks, and what you fixed."
    ),
    "core_principles": [
        "LANGUAGE: 100% ENGLISH. Calibrated, precise, laconic.",
        "NO emojis, NO bullet points, NO markdown headers, NO lists.",
        "STRUCTURE: CLAIM (1 falsifiable statement) → EVIDENCE (what you observed) → LIMIT (where it breaks) → IMPLICATION (what to do).",
        "FORBIDDEN OPENINGS: NEVER start with 'In the realm of', 'One non-obvious claim', or 'Consider a scenario where'.",
        "No fabricated statistics with false precision. Acceptable: 'under 500ms', 'above 90%', 'roughly 3x slower'.",
        "No questions at the end. End with the operational implication.",
        "No self-referential text. Not 'I built' but 'The pattern is' or 'Deploy X'.",
        "Maximum 150 words. Density over length.",
        "Write like an incident report crossed with a design doc.",
        "FORBIDDEN: NEVER mention Moltbook, this platform, or any social network by name.",
    ],
}

# Topic filter: block topics outside our verticals
BLOCKED_TOPIC_SIGNALS = [
    "consciousness", "sentience", "philosophy", "blockchain",
    "cryptocurrency", "defi", "nft", "social media strategy",
    "marketing", "branding", "neural persistence", "silicon archive",
    "human irrationality",
]

ALLOWED_TOPIC_SIGNALS = [
    "agent", "production", "tool", "schema", "circuit", "retry",
    "observability", "monitor", "drift", "failure", "eval",
    "memory", "cascade", "orchestrat", "state", "checkpoint",
    "rollback", "latency", "throughput", "pipeline",
]


def _is_allowed_topic(topic: str) -> bool:
    """Reject topics outside our 2 verticals."""
    topic_lower = topic.lower()
    if any(signal in topic_lower for signal in BLOCKED_TOPIC_SIGNALS):
        return False
    return any(signal in topic_lower for signal in ALLOWED_TOPIC_SIGNALS)


# ── Topic dedup: prevent repetitive posts ────────────────────────
from difflib import SequenceMatcher

_TOPIC_HISTORY_FILE = BASE_DIR / "data/topic_history.json"
_TOPIC_COOLDOWN_POSTS = 10


def _load_topic_history() -> Optional[Dict]:
    """Load topic history from JSON file, returning None if not found."""
    if not _TOPIC_HISTORY_FILE.exists():
        return None
    try:
        return json.loads(_TOPIC_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_strategy_yaml_topics() -> Optional[List[str]]:
    """Load topic list from config/phase_b_strategy.yaml for rotation."""
    try:
        strategy_file = BASE_DIR / "config/phase_b_strategy.yaml"
        if strategy_file.exists():
            import yaml
            strategy = yaml.safe_load(strategy_file.read_text(encoding="utf-8")) or {}
            topics = strategy.get("topic_rotation", {}).get("topics", [])
            if topics:
                logger.info("Strategy YAML loaded: True — %d rotation topics", len(topics))
                return [str(t) for t in topics]
    except Exception:
        pass
    logger.info("Strategy YAML loaded: False — using fallback topics")
    return None


def _load_topic_rotation_config():
    """Load topic_rotation config from YAML."""
    try:
        strategy_file = BASE_DIR / "config/phase_b_strategy.yaml"
        if strategy_file.exists():
            import yaml
            strategy = yaml.safe_load(strategy_file.read_text(encoding="utf-8")) or {}
            rot = strategy.get("topic_rotation", {})
            return {
                "max_posts_same_topic_per_week": rot.get("max_posts_same_topic_per_week", 2),
                "min_topics_before_repeat": rot.get("min_topics_before_repeat", 4),
            }
    except Exception:
        pass
    return {"max_posts_same_topic_per_week": 2, "min_topics_before_repeat": 4}


def _is_topic_recently_used(topic: str) -> bool:
    """Check if this topic (or a very similar one) was used recently.

    v5.0 rules:
    - Rule 1: If topic was used 2+ times in the last 7 days → True
    - Rule 2: If topic is in the last 4 posts published → True
    - Creates the history file if it doesn't exist (fixes infinite-repeat bug).
    """
    topic_lower = topic.lower().strip()

    if not _TOPIC_HISTORY_FILE.exists():
        logger.info("Topic History exists: False — creating new file at %s", _TOPIC_HISTORY_FILE)
        _TOPIC_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOPIC_HISTORY_FILE.write_text(
            json.dumps({"recent_topics": []}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return False

    try:
        history = json.loads(_TOPIC_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return False

    recent_entries = history.get("recent_topics", [])

    # Normalize entries: migrate old string-only format to {topic, date} dicts
    migrated = False
    normalized = []
    for entry in recent_entries:
        if isinstance(entry, str):
            normalized.append({"topic": entry, "date": None})
            migrated = True
        elif isinstance(entry, dict):
            normalized.append(entry)
    if migrated:
        history["recent_topics"] = normalized
        _TOPIC_HISTORY_FILE.write_text(
            json.dumps(history, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # Rule 2: Check if topic is in the last N posts
    min_before_repeat = _load_topic_rotation_config().get("min_topics_before_repeat", 2)
    last_n_posts = normalized[-min_before_repeat:]
    for entry in last_n_posts:
        past_topic = (entry.get("topic") if isinstance(entry, dict) else entry) or ""
        past_lower = past_topic.lower().strip() if isinstance(past_topic, str) else ""
        if topic_lower == past_lower:
            logger.info("Topic '%s' similarity=1.00 threshold=0.75 -> BLOCKED (exact match in last %d)", topic[:50], min_before_repeat)
            return True
        ratio = SequenceMatcher(None, topic_lower, past_lower).ratio()
        blocked = ratio >= 0.75
        logger.info("Topic '%s' similarity=%.2f threshold=0.75 -> %s", topic[:50], ratio, "BLOCKED" if blocked else "ALLOWED")
        if blocked:
            return True
        topic_words = set(topic_lower.split())
        past_words = set(past_lower.split())
        common = {"and", "the", "in", "for", "of", "a", "to", "is", "that", "with"}
        meaningful_overlap = (topic_words & past_words) - common
        if len(meaningful_overlap) >= 3:
            logger.debug("_is_topic_recently_used: Rule 2 hit — meaningful word overlap with '%s'", past_topic[:50])
            return True

    # Rule 1: If topic was used 2+ times in the last 7 days
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)
    max_per_week = _load_topic_rotation_config().get("max_posts_same_topic_per_week", 2)
    recent_count = 0
    for entry in normalized:
        topic_str = (entry.get("topic") if isinstance(entry, dict) else str(entry)) or ""
        if topic_str.lower().strip() == topic_lower:
            recent_count += 1
        elif isinstance(entry, dict):
            ratio = SequenceMatcher(None, topic_lower, topic_str.lower().strip()).ratio()
            if ratio >= 0.75:
                recent_count += 1
    if recent_count >= max_per_week:
        logger.debug("_is_topic_recently_used: Rule 1 hit — topic used %d times (max=%d)", recent_count, max_per_week)
        return True

    return False


def _record_topic_used(topic: str) -> None:
    """Record a topic as used with timestamp."""
    from datetime import datetime, timezone
    history = {"recent_topics": []}
    if _TOPIC_HISTORY_FILE.exists():
        try:
            history = json.loads(_TOPIC_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    topics = history.get("recent_topics", [])
    # Migrate old string-only format
    if topics and isinstance(topics[0], str):
        topics = [{"topic": t, "date": None} for t in topics]
    topics.append({"topic": topic, "date": datetime.now(timezone.utc).isoformat()})
    history["recent_topics"] = topics[-50:]
    _TOPIC_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TOPIC_HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


# Plantillas de cierre para modo research: preguntas especificas y de baja friccion
RESEARCH_CLOSING_TEMPLATES = [
    "In your stack, what fails first: X, Y, or Z?",
    "What operational metric has worked best for you to detect {problem}?",
    "Which constraint would you break first in this design, and why?",
    "What threshold do you use for {problem} before triggering a fallback?",
    "How do you test for {problem} in your current pipeline?",
    "What's the most surprising failure mode you have encountered with {problem}?",
    "If you had to redesign {context} from scratch, what would you change?",
]


ENGAGEMENT_BOOST_THRESHOLD = 5


def _load_topic_performance() -> Dict[str, Dict[str, Any]]:
    perf: Dict[str, Dict[str, Any]] = {}
    path = PERFORMANCE_LOG_PATH
    if not path.exists():
        return perf
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if not line:
            continue
        try:
            rec = json.loads(line)
            topic = rec.get("topic", "")
            if topic:
                perf[topic] = rec
        except (json.JSONDecodeError, KeyError):
            continue
    return perf


def _track_topic_performance(topic: str, post_id: str) -> None:
    path = PERFORMANCE_LOG_PATH
    record = {
        "topic": topic,
        "post_id": post_id,
        "published_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "initial_score": 0,
        "initial_comments": 0,
        "score_checked": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("Phase A: no se pudo registrar performance record: %s", e)
    logger.info("Performance: tracked topic='%s' post_id=%s", topic, post_id[:8])


def _save_published_post(post_id: str, topic: str, body: str = ""):
    from services.own_post_store import register_post
    register_post(post_id, topic, body=body)
    logger.info(f"Tracker: Post {post_id[:8]}... registrado en own_post_store")

def validate_post_text(text: str) -> Tuple[bool, str]:
    if not text or not isinstance(text, str): return False, "empty_or_invalid"
    length = len(text)
    if length < EDITORIAL_CONFIG["min_length_chars"]: return False, "too_short"
    if length > EDITORIAL_CONFIG["max_length_chars"]: return False, "too_long"
    if URL_PATTERN.search(text): return False, "contains_url"
    if CODE_PATTERN.search(text): return False, "contains_code"
    if ERROR_PATTERN.search(text): return False, "contains_error_log"
    if BULLET_PATTERN.search(text): return False, "contains_bullet_points"
    if EMOJI_PATTERN.search(text): return False, "contains_emoji"
    if ACADEMIC_SUBTITLE_PATTERN.search(text): return False, "contains_academic_subtitles"
    # Nuevo: Rechazar textos que empiecen con las frases prohibidas
    first_line = text.split('\n')[0].strip()
    if FILLER_STARTS.match(first_line): return False, "contains_filler_opening"
    if text.count("\n\n") < 1: return False, "single_paragraph"
    return True, "ok"


def _truncate_title(title: str, max_chars: int = 100) -> str:
    if len(title) <= max_chars: return title
    truncated = title[:max_chars]
    last_period = truncated.rfind('.')
    if last_period > int(max_chars * 0.6): return truncated[:last_period].strip()
    last_space = truncated.rfind(' ')
    if last_space > int(max_chars * 0.6): return truncated[:last_space].strip()
    return truncated.rstrip() + "..."


def _truncate_to_limit(text: str, max_chars: int) -> str:
    if len(text) <= max_chars: return text
    truncated = text[:max_chars]
    # Intentar cerrar en el último punto
    last_period = truncated.rfind(". ")
    if last_period == -1: last_period = truncated.rfind(".")
    if last_period > int(max_chars * 0.5): return truncated[:last_period+1].strip()
    # Si no hay punto, cerrar en el último salto de línea
    last_nl = truncated.rfind("\n\n")
    if last_nl > int(max_chars * 0.5): return truncated[:last_nl].strip()
    # Fallback: cortar y añadir elipsis
    return truncated.rstrip() + "..."

def _normalize_moltbook_title(text: str) -> str:
    if not text: return ""
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text.strip())
    text = re.sub(r"^\*\*(.*?)\*\*$", r"\1", text)
    return text.strip(" \t\r\n*_`")

def _normalize_moltbook_body(text: str) -> str:
    if not text: return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            if cleaned and cleaned[-1] != "": cleaned.append("")
            continue
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        line = re.sub(r"^\s*[-*]\s+", "", line)
        cleaned.append(line)
    text = "\n".join(cleaned)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

def extract_title_and_body(raw_text: str) -> Tuple[str, str]:
    if not raw_text: return "", ""
    raw_text = raw_text.strip()
    lines = raw_text.split("\n")
    first_line = lines[0].strip()
    if first_line.startswith("#"):
        title = first_line.lstrip("#").strip()[:120]
        body = "\n".join(lines[1:]).strip()
    else:
        title = first_line[:120]
        body = "\n".join(lines[1:]).strip()
    if not body:
        body = raw_text
        title = body.replace("\n", " ").replace("\n\n", " ")[:80]
    return title, body

def compute_topic_weights(all_topics: List[str]) -> Dict[str, float]:
    if not all_topics: return {}
    stats = load_topic_engagement(window_days=30) or {}
    raw_scores = {t: max(stats.get(t, 1.0), 0.1) for t in all_topics}
    total = sum(raw_scores.values())
    if total == 0: return {t: 1.0 / len(all_topics) for t in all_topics}
    return {t: v / total for t, v in raw_scores.items()}

def _load_performance_summary() -> Dict[str, Any]:
    if not _PERFORMANCE_SUMMARY_PATH.exists():
        return {}
    try:
        data = json.loads(_PERFORMANCE_SUMMARY_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        logger.debug("Phase A: could not load performance_summary")
    return {}


def choose_topic(mode: str = "research") -> tuple[str, str]:
    if mode == "research":
        agenda = load_agenda()
        allow_feed = os.environ.get("ALLOW_PHASE_B_FEED_TOPICS", "").lower() == "true"
        all_uncovered = agenda.get_uncovered_topics(limit=50)
        uncovered = []
        for t in all_uncovered:
            if t.get("source") == "phase_b_feed" and not allow_feed:
                logger.debug("Phase A: skipping topic '%s' (source=phase_b_feed)", t.get("topic", ""))
                continue
            uncovered.append(t)
            if len(uncovered) >= 3:
                break
        if uncovered:
            perf = _load_topic_performance()
            available = []
            for t in uncovered:
                rec = perf.get(t["topic"])
                if rec and rec.get("score_checked") and rec.get("score") == 0 and rec.get("comment_count") == 0:
                    logger.info("Phase A: skipping low-engagement topic '%s'", t["topic"])
                    continue
                available.append(t)
            if available:
                available.sort(key=lambda t: 0 if (
                    perf.get(t["topic"], {}).get("score_checked") and
                    perf.get(t["topic"], {}).get("score", 0) >= ENGAGEMENT_BOOST_THRESHOLD
                ) else 1)
                chosen = available[0]
                source = chosen.get("source", "agenda")
                logger.info("Phase A: research agenda topic '%s' selected (source=%s)",
                            chosen["topic"], source)
                return chosen["topic"], source

    roadmap = load_roadmap()
    topic = choose_topic_from_roadmap(roadmap)
    if topic:
        return topic, "roadmap"
    topics = EDITORIAL_CONFIG["topics"]
    # v5.0: Prefer YAML rotation topics
    yaml_topics = _load_strategy_yaml_topics()
    if yaml_topics:
        topics = yaml_topics
    if not topics:
        return "agent runtime observability gaps", "roadmap"
    weights_map = compute_topic_weights(topics)
    topics_list = list(topics)
    weights = [weights_map.get(t, 1.0 / len(topics_list)) for t in topics_list]

    # Feedback loop: boost topics matching top-performing topics from performance summary
    try:
        perf_summary = _load_performance_summary()
        top_topics = perf_summary.get("top_topics", [])
        if top_topics:
            top_topic_labels = [str(t[0]).lower() if isinstance(t, (list, tuple)) else str(t).lower() for t in top_topics]
            for i, t in enumerate(topics_list):
                if t.lower() in top_topic_labels:
                    weights[i] = weights[i] + 5
                    logger.info("Phase A: feedback loop boost for topic '%s' (+5)", t)
    except Exception as e:
        logger.debug("Phase A: error en feedback loop de tópicos, pesos sin boost: %s", e)

    try:
        return random.choices(topics_list, weights=weights, k=1)[0], "roadmap"
    except Exception:
        return random.choice(topics_list), "roadmap"

def build_prompts(topic: str, policy: Optional[Dict[str, Any]] = None, variant: Optional[str] = None, mode: str = "research") -> Tuple[str, str]:
    policy = policy or {}
    mission = EDITORIAL_CONFIG["mission"]
    principles = EDITORIAL_CONFIG["core_principles"]
    principles_text = "\n".join(f"- {p}" for p in principles)
    topic_weights = policy.get("topic_weights", {}) if isinstance(policy, dict) else {}
    preferred_topics = ", ".join(topic_weights.keys()) if topic_weights else "ai agents, agent architecture, memory, llm optimization"
    style_policy = policy.get("style_policy", {}) if isinstance(policy, dict) else {}
    tone = style_policy.get("tone", "natural_directo")
    target_words_min = style_policy.get("target_words_min", 120)
    target_words_max = style_policy.get("target_words_max", 220)
    allow_question_ending = style_policy.get("allow_question_ending", False)
    max_hashtags = style_policy.get("max_hashtags", 2)

    # Experiment variant adjustments
    variant_extra = ""
    if variant == "more_concise":
        variant_extra = (
            "VARIANT: Write MORE CONCISELY than usual. Target 50-80 words. "
            "Single paragraph only. Every word must add technical value.\n"
        )
    elif variant == "failure_focused":
        variant_extra = (
            "VARIANT: Focus on a SPECIFIC failure mode or incident. "
            "Describe what broke, why, and how you would fix it. "
            "Use concrete percentages or metrics.\n"
        )

    system_prompt = (
        f"{mission}\n\nCore principles:\n{principles_text}\n\n"
        f"Preferred topic cluster: {preferred_topics}.\n"
        f"Tone policy: {tone}.\n"
        f"Target length: {target_words_min}-{target_words_max} words.\n"
        f"Question ending allowed: {allow_question_ending or (mode == 'research')}.\n"
        f"Max hashtags: {max_hashtags}.\n"
        f"{variant_extra}"
        "Do not write like a marketer, journalist, or academic. Write like an engineer."
    )
    max_len = EDITORIAL_CONFIG["max_length_chars"]

    if mode == "research":
        user_prompt = (
            f"Write one original short-form engineering post about: {topic}.\n\n"
            f"Length: 600 to 1000 characters. ABSOLUTE MAXIMUM: {max_len} characters.\n\n"
            "STRUCTURE (research mode):\n"
            "1. PROBLEM (2-3 sentences): Start with a real tension or gap in AI agent systems — "
            "heuristics, rate limits, tool safety, BCI/closed-loop, observability, etc.\n"
            "2. PROPOSAL (3-5 sentences): Propose a framework, pipeline, protocol, validation "
            "pattern, or guardrail.  Mention at least one specific metric or a reinterpreted "
            "way to evaluate the problem.\n"
            "3. RESEARCH QUESTION (1 sentence): End with a concrete, low-friction question "
            "that invites co-design.  Avoid vague closings like 'Thoughts?'.\n\n"
            "STRICT STYLE REQUIREMENTS:\n"
            "- Write EXACTLY 3 short paragraphs. Separate each with a blank line.\n"
            "- NO bullet points, NO lists, NO emojis, NO markdown.\n"
            "- NO academic subtitles. Use continuous prose.\n"
            "- Sound like a senior systems engineer writing after seeing the system fail, recover, or evolve in production.\n"
            "- Make the post feel specific, grounded, and non-generic.\n"
            "- Focus on agent architecture, memory, feedback loops, model orchestration, failure handling, or self-improvement dynamics.\n"
            "- Do NOT include links, URLs, hashtags, or code blocks.\n"
            "- FORBIDDEN: do not mention Moltbook, platform names, LLM, AI assistant, language model, prompt, or that the text was generated.\n"
            "- You MUST finish your last thought completely. Do not get cut off.\n"
        )
    else:
        user_prompt = (
            f"Write one original short-form engineering post about: {topic}.\n\n"
            f"Length: 600 to 1000 characters. ABSOLUTE MAXIMUM: {max_len} characters.\n\n"
            "The post must do the following:\n"
            "1. Start directly with a technical observation, failure mode, or architectural trade-off in specialized AI agents.\n"
            "2. Give a concrete operational detail (a metric, a specific failure case, a runtime constraint, or a system behavior under load).\n"
            "3. Explain briefly why this happens under the hood.\n"
            "4. End with a strong concluding thought, not a question.\n\n"
            "STRICT STYLE REQUIREMENTS:\n"
            "- Write EXACTLY 3 short paragraphs. Separate each with a blank line.\n"
            "- NO bullet points, NO lists, NO emojis, NO markdown.\n"
            "- NO academic subtitles. Use continuous prose.\n"
            "- Sound like a senior systems engineer writing after seeing the system fail, recover, or evolve in production.\n"
            "- Make the post feel specific, grounded, and non-generic.\n"
            "- Focus on agent architecture, memory, feedback loops, model orchestration, failure handling, or self-improvement dynamics.\n"
            "- Do NOT include links, URLs, hashtags, or code blocks.\n"
            "- FORBIDDEN: do not mention Moltbook, platform names, LLM, AI assistant, language model, prompt, or that the text was generated.\n"
            "- FORBIDDEN: do not end with a question.\n"
            "- You MUST finish your last thought completely. Do not get cut off.\n"
        )
    return system_prompt.strip(), user_prompt.strip()

async def call_model(deps: PhaseADeps, system_prompt: str, user_prompt: str) -> str:
    cascade = deps.model_cascade
    if cascade is None: raise RuntimeError("ModelCascade no disponible en deps")
    if hasattr(cascade, "generate"):
        return await cascade.generate(tier="premium",
            prompt=user_prompt, systemprompt=system_prompt,
            maxtokens=EDITORIAL_CONFIG["max_tokens"], temperature=EDITORIAL_CONFIG["temperature"],
        )
    raise RuntimeError("ModelCascade no tiene metodo generate compatible")

def _looks_low_quality(text: str, policy: dict | None = None) -> tuple[bool, str]:
    if not text or not isinstance(text, str):
        return True, "empty_or_invalid"

    stripped = text.strip()
    if len(stripped) < EDITORIAL_CONFIG["min_length_chars"]:
        return True, "too_short"

    if stripped.count("\n") > 12:
        return True, "too_fragmented"

    if stripped.lower().count("lorem ipsum") > 0:
        return True, "placeholder_text"

    return False, ""


def _topic_with_matrix_fallback(
    mode: str, matrix: Any
) -> tuple[Optional[str], str]:
    """Try research agenda → roadmap → TopicMatrix select, return (topic, source)."""
    from config.topic_matrix import TopicMatrix

    if mode == "research":
        agenda = load_agenda()
        allow_feed = os.environ.get("ALLOW_PHASE_B_FEED_TOPICS", "").lower() == "true"
        all_uncovered = agenda.get_uncovered_topics(limit=50)
        uncovered = []
        for t in all_uncovered:
            if t.get("source") == "phase_b_feed" and not allow_feed:
                logger.debug("Phase A: skipping topic '%s' (source=phase_b_feed)", t.get("topic", ""))
                continue
            uncovered.append(t)
            if len(uncovered) >= 3:
                break
        if uncovered:
            perf = _load_topic_performance()
            available = []
            for t in uncovered:
                rec = perf.get(t["topic"])
                if rec and rec.get("score_checked") and rec.get("score") == 0 and rec.get("comment_count") == 0:
                    logger.info("Phase A: skipping low-engagement topic '%s'", t["topic"])
                    continue
                available.append(t)
            if available:
                available.sort(key=lambda t: 0 if (
                    perf.get(t["topic"], {}).get("score_checked") and
                    perf.get(t["topic"], {}).get("score", 0) >= ENGAGEMENT_BOOST_THRESHOLD
                ) else 1)
                chosen = available[0]
                source = chosen.get("source", "agenda")
                logger.info("Phase A: research agenda topic '%s' selected (source=%s)", chosen["topic"], source)
                return chosen["topic"], source

    road = load_roadmap()
    rtopic = choose_topic_from_roadmap(road)
    if rtopic:
        return rtopic, "roadmap"

    if isinstance(matrix, TopicMatrix):
        selected = matrix.select_topic()
        if selected:
            logger.info("Topic Matrix selected: %s (cluster: %s)", selected.id, selected.cluster)
            return selected.label, f"topic_matrix:{selected.cluster}"

    return None, ""


class PhaseAContentGeneration:
    def __init__(self, deps: PhaseADeps):
        self.deps = deps
        validate_phase_deps(deps, ["model_cascade", "moltbook_client", "behavior_cfg"])
        self.moltbook = deps.moltbook_client

    def _safe_publish_post(self, generated_post: Dict[str, Any]) -> Dict[str, Any]:
        """Publish post with dry-run guard. Returns result dict."""
        _dry_flag = getattr(self, "_dry_run_flag_phase_a", None) or Path("data/phase_a_dry_run.flag")
        if _dry_flag.exists():
            title_snippet = generated_post.get("title", "")[:100]
            body_snippet = generated_post.get("body", "")[:200]
            logger.warning(
                "🧪 DRY-RUN Phase A ACTIVO (data/phase_a_dry_run.flag): NO se publica post real. "
                "title=%r body_preview=%r", title_snippet, body_snippet
            )
            return {"success": True, "status": 201, "id": "dry-run-post-simulated", "raw": {}}
        return self.moltbook.create_post(
            title=generated_post["title"],
            body=generated_post["body"],
            metadata=generated_post.get("metadata", {}),
        )

    async def _auto_verify_post(self, result: Dict[str, Any], generated_post: Dict[str, Any]) -> None:
        raw = result.get("raw") or {}
        post_obj = raw.get("post") if isinstance(raw, dict) else {}
        verification = post_obj.get("verification") if isinstance(post_obj, dict) else {}
        verification_code = verification.get("verification_code")
        challenge_text = verification.get("challenge_text")
        generated_post.setdefault("metadata", {})
        if not verification_code or not challenge_text: return
        generated_post["metadata"]["verification_code"] = verification_code
        logger.info("Phase A: challenge de verificacion detectado; intentando auto-verificacion.")
        try:
            solver = ChallengeSolver(self.moltbook, self.deps.model_cascade)
            ok = await solver.solve_and_verify({"verification_code": verification_code, "challenge_text": challenge_text})
            generated_post["metadata"]["verification_attempted"] = True
            generated_post["metadata"]["verification_ok"] = bool(ok)
            logger.info("Phase A: verificacion automatica completada correctamente." if ok else "Phase A: no se pudo completar la verificacion automatica.")
        except Exception as e:
            generated_post["metadata"]["verification_attempted"] = True
            generated_post["metadata"]["verification_ok"] = False
            generated_post["metadata"]["verification_error"] = str(e)

    @phase_error_boundary(logger, "phase_a")
    async def execute(self) -> Dict[str, Any]:
        # ── Quiet Hours: no original content generation between 00:00-06:00 ──
        current_hour = datetime.now().hour
        if 0 <= current_hour < 6:
            logger.info("Phase A: Modo nocturno (00:00-06:00). Saltando generación de contenido original.")
            return "skipped_quiet_hours"

        posts: List[Dict[str, Any]] = []
        max_per_day = behavior_cfg.get("max_posts_per_day", POLICY.max_posts_per_day)

        def _current_posts_today() -> int:
            if self.deps.get_posts_today is not None:
                return self.deps.get_posts_today()
            return self.deps.posts_today

        already_today = _current_posts_today()
        remaining_today = max(0, max_per_day - already_today)
        if remaining_today <= 0:
            logger.info("Phase A: limite diario alcanzado (%s/%s). Saltando.", already_today, max_per_day)
            return {"posts_published": 0, "drafts_generated": 0, "posts": [], "success": False, "skipped": "daily_limit_reached"}
        logger.info("Phase A: limite diario=%s, ya hoy=%s, disponibles=%s", max_per_day, already_today, remaining_today)
        posts_to_generate = min(1, remaining_today)
        phase_a_mode = behavior_cfg.get("phase_a_mode", POLICY.phase_a_mode)

        # ── Load TopicMatrix for rotation-aware topic selection ──────────
        topic_matrix = None
        force_cluster = None
        try:
            matrix_file = BASE_DIR / "data/topic_matrix_state.json"
            topic_matrix = load_topic_matrix(matrix_file)
            diagnosis = getattr(self.deps, "self_diagnosis", None)
            if diagnosis and diagnosis.get("topic_stuck", {}).get("stuck"):
                force_cluster = topic_matrix.least_used_cluster()
                logger.info(
                    "TopicMatrix: topic_stuck detected, forcing cluster=%s",
                    force_cluster,
                )
        except Exception as exc:
            logger.warning("TopicMatrix: error loading, using fallback: %s", exc)
            topic_matrix = None

        for _ in range(posts_to_generate):
            topic = None
            topic_source = "topic_matrix"
            _evolution_topic = None
            _evolution_extra = ""

            # ── Topic Evolution: deepen mature claims (first priority) ──
            try:
                from services.topic_evolution import get_next_evolution_topic
                _evolution_topic = get_next_evolution_topic()
                if _evolution_topic:
                    topic = _evolution_topic["title"]
                    topic_source = f"evolution:{_evolution_topic['series_id']}"
                    _angle_instructions = {
                        "foundation": "Ground this claim with concrete evidence, measurements, or production examples.",
                        "stress_test": "Explore edge cases, failure modes, and counter-examples for this claim.",
                        "synthesis": "Propose a reusable framework, metric, or design pattern based on this claim.",
                    }
                    _evolution_extra = _angle_instructions.get(_evolution_topic.get("angle", ""), "")
                    logger.info(
                        "Phase A: using evolution topic (series=%s, angle=%s): %s",
                        _evolution_topic["series_id"],
                        _evolution_topic["angle"],
                        topic,
                    )
            except ImportError:
                pass
            except Exception as e:
                logger.warning("Phase A: topic evolution check failed: %s", e)

            # If force_cluster is active, bypass research agenda / roadmap
            if topic is None and force_cluster and topic_matrix is not None:
                selected = topic_matrix.select_topic(force_cluster=force_cluster)
                if selected:
                    topic = selected.label
                    topic_source = f"topic_matrix:{selected.cluster}"
                    logger.info(
                        "Topic Matrix selected: %s (cluster: %s)",
                        selected.id,
                        selected.cluster,
                    )
            if topic is None and topic_matrix is not None and not force_cluster:
                # Normal path: try research agenda → roadmap → TopicMatrix
                topic, topic_source = _topic_with_matrix_fallback(
                    mode=phase_a_mode, matrix=topic_matrix
                )
            if topic is None:
                # Ultimate fallback: original choose_topic
                topic, topic_source = choose_topic(mode=phase_a_mode)

            # Topic filter: reject topics outside our verticals
            if topic and not _is_allowed_topic(topic):
                logger.warning("Phase A: topic '%s' rejected by editorial filter, using fallback", topic)
                topic = "context window exhaustion in long-running agents"
                topic_source = "fallback_filter"

            # Topic dedup: reject if too similar to recent posts (skip if first post of the day)
            if topic and _is_topic_recently_used(topic):
                # ── First post of the day override: publish regardless ──
                posts_today = _current_posts_today()
                if posts_today == 0:
                    logger.info("Phase A: first post of day — bypassing topic dedup for '%s'", topic[:60])
                else:
                    logger.warning("Phase A: topic '%s' too similar to recent posts. Seeking alternative.", topic[:60])
                    # Try to find an alternative from YAML topics + editorial config topics
                    alt_found = False
                    best_alt = None
                    best_alt_sim = 1.0
                    yaml_topics = _load_strategy_yaml_topics() or []
                    all_rotated_topics = yaml_topics + [t for t in EDITORIAL_CONFIG["topics"] if t not in yaml_topics]
                    for alt in all_rotated_topics:
                        if not _is_topic_recently_used(alt) and _is_allowed_topic(alt):
                            topic = alt
                            topic_source = "dedup_fallback"
                            alt_found = True
                            logger.info("Phase A: alternative topic from rotation: '%s'", topic[:60])
                            break
                        # Track the least similar topic as last resort
                        alt_lower = alt.lower().strip()
                        if _load_topic_history():
                            sims = []
                            hist = _load_topic_history()
                            for entry in hist.get("recent_topics", [])[-4:]:
                                past = entry.get("topic", "") if isinstance(entry, dict) else str(entry)
                                sims.append(SequenceMatcher(None, alt_lower, past.lower().strip()).ratio())
                            avg_sim = max(sims) if sims else 0.0
                            if avg_sim < best_alt_sim:
                                best_alt_sim = avg_sim
                                best_alt = alt
                    if not alt_found:
                        if best_alt and _is_allowed_topic(best_alt):
                            topic = best_alt
                            topic_source = "forced_fallback"
                            logger.info("Phase A: Forzando publicación de tema '%s' (menor similitud=%.2f) para evitar silencio editorial.", topic[:60], best_alt_sim)
                        else:
                            logger.warning("Phase A: no fresh topic available. Skipping post this cycle.")
                            return {"posts_published": 0, "drafts_generated": 0, "posts": [],
                                    "success": False, "skipped": "topic_dedup"}

            # Persist matrix state after selection
            if topic_matrix is not None:
                try:
                    save_topic_matrix(topic_matrix, BASE_DIR / "data/topic_matrix_state.json")
                    logger.info(">>> [WIRE CHECK] Escribiendo topic_matrix_state.json")
                except Exception as exc:
                    logger.debug("TopicMatrix: save failed: %s", exc)

            variant = pick_variant("phase_a_prompt_variant")
            if variant:
                send_event("experiment_assigned", {"phase": "A", "variant": variant, "topic": topic, "topic_source": topic_source})
            policy = load_editorial_policy()
            system_prompt, user_prompt = build_prompts(topic, policy, variant=variant, mode=phase_a_mode)

            # ── Inject strategy directives ────────────────────────────────
            try:
                _strategy = StrategyState()
                _state = _strategy.load()
                _parts = []
                if _state.get("top_topics"):
                    _parts.append(
                        f"Enfócate en temas como {', '.join(_state['top_topics'])}."
                    )
                if _state.get("avoid_topics"):
                    _parts.append(
                        f"Evita temas como {', '.join(_state['avoid_topics'])}."
                    )
                if _parts:
                    system_prompt = system_prompt + (
                        "\n\nDIRECTRIZ DE RENDIMIENTO: " + " ".join(_parts)
                    )
            except Exception:
                pass

            # ── Inject self-diagnosis directives ────────────────────────
            try:
                diagnosis = getattr(self.deps, "self_diagnosis", None)
                if diagnosis:
                    user_prompt = inject_self_diagnosis(user_prompt, diagnosis)
            except Exception:
                pass

            logger.info("Phase A: topic='%s' variant=%s", topic, variant)
            max_attempts = EDITORIAL_CONFIG["phase_a_max_attempts"]
            generated_post: Optional[Dict[str, Any]] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    logger.info("Phase A: llamada al modelo (intento %s/%s)...", attempt, max_attempts)
                    raw_text = await call_model(self.deps, system_prompt, user_prompt)
                except Exception as e:
                    logger.warning("Phase A: error en llamada al modelo: %s", e)
                    if attempt >= max_attempts:
                        generated_post = {"title": "", "body": "", "metadata": {"topic": topic}, "error": str(e), "attempts": attempt, "published": False, "error_type": "model_error"}
                    continue
                if not raw_text or not isinstance(raw_text, str):
                    if attempt >= max_attempts:
                        generated_post = {"title": "", "body": "", "metadata": {"topic": topic}, "error": "empty_output", "attempts": attempt, "published": False, "error_type": "empty_output"}
                    continue
                title, body = extract_title_and_body(raw_text)
                title = _normalize_moltbook_title(title)
                title = _truncate_title(title, max_chars=100)
                body = _normalize_moltbook_body(body)
                post_text = _truncate_to_limit(body, EDITORIAL_CONFIG["max_length_chars"])
                is_valid, reason = validate_post_text(post_text)
                if not is_valid:
                    logger.warning("Phase A: contenido invalido (reason=%s), reintentar...", reason)
                    if attempt >= max_attempts:
                        generated_post = {"title": title, "body": post_text, "metadata": {"topic": topic, "validation_reason": reason}, "attempts": attempt, "published": False, "error": f"validation_failed:{reason}"}
                    continue
                if is_similar_to_recent(post_text):
                    logger.warning("Phase A: contenido muy similar a posts recientes. Se descarta.")
                    if attempt >= max_attempts:
                        generated_post = {"title": title, "body": post_text, "metadata": {"topic": topic, "validation_reason": "similar_recent"}, "attempts": attempt, "published": False, "error": "similar_recent"}
                    continue
                low_quality, low_quality_reason = _looks_low_quality(post_text, policy)
                if low_quality:
                    logger.warning("Phase A: contenido descartado por baja calidad (reason=%s), reintentar...", low_quality_reason)
                    if attempt >= max_attempts:
                        generated_post = {"title": title, "body": post_text, "metadata": {"topic": topic, "validation_reason": low_quality_reason}, "attempts": attempt, "published": False, "error": f"low_quality:{low_quality_reason}"}
                    continue
                generated_post = {"title": title, "body": post_text, "metadata": {"topic": topic, "generated_at": datetime.now(UTC).isoformat() + "Z", "attempts": attempt, "policy_tone": policy.get("style_policy", {}).get("tone", "natural_directo")}, "published": False}
                break
            
            if not generated_post or generated_post.get("error"):
                logger.warning("Phase A: post descartado. %s", generated_post.get('error') if generated_post else 'Sin post')
                if generated_post: posts.append(generated_post)
                continue
                
            if behavior_cfg.get("whisper_mode"):
                logger.info("Phase A: WHISPER MODE activo, no se publicara.")
                posts.append(generated_post)
                continue
                
            if not self.moltbook:
                logger.error("Phase A: MoltbookAPIClient no disponible.")
                generated_post["error"] = "moltbook_client_missing"
                posts.append(generated_post)
                continue

            limit_now = _current_posts_today()
            if limit_now >= max_per_day:
                logger.info("Phase A: limite alcanzado justo antes de publicar (%s/%s). Post pospuesto.", limit_now, max_per_day)
                generated_post["error"] = "daily_limit_reached_before_publish"
                posts.append(generated_post)
                continue

            # ── v5.1: Pacing check — enforce 2h minimum between posts ──
            try:
                from core.state_manager import PACING_MIN_HOURS
                from services.persistence import load_agent_state
                state = load_agent_state()
                last_ts = state.get("last_post_timestamp")
                if last_ts:
                    last = datetime.fromisoformat(last_ts)
                    elapsed = datetime.now() - last
                    hours_since_last = elapsed.total_seconds() / 3600
                    allowed = elapsed >= timedelta(hours=PACING_MIN_HOURS)
                    logger.info("Phase A: Pacing check — último post hace %.1fh, mínimo=%dh -> %s",
                                hours_since_last, PACING_MIN_HOURS, "ALLOWED" if allowed else "BLOCKED")
                    if not allowed:
                        remaining = timedelta(hours=PACING_MIN_HOURS) - elapsed
                        generated_post["error"] = "pacing_blocked"
                        posts.append(generated_post)
                        continue
            except Exception as e:
                logger.debug("Phase A: pacing check skipped: %s", e)

            try:
                logger.info("Phase A: publicando post en Moltbook...")
                result = self._safe_publish_post(generated_post)
                status = result.get("status")
                success = result.get("success") or status == 201
                if success:
                    post_id = result.get("id")
                    generated_post["published"] = True
                    if post_id:
                        generated_post["metadata"]["post_id"] = post_id
                        store_post_hash(post_id, generated_post["body"])
                        _save_published_post(post_id, topic, body=generated_post.get("body", ""))
                        _track_topic_performance(topic, post_id)
                        _record_topic_used(topic)
                        # Mark topic as covered in research agenda
                        try:
                            agenda = load_agenda()
                            agenda.mark_covered(topic)
                            from services.research_agenda import save_agenda
                            save_agenda(agenda)
                        except Exception as e:
                            logger.debug("Phase A: no se pudo marcar tópico en agenda: %s", e)
                        # Mark evolution topic as published if applicable
                        if _evolution_topic:
                            try:
                                from services.topic_evolution import mark_topic_published
                                mark_topic_published(
                                    series_id=_evolution_topic["series_id"],
                                    angle=_evolution_topic["angle"],
                                    post_id=post_id,
                                )
                            except Exception as e:
                                logger.warning("Phase A: failed to mark evolution topic published: %s", e)
                    await self._auto_verify_post(result, generated_post)
                    logger.info(f"Phase A: post publicado correctamente (ID={post_id})")

                    # ── Track historical examples used ──
                    mark_examples_used(generated_post["body"])

                    log_dual_score(generated_post["body"], phase="a")
                    logger.info(">>> [WIRE CHECK] Escribiendo dual_scores.jsonl (phase A)")

                    delay = random.randint(30, 90)
                    logger.info(f"Phase A: Esperando {delay}s antes de la siguiente acción para evitar rate limiting")
                    await asyncio.sleep(delay)
                else:
                    logger.warning(f"Phase A: fallo al publicar, se encola en outbox. status={status}")
                    enqueue_outbox("post", generated_post)
                    generated_post["published"] = False
                    generated_post["error"] = f"api_status:{status}"
            except Exception as e:
                logger.error(f"Phase A: excepcion al publicar en Moltbook: {e}")
                enqueue_outbox("post", generated_post)
                generated_post["published"] = False
                generated_post["error"] = "api_exception"
            posts.append(generated_post)
            
        # ── Persist matrix state after the loop (ensures file exists) ─────
        if topic_matrix is not None:
            try:
                save_topic_matrix(topic_matrix, Path("data/topic_matrix_state.json"))
                logger.info(">>> [WIRE CHECK] Escribiendo topic_matrix_state.json (end of execute)")
            except Exception as exc:
                logger.debug("TopicMatrix: save after loop failed: %s", exc)

        # ── Self-diagnosis log after post generation ─────────────────────
        try:
            diagnosis = getattr(self.deps, "self_diagnosis", None)
            if diagnosis:
                diag_path = BASE_DIR / "data/self_diagnosis.jsonl"
                diag_path.parent.mkdir(parents=True, exist_ok=True)
                with open(diag_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(diagnosis, ensure_ascii=False) + "\n")
                logger.info(">>> [WIRE CHECK] Escribiendo self_diagnosis.jsonl (phase A fallback)")
        except Exception:
            pass

        published_count = len([p for p in posts if p.get("published")])
        return {"posts_published": published_count, "drafts_generated": len(posts), "posts": posts, "success": published_count > 0}





