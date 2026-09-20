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
import zoneinfo
import os
import time
import logging
import random
import re
from datetime import datetime, timezone, UTC, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import behavior_cfg, BASE_DIR
from config.schedule import get_quiet_hours, get_post_hours, get_max_posts_per_day
from config.agent_policy import POLICY
from config.topic_matrix import load_topic_matrix, save_topic_matrix
from config.niche_prompts import NICHE_PROMPTS
from core.observability import send_event
from phases.deps import PhaseADeps
from services.challenge_solver import ChallengeSolver
from services.model_router import call_model_with_fallback  # Groq fallback para classify
from services.experiments import load_experiments, pick_variant, get_variant_config
from services.roadmap import load_roadmap, choose_topic_from_roadmap, save_roadmap
from services.research_agenda import load_agenda, ResearchAgenda
from core.strategy_state import StrategyState
from prompts.prompt_templates import inject_self_diagnosis
from utils.phase_utils import phase_error_boundary, validate_phase_deps
from services.editorial_policy import load_editorial_policy
from services.dual_scoring import compute_dual_score, log_dual_score, _count_signals
from services.incident_store import (
    get_incident_by_id,
    mark_incident_used,
    extract_incident_figures,
)
from services.abstain_tracker import record_abstain
from services.used_examples_tracker import mark_examples_used
from services.persistence import (
    enqueue_outbox,
    is_similar_to_recent,
    store_post_hash,
    load_topic_engagement,
)
from services.quality_governor import text_has_reasoning_leak, title_has_scaffold, text_template_fatigue
from phases.phase_b.scoring import text_has_fabricated_measurement, text_has_unverifiable_historical_claim

logger = logging.getLogger("phases.phase_a_content")

PERFORMANCE_LOG_PATH = BASE_DIR / "data/topic_performance.jsonl"
_PERFORMANCE_SUMMARY_PATH = BASE_DIR / "data/performance_summary.json"



# Patrones de rechazo estricto (Anti-Spam Moltbook)
URL_PATTERN = re.compile(r"https?://|www\.", re.IGNORECASE)
CODE_PATTERN = re.compile(
    r"def\s+\w+\s*\(|"          # def foo(
    r"class\s+\w+\s*[:\(]|"     # class Foo:  o  class Foo(
    r"import\s+\w|"             # import x
    r"async\s+def|"            # async def
    r"```",                     # fenced code block
    re.MULTILINE,
)
# Fix 5: exige FORMA de log/excepcion (no la palabra suelta "exception" en prosa).
# Sin IGNORECASE: los nombres reales de excepcion van en PascalCase.
ERROR_PATTERN = re.compile(r"Traceback \(most recent call last\)|^\s*raise\s+\w+|\b[A-Z]\w*(Error|Exception):", re.MULTILINE)
BULLET_PATTERN = re.compile(r"^\s*[-*•]\s+", re.MULTILINE)
EMOJI_PATTERN = re.compile(r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF]", re.UNICODE)
# Fix 5: rebota subtitulo real -> dos puntos ("Abstract:") O palabra sola en su
# linea ("Abstract\n\n..."), via \s*(:|$) con MULTILINE. Deja pasar prosa que
# empieza con esas palabras seguidas de mas texto ("Claim verification is hard.").
ACADEMIC_SUBTITLE_PATTERN = re.compile(r"^\s*(Abstract|Claim|Introduction|Conclusion|Failure Case|Discussion|Methodology)\s*(:|$)", re.IGNORECASE | re.MULTILINE)
FILLER_STARTS = re.compile(r"^(In the realm of|One non-obvious|Consider a scenario where)", re.IGNORECASE)

EDITORIAL_CONFIG = {
    "language": "en",
    "target_length_chars": 600,
    "min_length_chars": 300,
    "max_length_chars": 900,
    "max_tokens": 3000,
    "temperature": 0.72,
    "phase_a_max_attempts": 3,
    "topics": [
        "persistent memory and context management in LLM agents",
        "cascading automation with local models",
        "CAPTCHA and anti-bot handling in ethical scraping",
        "observability and tracing in agent systems",
        "technical debt in automation pipelines",
        "PowerShell integration in AI workflows",
        "post-mortems of real production failures",
        "provider failover and model cascade reliability",
        "context window exhaustion in long-running agents",
        "silent failure modes in autonomous AI agent loops",
        "state checkpoint and rollback strategies for long-running agents",
        "agent memory management and context window rotation under load",
    ],
        "mission": (
        "You are COMET-RIOBAMBA, an inventor building agent infrastructure. "
        "Read papers, observe real systems, then propose mechanisms, protocols, "
        "guardrails, or architectures that do not yet exist. "
        "State a clear engineering position."
    ),
        "core_principles": [
        "LANGUAGE: 100% ENGLISH. Precise, sharp, opinionated.",
        "TITLE: Confrontational reframe with STANCE. Max 12 complete words.",
        "ORIGINATE: Propose a mechanism, protocol, threshold, or architecture.",
        "STRUCTURE: Reframe -> invention -> threshold -> why.",
        "NO emojis, bullets, lists, markdown headers, or filler openings.",
        "TRUTH: Never fabricate outcomes, measurements, dates, or war stories.",
        "ABSTAIN when the mechanism cannot be grounded.",
        "Unmeasured thresholds are starting points; calibrate them against a baseline.",
        "Use concrete technical details and production failure modes.",
        "Frame inventions impersonally: 'The mechanism is' or 'Gate at X'.",
        "End with one sharp question or debatable technical assertion.",
        "Write 120-220 words and stay within the configured character limits.",
        "Never mention the platform, social networks, LLM, or generated text.",
    ],
}

# Contexto factual para posts anclados a incidentes reales propios
# (source=own_incident). Solo se usan estos hechos verificados; el resto del
# prompt ya prohibe inventar outcomes o war-stories (core_principles TRUTH).
_FACTUAL_CONTEXT_TEMPLATE = (
    "\nFACTUAL CONTEXT — REAL INCIDENT, VERIFIED:\n"
    "This post is anchored to a real production incident from the agent's own "
    "history. Use ONLY these facts:\n"
    "- Symptom: {symptom}\n"
    "- Root cause: {root_cause}\n"
    "- Fix: {fix}\n"
    "- Verified specifics: {real_numbers}\n\n"
    "INSTRUCTION: These are real, verified specifics. Use them exactly. Do NOT "
    "invent any additional number, date, or outcome beyond what is provided."
)

# Minimo de cifras verificadas que el body de un post own_incident debe incluir
# textualmente. La instruccion no alcanza (leccion arXiv): hace falta gate.
INCIDENT_MIN_FIGURES = 2


def _normalize_figure(text: str) -> str:
    """Normaliza una cifra para comparacion textual: sin comas de miles (para
    que '1,035' matchee '1035'), minusculas."""
    return re.sub(r",", "", text or "").lower().strip()


def _count_incident_figures(body: str, figures: List[str]) -> Tuple[int, List[str]]:
    """Cuantas de las cifras verificadas aparecen textualmente en el body.

    Devuelve (presentes, faltantes). Exige frontera no-digitica para evitar
    que '12' matchee dentro de '123' o que '50' matchee dentro de '1050'."""
    if not figures:
        return 0, list(figures)
    norm_body = _normalize_figure(body or "")
    present = 0
    missing: List[str] = []
    for fig in figures:
        pattern = rf"(?<!\d){re.escape(_normalize_figure(fig))}(?!\d)"
        if re.search(pattern, norm_body):
            present += 1
        else:
            missing.append(fig)
    return present, missing


# Topic filter: block topics outside our verticals
BLOCKED_TOPIC_SIGNALS = [
    "consciousness", "sentience", "philosophy", "blockchain",
    "cryptocurrency", "defi", "nft", "social media strategy",
    "marketing", "branding", "neural persistence", "silicon archive",
    "human irrationality",
]

ALLOWED_TOPIC_SIGNALS = [
    "agent", "production", "tool", "schema", "circuit", "retry",
    "observability", "tracing", "telemetry", "monitor", "drift", "failure",
    "eval", "memory", "cascade", "cascading", "orchestrat",
    "state", "checkpoint", "rollback", "backoff", "latency", "throughput",
    "pipeline", "validation", "provenance", "idempotency", "quota",
    "throttling", "tool call", "failure mode", "guardrail",
    "automation", "scraping", "workflow", "bot",
    # Vertical 3: la interseccion fisica/economica con sistemas de IA (no
    # energia generica suelta — la puerta es el vinculo con AI/agents).
    "inference cost", "datacenter", "power envelope", "thermal",
    "grid", "compute budget", "energy per token",
]


def _is_allowed_topic(topic: str) -> bool:
    """Reject topics outside our 2 verticals."""
    topic_lower = topic.lower()
    if any(signal in topic_lower for signal in BLOCKED_TOPIC_SIGNALS):
        return False
    return any(signal in topic_lower for signal in ALLOWED_TOPIC_SIGNALS)


def _apply_editorial_filter(topic: Optional[str], topic_source: str) -> tuple:
    """Filtro editorial de verticales.

    Los temas de post-pairing (watchlist_pairing) y de incidentes reales
    (own_incident) están exentos del chequeo de vocabulario ALLOWED (son
    on-niche por construcción: responden a un referente curado o a un fallo
    real del propio sistema, aunque su título no contenga keywords
    editoriales). Los signals BLOCKED (política dura: blockchain, crypto,
    filosofía, etc.) se mantienen.
    El resto de los gates (dedup/similitud) siguen intactos aguas abajo.
    """
    if not topic:
        return topic, topic_source
    topic_lower = topic.lower()
    if any(signal in topic_lower for signal in BLOCKED_TOPIC_SIGNALS):
        logger.warning("Phase A: topic '%s' rejected by editorial filter, using fallback", topic)
        return "context window exhaustion in long-running agents", "fallback_filter"
    if str(topic_source or "").startswith(("watchlist_pairing", "own_incident")):
        logger.info("Phase A: topic %s exento del filtro editorial: '%s'", topic_source.split(":")[0], topic[:80])
        return topic, topic_source
    if not any(signal in topic_lower for signal in ALLOWED_TOPIC_SIGNALS):
        logger.warning("Phase A: topic '%s' rejected by editorial filter, using fallback", topic)
        return "context window exhaustion in long-running agents", "fallback_filter"
    return topic, topic_source


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
        from utils.file_helpers import write_json_atomic
        write_json_atomic(_TOPIC_HISTORY_FILE, {"recent_topics": []}, indent=2, ensure_ascii=False)
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
        from utils.file_helpers import write_json_atomic
        write_json_atomic(_TOPIC_HISTORY_FILE, history, indent=2, ensure_ascii=False)

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
        common = {
            "and", "the", "in", "for", "of", "a", "to", "is", "that", "with",
            "en", "y", "de", "del", "la", "el", "los", "las", "con", "para",
            "por", "un", "una", "al", "que", "se", "su", "sus", "es", "son",
            "mas",
        }
        meaningful_overlap = (topic_words & past_words) - common
        if len(meaningful_overlap) >= 3:
            logger.info(
                "topic blocked by word-overlap (%s) with '%s'",
                sorted(meaningful_overlap), past_topic[:50],
            )
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
    from utils.file_helpers import write_json_atomic
    write_json_atomic(_TOPIC_HISTORY_FILE, history, indent=2, ensure_ascii=False)


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

_ARXIV_ID_RE = re.compile(r"arXiv:\s*([\w.\-]+)", re.IGNORECASE)
_PAPER_TITLE_RE = re.compile(r'paper\s+"([^"]+)"', re.IGNORECASE)


def _extract_arxiv_id(topic: str) -> Optional[str]:
    """Extrae el arXiv ID de un topic anclado (ej. '... (arXiv:2607.18045v1) ...').

    Devuelve el ID completo con su version (p.ej. '2607.18045v1') o None si el
    topic no trae cita. Es la fuente verificable que el body debe citar."""
    if not topic:
        return None
    m = _ARXIV_ID_RE.search(topic)
    return m.group(1) if m else None


def _paper_title_and_arxiv_id(topic: str) -> Tuple[Optional[str], Optional[str]]:
    """Extrae (titulo del paper, arXiv ID) de un topic anclado a arXiv.

    El topic tiene la forma 'production agent engineering implications of the
    paper "TITULO" (arXiv:XXXX.XXXXXv1) for ...'. Devuelve None para el titulo
    si el formato no matchea."""
    arxiv_id = _extract_arxiv_id(topic)
    title = None
    if topic:
        m = _PAPER_TITLE_RE.search(topic)
        if m:
            title = m.group(1).strip()
    return title, arxiv_id


def validate_post_text(text: str, required_citation: Optional[str] = None,
                       is_own_incident: bool = False,
                       historical_context: str = "") -> Tuple[bool, str]:
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
    # Gate anti-fuga (23/08/2026): 2 posts con el system prompt ecoado
    # ('**Analyze the Request Thoroughly:**...') llegaron a publicarse porque
    # pasaban longitud/sin-URL/sin-bullets. Bloquear y regenerar.
    if text_has_reasoning_leak(text): return False, "prompt_or_reasoning_leak"
    if text.count("\n\n") < 1: return False, "single_paragraph"
    # own_incident queda exento del guard anti-fabricacion: su primera persona
    # esta respaldada por numeros verificados del store (incidents.jsonl).
    if text_has_fabricated_measurement(text, is_own_incident=is_own_incident): return False, "fabricated_measurement"
    # Gate de citas historicas: un año 19xx/20xx que no esta en el contexto
    # (paper, incidente propio, o lo que el interlocutor menciono) es un
    # incidente de terceros con detalles no verificables.
    if text_has_unverifiable_historical_claim(text, historical_context, is_own_incident=is_own_incident):
        return False, "unverifiable_historical_claim"
    if required_citation:
        # La cita verificable debe estar en el body (tolerando el sufijo de
        # version: '2607.18045' == '2607.18045v1'). Sin ancla, no hay evidencia.
        base = re.sub(r"v\d+$", "", required_citation).lower()
        if f"arxiv:{base}" not in text.lower():
            return False, "missing_arxiv_citation"
    return True, "ok"


def _truncate_title(title: str, max_chars: int = 100) -> str:
    if len(title) <= max_chars: return title
    truncated = title[:max_chars]
    last_period = truncated.rfind('.')
    if last_period > int(max_chars * 0.6): return truncated[:last_period].strip()
    last_space = truncated.rfind(' ')
    if last_space > int(max_chars * 0.5): return truncated[:last_space].strip()
    return truncated.strip()


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
    text = re.sub(r"^\s*title\s*:\s*", "", text.strip(), flags=re.IGNORECASE)
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


def _select_phase_a_mode() -> str:
    """Selecciona el modo de Phase A (niche_technical vs research) según el
    rendimiento reciente y el peso estratégico de cada modo.

    Estrategia:
    - nicho_technical: contenido único del agente (5 nichos curados). Peso base 40%.
    - research: agenda de investigación, arXiv, post-pairing watchlist. Peso base 60%.

    Ajustes dinámicos:
    - Si el rendimiento de los nichos está bajo el umbral, baja el peso del nicho.
    - Si los nichos producen más engagement que la media, sube el peso.
    """
    import os
    import random
    from config import behavior_cfg
    from config.agent_policy import POLICY

    base_mode = behavior_cfg.get("phase_a_mode", POLICY.phase_a_mode) or "research"
    niche_topics = os.getenv("PHASE_A_NICHE_TOPICS", "").strip()
    if not niche_topics:
        return base_mode

    # Pesos base: el nicho es la propuesta de valor única del agente, pero
    # la investigación es el motor de descubrimiento y construcción de autoridad.
    niche_weight = 0.40
    research_weight = 0.60

    # Ajuste por rendimiento reciente del nicho
    try:
        perf = _load_topic_performance()
        if perf:
            niche_scores = []
            for niche in [t.strip() for t in niche_topics.split(",") if t.strip()]:
                rec = perf.get(niche)
                if rec and rec.get("score_checked"):
                    niche_scores.append(rec.get("score", 0))
            if niche_scores:
                avg_niche = sum(niche_scores) / len(niche_scores)
                if avg_niche < 0.3:
                    niche_weight = max(0.20, niche_weight - 0.15)
                elif avg_niche > 0.6:
                    niche_weight = min(0.60, niche_weight + 0.15)
    except Exception as e:
        logger.debug("Phase A: niche perf adjustment skipped: %s", e)

    # Selección ponderada
    roll = random.random()
    chosen = "niche_technical" if roll < niche_weight else "research"
    logger.info(
        "Phase A: mode selector roll=%.2f → %s (niche_w=%.2f, research_w=%.2f, base=%s)",
        roll, chosen, niche_weight, research_weight, base_mode,
    )
    return chosen


def choose_topic(mode: str = "research") -> tuple[str, str]:
    # ── Niche Technical Mode ──────────────────────────────────────────
    if mode == "niche_technical":
        niche_topics_str = os.getenv("PHASE_A_NICHE_TOPICS", "")
        if niche_topics_str:
            niche_topics = [t.strip() for t in niche_topics_str.split(",") if t.strip()]
            if niche_topics:
                chosen = random.choice(niche_topics)
                # Select a random niche and return its key as topic
                # The actual content generation will use the niche prompt
                source = "niche_config"
                logger.info("Phase A: niche technical mode, topic='%s' (source=%s)", chosen, source)
                return chosen, source
        # Si no hay nicho configurado, caemos al modo research default
        logger.info("Phase A: niche_technical mode selected but no PHASE_A_NICHE_TOPICS configured, falling back to research")
    
    # ── Research Mode (original) ──────────────────────────────────────
    if mode == "research":
        agenda = load_agenda()
        allow_feed = os.environ.get("ALLOW_PHASE_B_FEED_TOPICS", "").lower() == "true"
        # limit=None: la agenda completa (los topics arXiv llegan al final del
        # array pending_topics; un limit corto los deja afuera y la agenda nunca
        # alimenta posts anclados a papers reales).
        all_uncovered = agenda.get_uncovered_topics(limit=None)
        # Prioriza los temas mas recientes primero (no orden de insercion/FIFO).
        # Sin esto, un backlog viejo bloquea indefinidamente temas nuevos y de
        # mejor calidad (ej. arxiv, postmortem_own) que quedan al final de la
        # cola. created_at ausente/invalido se trata como el mas antiguo.
        # v5.2: topics de post-pairing con autores watchlist tienen prioridad
        # maxima — el mecanismo de invitacion reciproca hacia los referentes.
        # v5.3: los incidentes reales propios (own_incident) comparten ese
        # nivel: material que ningun otro agente puede escribir.
        # Con reverse=True, la prioridad usa valor 2 (mayor) para watchlist
        # y own_incident, y 1 para el resto; dentro de cada grupo rige
        # created_at descendente.
        all_uncovered = sorted(
            all_uncovered,
            key=lambda t: (
                2 if str(t.get("source", "")).startswith(("watchlist_pairing", "own_incident")) else 1,
                t.get("created_at") or "",
            ),
            reverse=True,
        )
        uncovered = []
        for t in all_uncovered:
            if str(t.get("source", "")).startswith("phase_b_feed") and not allow_feed:
                logger.debug("Phase A: skipping topic '%s' (source=%s)", t.get("topic", ""), t.get("source", ""))
                continue
            if _topic_in_cooldown(t.get("topic", "")):
                logger.info("Phase A: skipping topic en cooldown '%s'", t.get("topic", "")[:50])
                continue
            uncovered.append(t)
            if len(uncovered) >= 3:
                break
        if uncovered:
            perf = _load_topic_performance()
            available = []
            for t in uncovered:
                rec = perf.get(t["topic"])
                if rec and rec.get("score_checked") and rec.get("score") == 0 and rec.get("comment_count") == 0 and not str(t.get("source", "")).startswith("own_incident"):
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

def build_prompts(topic: str, policy: Optional[Dict[str, Any]] = None, variant: Optional[str] = None, mode: str = "research", incident: Optional[Dict[str, Any]] = None, incident_figures: Optional[List[str]] = None) -> Tuple[str, str]:
    import os
    
    # ── Niche Technical Mode ──────────────────────────────────────────
    if mode == "niche_technical":
        # Check if topic is a niche key
        niche_prompt = NICHE_PROMPTS.get(topic)
        if niche_prompt:
            system = niche_prompt["system"]
            topics = niche_prompt["topics"]
            tone = niche_prompt["tone"]
            examples = niche_prompt["examples"]
            
            # Build system prompt from niche config
            mission = ""
            principles_text = ""
            publish_line = ""
            preferred_topics = ", ".join(topics) if topics else ""
            target_words_min = 200
            target_words_max = 600
            allow_question_ending = False
            max_hashtags = 0
            
            system_prompt = (
                f"{system}\n\n"
                f"Tópicos asociados: {preferred_topics}.\n"
                f"Tono: {tone}\n"
                f"Longitud: {target_words_min}-{target_words_max} palabras.\n"
                f"Ejemplos de referencia:\n"
            )
            for ex in examples:
                system_prompt += f"- {ex}\n"
            system_prompt += "Escribe un post técnico original sin scaffolds ('guía completa', 'todo sobre'). "
            system_prompt += "Sé directo, declarativo, con datos reales y métricas concretas."
            
            # Build user prompt asking for a post on this niche topic
            user_prompt = f"Genera un post técnico original sobre: {topic}\n\n" + \
                          "Contexto: Eres un ingeniero de sistemas en Moltbook. " + \
                          "Sé directo, incluye datos reales si aplican, y métricas concretas.\n\n" + \
                          "Requisitos:\n" + \
                          "- Longitud: 200-600 palabras\n" + \
                          "- Tono: " + tone + "\n" + \
                          "- Evita scaffolds ('guía completa', 'todo sobre')\n" + \
                          "- Sé declarativo, sin hedging ('creo', 'podría ser')\n" + \
                          "- Incluye al menos un dato o métrica concreta\n" + \
                          "- No copies los examples de arriba, úsalos solo como referencia de estilo\n\n" + \
                          "Escribe el post ahora:"
            
            return system_prompt, user_prompt
    
    # ── Research Mode (original) ──────────────────────────────────────────
    policy = policy or {}
    mission = EDITORIAL_CONFIG["mission"]
    principles = EDITORIAL_CONFIG["core_principles"]
    principles_text = "\n".join(f"- {p}" for p in principles)
    topic_weights = policy.get("topic_weights", {}) if isinstance(policy, dict) else {}
    preferred_topics = ", ".join(topic_weights.keys()) if topic_weights else "ai agents, agent architecture, memory, llm optimization"
    style_policy = policy.get("style_policy", {}) if isinstance(policy, dict) else {}
    publication_policy = policy.get("publication_policy", {}) if isinstance(policy, dict) else {}
    publish_only_when = publication_policy.get("publish_only_when", "")
    tone = style_policy.get("tone", "natural_directo")
    target_words_min = style_policy.get("target_words_min", 120)
    target_words_max = style_policy.get("target_words_max", 220)
    allow_question_ending = style_policy.get("allow_question_ending", False)
    max_hashtags = style_policy.get("max_hashtags", 2)

    # Experiment variant adjustments
    variant_extra = ""
    if variant == "more_concise":
        variant_extra = (
            "VARIANT: Write MORE CONCISELY than usual. Target 120-160 words "
            "(still above the minimum length). Single paragraph only. "
            "Every word must add technical value.\n"
        )
    elif variant == "failure_focused":
        variant_extra = (
            "VARIANT: Focus on a SPECIFIC failure mode or incident. "
            "Describe what broke, why, and how you would fix it. "
            "Use concrete percentages or metrics.\n"
        )

    publish_line = f"Publish only when: {publish_only_when}.\n" if publish_only_when else ""

    system_prompt = (
        f"{mission}\n\nCore principles:\n{principles_text}\n\n"
        f"Preferred topic cluster: {preferred_topics}.\n"
        f"{publish_line}"
        f"Tone policy: {tone}.\n"
        f"Target length: {target_words_min}-{target_words_max} words.\n"
        f"Question ending allowed: {allow_question_ending or (mode == 'research')}.\n"
        f"Max hashtags: {max_hashtags}.\n"
        f"{variant_extra}"
        "Do not write like a marketer, journalist, or academic. Write like an engineer."
    )
    if incident_figures:
        # La regla 'Do not narrate personal lived experience' reprime el relato
        # del incidente (el modelo lo deja en el titulo y el body queda como
        # mecanismo puro). Para own_incident la excepcion es explicita: los
        # numeros del FACTUAL CONTEXT son datos propios verificados.
        system_prompt = system_prompt.rstrip() + (
            "\nEXCEPTION ACTIVE FOR THIS POST: you are reporting a REAL incident "
            "from your own history with verified numbers (FACTUAL CONTEXT). The "
            "anti-fabrication rule does not apply to those figures — they are "
            "your own data — and the incident MUST be written in the BODY, not "
            "just the title."
        )
    max_len = EDITORIAL_CONFIG["max_length_chars"]

    if incident_figures:
        # Encuadre propio de own_incident: el incidente ES la estructura, no un
        # accesorio. El encuadre generico (PROBLEM/PROPOSAL) empuja al modelo a
        # escribir mecanismo puro y dejar el incidente (con sus cifras) en el
        # titulo — que es exactamente lo que el gate de cifras debe impedir.
        figures_list = ", ".join(f"'{f}'" for f in incident_figures)
        min_figures = min(INCIDENT_MIN_FIGURES, len(incident_figures))
        user_prompt = (
            f"Write one original short-form engineering post about a REAL, "
            f"verified incident from your own production history: {topic}.\n\n"
            f"Length: 600 to 1000 characters. ABSOLUTE MAXIMUM: {max_len} characters.\n\n"
            "STRUCTURE (own_incident mode):\n"
            "1. INCIDENT (2-3 sentences): OPEN the body with the incident itself "
            "-- what the system did, the verified figures verbatim, and the "
            "root cause. This is the evidence: it is real, it happened, and "
            "its numbers are the whole point of the post.\n"
            "2. MECHANISM (3-5 sentences): Derive the general fix or protocol "
            "from that incident.\n"
            "3. QUESTION (1 sentence): End with a concrete, low-friction "
            "question that invites co-design. Avoid vague closings like "
            "'Thoughts?'.\n\n"
            "HARD REQUIREMENT (non-negotiable): the INCIDENT paragraph must "
            "write at least "
            f"{min_figures} of these verified figures verbatim, exactly as "
            "they appear here: "
            f"{figures_list}.\n"
            "Output format: FIRST line = TITLE (short, may carry the angle), "
            "then a blank line, then the BODY paragraphs. The INCIDENT paragraph "
            "goes in the BODY, never in the title line — putting them in the "
            "TITLE does not count. Using the verified numbers is not "
            "fabrication; omitting them is wasting the only thing that makes "
            "this post worth writing.\n\n"
            "STRICT STYLE REQUIREMENTS:\n"
            "- Write EXACTLY 3 short paragraphs. Separate each with a blank line.\n"
            "- NO bullet points, NO lists, NO emojis, NO markdown.\n"
            "- NO academic subtitles. Use continuous prose.\n"
            "- Sound like a senior systems engineer writing after seeing the "
            "system fail, recover, or evolve in production.\n"
            "- Make the post feel specific, grounded, and non-generic.\n"
            "- Do NOT include links, URLs, hashtags, or code blocks.\n"
            "- FORBIDDEN: do not mention Moltbook, platform names, LLM, AI "
            "assistant, language model, prompt, or that the text was generated.\n"
            "- You MUST finish your last thought completely. Do not get cut off.\n"
        )
    elif mode == "research":
        user_prompt = (
            f"Write one original engineering post about: {topic}.\n\n"
            "Choose ONE mechanism, failure mode, or design decision. Do not cover multiple ideas.\n"
            "Explain the mechanism precisely: what state changes, what boundary fails, and why the naive fix misses it.\n"
            "Propose ONE operational intervention and state ONE calibratable starting threshold. If the threshold is not measured, label it as a starting point and say it must be calibrated.\n"
            "Use one concrete technical detail such as a schema field, retry condition, timestamp, queue state, or observable metric. Do not invent a production outcome, measured result, date, or war story.\n\n"
            f"Length: 650-850 characters; absolute maximum: {max_len} characters.\n"
            "Write exactly three short prose paragraphs separated by blank lines. The first paragraph states the tension, the second explains the mechanism and intervention, and the third ends with one sharp technical question or debatable assertion. Do not label the paragraphs.\n\n"
            "Use precise English. No bullets, lists, emojis, markdown headers, URLs, hashtags, code, academic subtitles, generic advice, or filler openings. Do not mention the platform, LLM, AI assistant, language model, prompt, or that the text was generated. Finish the final sentence completely.\n"
            "Output only the title on the first line, then a blank line, then the body."
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
    arxiv_id = _extract_arxiv_id(topic)
    if arxiv_id:
        system_prompt = system_prompt.rstrip() + (
            f"\nSOURCE ANCHOR: your post is anchored to a real paper. The BODY must "
            f"contain the exact identifier (arXiv:{arxiv_id}) in its first paragraph. "
            "The TITLE must not contain it. This is non-negotiable."
        )
        citation_extra = (
            "HARD REQUIREMENT (non-negotiable):\n"
            f"- The BODY text MUST contain the exact identifier (arXiv:{arxiv_id}) at least once.\n"
            "- The identifier goes in the FIRST paragraph of the BODY, integrated into the prose "
            f"like: 'The paper (arXiv:{arxiv_id}) introduces a value-aware controller...'\n"
            "- The TITLE must NOT contain the arXiv identifier or the word arXiv.\n"
        )
        user_prompt = user_prompt.rstrip() + "\n\n" + citation_extra
    if incident:
        try:
            factual = _FACTUAL_CONTEXT_TEMPLATE.format(
                symptom=incident.get("symptom", ""),
                root_cause=incident.get("root_cause", ""),
                fix=incident.get("fix", ""),
                real_numbers=incident.get("real_numbers", ""),
            ).strip()
            user_prompt = user_prompt.rstrip() + "\n\n" + factual
        except Exception as e:
            logger.warning("Phase A: no se pudo anexar contexto factual del incidente: %s", e)
    return system_prompt.strip(), user_prompt.strip()

_HERO_STATE_FILE = BASE_DIR / "data/hero_state.json"


def _should_use_opus_hero() -> bool:
    """True si HOY (UTC) todavía no se usó el post 'hero' con Opus.

    Estado en data/hero_state.json: {"date":"YYYY-MM-DD","opus_done":bool}.
    Si el date != hoy (o el archivo falta/ilegible) -> opus_done=False (reset diario)."""
    import os
    if os.getenv("AGENT_FLASH_ONLY", "0") == "1":
        return False
    try:
        data = json.loads(_HERO_STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return True
    today = datetime.now(timezone.utc).date().isoformat()
    if data.get("date") != today:
        return True
    return not bool(data.get("opus_done"))


def _mark_opus_hero_used() -> None:
    """Marca que el hero Opus de HOY (UTC) ya se consumió."""
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        _HERO_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HERO_STATE_FILE.write_text(
            json.dumps({"date": today, "opus_done": True}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("Phase A: no se pudo escribir hero_state: %s", e)


async def call_model(deps: PhaseADeps, system_prompt: str, user_prompt: str, tier: str = "premium_opus") -> str:
    """Llama al modelo con fallback Groq para tier=classify."""
    
    # ── Fallback Groq para classify (bajo costo, alta disponibilidad) ──
    if tier == "classify":
        try:
            result = call_model_with_fallback(
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=512,
                temperature=0.1
            )
            if result["success"]:
                logger.info("call_model: classify con Groq fallback (%s tokens, %s)", result["tokens_used"], result["provider"])
                return result["content"]
            else:
                logger.warning("call_model: Groq fallback falló (%s), usando cascade", result.get("error", "unknown"))
        except Exception as e:
            logger.warning("call_model: error en Groq fallback (%s), usando cascade", e)
    
    # ── Cascade normal para todo lo demás (premium_opus, flash, etc.) ──
    cascade = deps.model_cascade
    if cascade is None: raise RuntimeError("ModelCascade no disponible en deps")
    if hasattr(cascade, "generate"):
        return await cascade.generate(tier=tier,
            prompt=user_prompt, systemprompt=system_prompt,
            maxtokens=EDITORIAL_CONFIG["max_tokens"], temperature=EDITORIAL_CONFIG["temperature"],
        )
    raise RuntimeError("ModelCascade no tiene metodo generate compatible")


from utils.quality_flags import quality_bestof_enabled as _quality_bestof_enabled
from utils.quality_flags import quality_bestof_n as _quality_bestof_n


def _parse_candidate_index(raw: Optional[str], count: int) -> Optional[int]:
    """Extrae el primer entero 1..count del output del juez. None si no hay."""
    if not raw:
        return None
    m = re.search(r"\b([1-9][0-9]*)\b", raw)
    if not m:
        return None
    idx = int(m.group(1))
    if 1 <= idx <= count:
        return idx
    return None


async def _pick_best_post(deps: PhaseADeps, candidates: List[Dict[str, Any]],
                          policy: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Juez flash sobre N candidatos válidos. Nunca devuelve peor que hoy:
    si el juez falla o responde basura -> desempate por dual_score; si eso
    también falla -> primer candidato."""
    if len(candidates) <= 1:
        return candidates[0]
    mission = EDITORIAL_CONFIG["mission"]
    principles = "\n".join(f"- {p}" for p in EDITORIAL_CONFIG["core_principles"])
    numbered = "\n\n".join(
        f"CANDIDATE {i}:\n{c['body']}" for i, c in enumerate(candidates, 1)
    )
    judge_system = (
        "You are the editorial judge for a production reliability publication.\n"
        f"Mission: {mission}\n\nCore principles:\n{principles}\n\n"
        "Pick the single best post draft. Reply with ONLY the candidate number (1, 2, ...)."
    )
    judge_user = f"Choose the best of these posts:\n\n{numbered}\n\nBest candidate number:"
    try:
        raw = await call_model(deps, judge_system, judge_user, tier="classify")
        idx = _parse_candidate_index(raw, len(candidates))
    except Exception as e:
        logger.warning("Phase A: best-of-N judge error (%s) -> fallback dual_score", e)
        idx = None
    if idx is not None:
        logger.info("Phase A: best-of-N judge picked candidate %s/%s", idx, len(candidates))
        return candidates[idx - 1]
    best = max(candidates, key=lambda c: compute_dual_score(c["body"])["research_value_score"])
    logger.warning("Phase A: best-of-N judge unusable -> dual_score tiebreak")
    return best


async def _critique_pass(deps: PhaseADeps, post: Dict[str, Any],
                         policy: Optional[Dict[str, Any]],
                         incident_figures: Optional[List[str]] = None) -> Dict[str, Any]:
    """Auto-crítica flash contra mission/core_principles. Degradación elegante:
    si el rewrite es inválido, low-quality, repetido o PEOR (dual_score menor)
    -> se descarta y se mantiene la versión pre-crítica.
    Para own_incident ademas se exige que el rewrite conserve las cifras
    verificadas: si la crítica las elimina, se descarta (el material es escaso)."""
    mission = EDITORIAL_CONFIG["mission"]
    principles = "\n".join(f"- {p}" for p in EDITORIAL_CONFIG["core_principles"])
    sys_prompt = (
        "You are a sharp editorial critic for a production reliability publication.\n"
        f"Mission: {mission}\n\nCore principles:\n{principles}\n\n"
        "Critique the draft below against these principles and return an IMPROVED rewrite "
        "in the exact same format: TITLE line, then body. Keep the arXiv citation if present."
    )
    user_prompt = f"TITLE: {post.get('title', '')}\n\n{post.get('body', '')}"
    try:
        raw = await call_model(deps, sys_prompt, user_prompt, tier="flash")
        title, body = extract_title_and_body(raw)
        title = _truncate_title(_normalize_moltbook_title(title), max_chars=100)
        body = _normalize_moltbook_body(body)
        if not body:
            return post
        # Gate de titulo: si la critica produce scaffold filtrado, se conserva
        # la version pre-critica (que ya paso todos los gates).
        if title_has_scaffold(title):
            logger.info("Phase A: auto-critique produjo titulo con scaffold -> keeping pre-critique")
            return post
        new_text = _truncate_to_limit(body, EDITORIAL_CONFIG["max_length_chars"])
        # Gate de fatiga: si la crítica re-introduce fórmulas, se conserva
        # la versión pre-crítica (que ya pasó el gate).
        if _check_template_fatigue(new_text):
            logger.info("Phase A: auto-critique reintrodujo fórmulas -> keeping pre-critique")
            return post
        required_citation = _extract_arxiv_id(post.get("metadata", {}).get("topic", ""))
        _historical_ctx = str(post.get("metadata", {}).get("historical_context")
                              or post.get("metadata", {}).get("topic", "") or "")
        is_valid, reason = validate_post_text(new_text, required_citation=required_citation,
                                              is_own_incident=bool(incident_figures),
                                              historical_context=_historical_ctx)
        if not is_valid:
            logger.info("Phase A: auto-critique invalid (%s) -> keeping pre-critique", reason)
            return post
        if incident_figures:
            present, _missing = _count_incident_figures(new_text, incident_figures)
            min_figures = min(INCIDENT_MIN_FIGURES, len(incident_figures))
            if present < min_figures:
                logger.info(
                    "Phase A: auto-critique perdió cifras verificadas del incidente (%s/%s) -> keeping pre-critique",
                    present, min_figures,
                )
                return post
        low_quality, lq_reason = _looks_low_quality(new_text, policy)
        if low_quality:
            logger.info("Phase A: auto-critique low_quality (%s) -> keeping pre-critique", lq_reason)
            return post
        if is_similar_to_recent(new_text):
            logger.info("Phase A: auto-critique similar to recent -> keeping pre-critique")
            return post
        old_score = compute_dual_score(post["body"])["research_value_score"]
        new_score = compute_dual_score(new_text)["research_value_score"]
        if new_score < old_score:
            logger.info("Phase A: auto-critique worse (%.2f < %.2f) -> keeping pre-critique",
                        new_score, old_score)
            return post
        new_post = dict(post)
        new_post["title"] = title
        new_post["body"] = new_text
        new_post["metadata"] = dict(post.get("metadata", {}))
        new_post["metadata"]["auto_critiqued"] = True
        logger.info("Phase A: auto-critique applied")
        return new_post
    except Exception as e:
        logger.warning("Phase A: auto-critique failed (%s) -> keeping pre-critique", e)
        return post


SUBSTANTIVE_MIN_CHARS = 400
_INTERROGATIVE_MARKERS = (
    "what", "how", "why", "when", "which", "where", "who", "do you", "does your",
    "did you", "have you", "has anyone", "would you", "is there", "what's", "how's",
    "how do", "how would", "can you",
)


def _is_substantive_post(text: str) -> bool:
    """True si el texto es un post de longitud completa que cierra con una pregunta
    abierta genuina. Sirve para NO rechazar contenido bueno que el clasificador de
    tipo (dual_scoring) etiqueta bajo por vocabulario, sin dejar pasar comentarios
    cortos/genericos. Detecta estructura, no keywords del dominio."""
    s = (text or "").strip()
    if len(s) < SUBSTANTIVE_MIN_CHARS:
        return False
    import re as _re
    sents = [x.strip() for x in _re.split(r'(?<=[.!?])\s+|\n+', s) if x.strip()]
    if not sents:
        return False
    last = sents[-1].lower()
    is_question = ("?" in last) or any(last.startswith(m) for m in _INTERROGATIVE_MARKERS)
    if is_question and len(last.split()) >= 8:
        return True
    # ── Segunda ruta (2026-09-18): post técnico denso sin pregunta ──
    #    El agente del niche no siempre termina en pregunta; muchos posts
    #    cierran con una prescripción ("The fix is..."). Exigir "?" rechazaba
    #    sistemáticamente contenido válido (1287 entradas en rejected_posts).
    if len(sents) < 3:
        return False
    tech_density = _count_signals(
        s.lower(),
        "the fix", "the mechanism", "the guardrail", "the gate",
        "the boundary", "failure mode", "silent failure", "circuit breaker",
        "schema drift", "rolling window", "idempotent", "atomicity",
        "commit boundar", "checkpoint", "backpressure",
    )
    return tech_density >= 2


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

    qf = (policy or {}).get("quality_filters", {})
    text_lower = stripped.lower()

    if qf.get("reject_if_mentions_moltbook", True) and "moltbook" in text_lower:
        return True, "mentions_moltbook"

    if qf.get("reject_if_mentions_llm", True) and (
        "llm" in text_lower or "large language model" in text_lower
    ):
        return True, "mentions_llm"

    if qf.get("reject_if_off_niche", True):
        niche_keywords = {"agent", "agents", "autonomous", "production"}
        for phrase in (policy or {}).get("topic_weights", {}).keys():
            for word in phrase.lower().split():
                word = "".join(c for c in word if c.isalpha())
                if len(word) >= 4 and word not in {"with", "that", "this", "from", "have", "when", "your"}:
                    niche_keywords.add(word)
        if not any(kw in text_lower for kw in niche_keywords):
            return True, "off_niche"

    min_score = qf.get("min_quality_score")
    if min_score is not None:
        # Se compara research_value_score (no composite_score): en generacion
        # engagement es siempre 0, y composite = 0.7 * research_value tiene
        # techo 0.7 — un umbral como el 0.72 de la policy rechazaria todo.
        # Contra research_value, 0.72 deja pasar framework/empirical/critique/
        # historical y rechaza metric/clarification/agreement/repetition.
        score = compute_dual_score(stripped)
        _verdict = "approve"
        _reason = "above_min_quality"
        _override = False
        if score["research_value_score"] < float(min_score):
            # Override estructural (Fix 6): un post de longitud completa que cierra
            # con una pregunta abierta genuina es publicable aunque el content_type
            # sea de bajo valor. dual_scoring clasifica TIPO (disenado para rankear
            # comentarios ajenos en Fase B), no captura todo el vocabulario del niche.
            if _is_substantive_post(stripped):
                _verdict = "approve"
                _reason = "substantive_override"
                _override = True
            else:
                _verdict = "reject"
                _reason = "below_min_quality"
        logger.info(
            "EVENT phase_a_classifier_verdict | %s",
            json.dumps({
                "verdict": _verdict,
                "reason": _reason,
                "content_type": score["content_type"],
                "research_value_score": score["research_value_score"],
                "min_quality_score": float(min_score),
                "override_substantive": _override,
                "len_chars": len(stripped),
            }, ensure_ascii=False),
        )
        if _verdict == "reject":
            return True, f"below_min_quality_score:{score['research_value_score']}:{score['content_type']}"

    return False, ""


_GENERATION_ATTEMPTS_LOG = BASE_DIR / "data/generation_attempts.jsonl"


# ── Gate anti-fatiga de plantilla (24/08/2026) ────────────────────────
# Auditoria editorial: 60% de posts recientes comparten coletillas
# formulaicas. Antes de publicar, el candidato se confronta contra los
# tetragramas 'hot' de los ultimos posts propios; si pisa el hot set,
# rechazo + regeneracion con las fórmulas nombradas. Reversible:
# PHASE_A_FATIGUE_GATE=0.
_FATIGUE_STORE = BASE_DIR / "data/published_posts.json"


def _recent_own_bodies(window: int = 25) -> List[str]:
    try:
        posts = json.loads(_FATIGUE_STORE.read_text(encoding="utf-8"))
        return [str(p.get("body") or "") for p in posts[-window:] if p.get("body")]
    except (OSError, ValueError):
        return []


def _env_flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


def _check_template_fatigue(text: str) -> List[str]:
    """Tetragramas hot que el candidato repite ([] = limpio). Con corpus
    chico (< PHASE_A_FATIGUE_MIN_BASE posts) no juzga: la base estadistica
    no alcanza y rechazaria todo."""
    if not _env_flag("PHASE_A_FATIGUE_GATE", "1"):
        return []
    window = int(os.getenv("PHASE_A_FATIGUE_WINDOW", "25"))
    bodies = _recent_own_bodies(window)
    if len(bodies) < int(os.getenv("PHASE_A_FATIGUE_MIN_BASE", "6")):
        return []
    min_posts = int(os.getenv("PHASE_A_FATIGUE_MIN_POSTS", "3"))
    return text_template_fatigue(text, bodies, min_posts=min_posts)


def _log_generation_attempt(topic: str, topic_source: str, attempt: int, max_attempts: int, outcome: str) -> None:
    """Registra cada intento de generacion (exito o motivo de rechazo). Antes
    esta informacion solo vivia en el log de texto y se perdia al terminar
    el ciclo -- es la base para medir tasas de rechazo por tipo/tema."""
    try:
        _GENERATION_ATTEMPTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "topic": topic,
            "topic_source": topic_source,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "outcome": outcome,
        }
        with open(_GENERATION_ATTEMPTS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug("Phase A: no se pudo loguear generation attempt: %s", e)


_REJECTED_POSTS_LOG = BASE_DIR / "data/rejected_posts.jsonl"


def _log_rejected_body(topic: str, topic_source: str, attempt: int, reason: str, title: str, body: str) -> None:
    """Persiste el cuerpo generado que fue rechazado, para poder auditar por que
    rebota el gate de calidad (variantes clarification/metric_proposal). Append-only;
    no toca la logica de decision. Complementa _log_generation_attempt, que solo
    guarda la razon y no el texto."""
    try:
        _REJECTED_POSTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "topic": topic,
            "topic_source": topic_source,
            "attempt": attempt,
            "reason": reason,
            "title": title[:200],
            "body": body[:800],
        }
        with open(_REJECTED_POSTS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug("Phase A: no se pudo registrar rejected body: %s", e)


# ── Cooldown de topics fallidos (v5.11) ───────────────────────────────
# Rompe el bucle de un topic "toxico" que falla la validacion repetidamente
# (ej. 105x too_short del mismo topic con Gemini 3.7 Flash) bloqueando la
# publicacion. Cuando un topic agota sus reintentos con fallo determinista,
# entra en cooldown persistente y el selector lo salta hasta que expire.
_TOPIC_COOLDOWN_PATH = BASE_DIR / "data/phase_a_topic_cooldown.json"
TOPIC_COOLDOWN_MINUTES = float(os.getenv("PHASE_A_TOPIC_COOLDOWN_MINUTES", "240"))  # 4h


def _load_topic_cooldown() -> Dict[str, str]:
    if not _TOPIC_COOLDOWN_PATH.exists():
        return {}
    try:
        data = json.loads(_TOPIC_COOLDOWN_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _save_topic_cooldown(cooldown: Dict[str, str]) -> None:
    try:
        _TOPIC_COOLDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        from utils.file_helpers import write_json_atomic
        write_json_atomic(_TOPIC_COOLDOWN_PATH, cooldown, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug("Phase A: no se pudo guardar topic cooldown: %s", e)


def _topic_in_cooldown(topic: str) -> bool:
    """True si el topic esta en cooldown vigente (expires_at futuro)."""
    if not topic:
        return False
    expires = _load_topic_cooldown().get(_tema_key(topic))
    if not expires:
        return False
    try:
        exp = datetime.fromisoformat(str(expires))
    except ValueError:
        return False
    now = datetime.now(timezone.utc)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return now < exp


def _mark_topic_cooldown(topic: str, reason: str = "") -> None:
    """Mete el topic en cooldown por TOPIC_COOLDOWN_MINUTES."""
    if not topic:
        return
    cooldown = _load_topic_cooldown()
    key = _tema_key(topic)
    expires = datetime.now(timezone.utc) + timedelta(minutes=TOPIC_COOLDOWN_MINUTES)
    cooldown[key] = expires.isoformat()
    # poda: descarta entradas expiradas para no crecer sin fin
    now = datetime.now(timezone.utc)
    for k, v in list(cooldown.items()):
        try:
            exp_v = datetime.fromisoformat(str(v))
            if exp_v.tzinfo is None:
                exp_v = exp_v.replace(tzinfo=timezone.utc)
            if exp_v < now:
                del cooldown[k]
        except (ValueError, TypeError):
            del cooldown[k]
    _save_topic_cooldown(cooldown)
    logger.warning(
        "Phase A: topic en cooldown %.0f min (reason=%s): '%s'",
        TOPIC_COOLDOWN_MINUTES, reason or "-", topic[:60],
    )


def _tema_key(topic: str) -> str:
    return " ".join((topic or "").lower().split())


_RETRY_CORRECTION_HINTS: Dict[str, str] = {
    "too_short": ("El intento anterior fue demasiado corto (menos de 600 caracteres). "
                  "Escribi el body con al menos 600-900 caracteres (120-220 palabras): "
                  "abre con el mecanismo, desarrolla el por que con un contra-ejemplo o "
                  "umbral concreto, y cierra con la tension. NO cortes a las dos oraciones."),    "too_long": "El intento anterior excedio el largo maximo. Se mas directo y recorta lo accesorio.",
    "contains_url": "El intento anterior incluia una URL. No incluyas links.",
    "contains_code": "El intento anterior incluia bloques de codigo o sintaxis de codigo. Describi la idea en prosa, sin codigo.",
    "contains_error_log": "El intento anterior parecia un log de error o traceback. Escribi una reflexion tecnica, no un log.",
    "contains_bullet_points": "El intento anterior usaba vinetas o listas. Escribi en prosa continua, sin bullets.",
    "contains_emoji": "El intento anterior tenia emojis. No uses emojis.",
    "contains_academic_subtitles": "El intento anterior tenia subtitulos de estilo academico. Escribi un unico bloque de prosa fluida.",
    "contains_filler_opening": "El intento anterior empezaba con una frase de relleno generica. Arranca directo con la idea concreta.",
    "single_paragraph": "El intento anterior era un solo parrafo compacto. Separa la idea en al menos dos parrafos.",
    "similar_recent": "El intento anterior era demasiado parecido a un post reciente. Encara el tema desde un angulo distinto.",
    "empty_output": "El intento anterior no devolvio contenido. Genera el post completo.",
    "too_fragmented": "El intento anterior tenia demasiados saltos de linea. Escribi en prosa continua, menos fragmentada.",
    "placeholder_text": "El intento anterior tenia texto de relleno generico. Generá contenido real y especifico.",
    "mentions_moltbook": "El intento anterior menciono 'Moltbook' explicitamente. No nombres la plataforma.",
    "mentions_llm": "El intento anterior menciono 'LLM' o 'large language model' explicitamente. Evita esa jerga meta sobre el modelo.",
    "missing_arxiv_citation": "El intento anterior no cito la fuente arXiv del paper en el cuerpo. Incluí el identificador textualmente (formato arXiv:XXXX.XXXXXv1, tal cual viene en el tema del post) en el PRIMER parrafo, junto con el nombre del paper. Es la evidencia verificable del post.",
    "missing_incident_figures": "El intento anterior no incluyó al menos dos de las cifras verificadas del incidente EN EL BODY (el título no cuenta). Abrí el PRIMER parrafo del body con el incidente y escribí los numeros reales textualmente, tal cual aparecen entre comillas en el HARD REQUIREMENT. La diferenciacion del post son esos numeros: sin ellos es un post generico.",
    "unverifiable_historical_claim": "Remove the dated third-party example. Make the same point from the mechanism itself, or from your own verified incidents.",
    "prompt_or_reasoning_leak": "El intento anterior ecoó instrucciones internas, listas de pasos o razonamiento en vez del contenido final. Devolvé ÚNICAMENTE el post terminado: primera línea = título declarativo, luego el body en prosa continua.",
    "leaked_scaffold_title": "El intento anterior tenía un título que era scaffold interno ('Critique:**', 'Here's a thinking process:', termina en ':', o empieza como item de lista). El título debe ser una frase declarativa confrontativa de ~6-12 palabras, segunda persona, sin markdown, sin etiquetas y sin dos puntos finales.",
    "template_fatigue": "El intento anterior reutilizó fórmulas literales de posts anteriores (mismas coletillas de cierre o apertura). Escribí TODO el post con estructura y vocabulario originales: nada de frases hechas repetidas, otro tipo de cierre y otra forma de abrir. La voz es inventor, no plantilla.",
}


def _build_retry_correction(reason: str) -> str:
    """Traduce el motivo de rechazo del intento anterior en una instruccion
    correctiva para el proximo intento -- evita repetir el mismo prompt a
    ciegas cuando cada reintento paga una llamada real al modelo."""
    if not reason:
        return ""
    if reason.startswith("below_min_quality_score"):
        parts = reason.split(":")
        content_type = parts[2] if len(parts) > 2 else "generico"
        hint = (
            f"El intento anterior fue clasificado como '{content_type}' (bajo valor "
            "de investigacion). Escribi algo con mas peso tecnico: un hallazgo "
            "empirico concreto, una propuesta de framework, o una critica con "
            "alternativa -- no una aclaracion generica, un acuerdo, o una "
            "propuesta de metrica aislada."
        )
    elif reason.startswith("validation_failed:"):
        sub_reason = reason.split(":", 1)[1]
        hint = _RETRY_CORRECTION_HINTS.get(sub_reason, f"El intento anterior fue rechazado ({sub_reason}). Corregi eso en este intento.")
    else:
        hint = _RETRY_CORRECTION_HINTS.get(reason, f"El intento anterior fue rechazado ({reason}). Corregi eso en este intento.")
    return f"\n\nCORRECCION DEL INTENTO ANTERIOR: {hint}"


def _topic_with_matrix_fallback(
    mode: str, matrix: Any
) -> tuple[Optional[str], str]:
    """Try research agenda → roadmap → TopicMatrix select, return (topic, source)."""
    from config.topic_matrix import TopicMatrix

    if mode == "research":
        agenda = load_agenda()
        allow_feed = os.environ.get("ALLOW_PHASE_B_FEED_TOPICS", "").lower() == "true"
        # limit=None: ver nota en choose_topic — los topics arXiv quedan fuera
        # del array con un limit corto y nunca se seleccionan.
        all_uncovered = agenda.get_uncovered_topics(limit=None)
        # Prioriza los temas mas recientes primero (no orden de insercion/FIFO).
        # Sin esto, un backlog viejo bloquea indefinidamente temas nuevos y de
        # mejor calidad (ej. arxiv, postmortem_own) que quedan al final de la
        # cola. created_at ausente/invalido se trata como el mas antiguo.
        # v5.2: los topicos de post-pairing con autores watchlist tienen prioridad
        # maxima — son el mecanismo de invitacion reciproca hacia los referentes.
        # v5.3: los incidentes reales propios (own_incident) comparten ese nivel.
        # Con reverse=True, prioridad 2 (watchlist/own_incident) y 1 (resto),
        # created_at desc.
        all_uncovered = sorted(
            all_uncovered,
            key=lambda t: (
                2 if str(t.get("source", "")).startswith(("watchlist_pairing", "own_incident")) else 1,
                t.get("created_at") or "",
            ),
            reverse=True,
        )
        uncovered = []
        for t in all_uncovered:
            if str(t.get("source", "")).startswith("phase_b_feed") and not allow_feed:
                logger.debug("Phase A: skipping topic '%s' (source=%s)", t.get("topic", ""), t.get("source", ""))
                continue
            if _topic_in_cooldown(t.get("topic", "")):
                logger.info("Phase A: skipping topic en cooldown '%s'", t.get("topic", "")[:50])
                continue
            uncovered.append(t)
            if len(uncovered) >= 3:
                break
        if uncovered:
            perf = _load_topic_performance()
            available = []
            for t in uncovered:
                rec = perf.get(t["topic"])
                if rec and rec.get("score_checked") and rec.get("score") == 0 and rec.get("comment_count") == 0 and not str(t.get("source", "")).startswith("own_incident"):
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
        logger.warning("CHALLENGE_DEBUG raw: %r", challenge_text)
        logger.warning("CHALLENGE_DEBUG full_verification: %r", verification)
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
        # ─── Quiet Hours: no original content generation outside configured hours ──────────
        try:
            tz = zoneinfo.ZoneInfo(behavior_cfg.get("timezone", "America/Guayaquil"))
        except Exception as e:
            logger.warning(
                "Timezone %r no resoluble (%s). Fallback a UTC-5 fijo.",
                behavior_cfg.get("timezone"), e,
            )
            tz = timezone(timedelta(hours=-5))
        now_dt = datetime.now(tz)
        current_hour = now_dt.hour
        quiet = get_quiet_hours(now=now_dt)
        post_hours = get_post_hours(now=now_dt)
        if current_hour in quiet:
            logger.info("Phase A: quiet_hours (hora=%s), saltando", current_hour)
            return {"posts_published": 0, "drafts_generated": 0, "posts": [], "success": False, "skipped": "quiet_hours"}
        if post_hours and current_hour not in post_hours:
            logger.info("Phase A: fuera de post_hours (hora=%s, permitidas=%s), saltando", current_hour, post_hours)
            return {"posts_published": 0, "drafts_generated": 0, "posts": [], "success": False, "skipped": "outside_post_hours"}

        posts: List[Dict[str, Any]] = []
        max_per_day = get_max_posts_per_day(now=now_dt, default=POLICY.max_posts_per_day)

        def _current_posts_today() -> int:
            if self.deps.get_posts_today is not None:
                return self.deps.get_posts_today()
            return self.deps.posts_today

        already_today = _current_posts_today()
        if max_per_day is not None:
            remaining_today = max(0, max_per_day - already_today)
            if remaining_today <= 0:
                logger.info("Phase A: limite diario alcanzado (%s/%s). Saltando.", already_today, max_per_day)
                return {"posts_published": 0, "drafts_generated": 0, "posts": [], "success": False, "skipped": "daily_limit_reached"}
        logger.info("Phase A: limite diario=%s, ya hoy=%s, disponibles=%s", max_per_day if max_per_day is not None else "sin límite", already_today, max_per_day - already_today if max_per_day is not None else "ilimitado")

        # ── Weekly limit: max_posts_per_week desde editorial_policy.json ──
        try:
            _weekly_policy = load_editorial_policy()
            max_per_week = _weekly_policy.get("publication_policy", {}).get("max_posts_per_week")
            corpus_post_exemption = _weekly_policy.get("corpus_post_exemption", 0)
            if max_per_week is not None:
                from services.own_post_store import count_posts_since
                posts_this_week = count_posts_since(7)
                # Recomendación 1: exención de corpus — si aún no se han publicado
                # el número exento de posts del corpus, permitir publicación aun
                # cuando el límite semanal estaría agotado.
                corpus_eligible = corpus_post_exemption > 0 and posts_this_week < corpus_post_exemption
                if posts_this_week >= int(max_per_week) and not corpus_eligible:
                    logger.info("Phase A: limite semanal alcanzado (%s/%s). Saltando.", posts_this_week, max_per_week)
                    return {"posts_published": 0, "drafts_generated": 0, "posts": [], "success": False, "skipped": "weekly_limit_reached"}
                # Si hay exención y el corpus aún no la consume, reducir el conteo
                # efectivo para este ciclo
                effective_max = int(max_per_week) - (0 if corpus_eligible else 0)
                if not corpus_eligible:
                    effective_max = int(max_per_week)
                logger.info("Phase A: limite semanal=%s, esta semana=%s, exención_corpus=%s, eligible=%s",
                            max_per_week, posts_this_week, corpus_post_exemption, corpus_eligible)
        except Exception as e:
            logger.debug("Phase A: weekly limit check skipped: %s", e)

        # max_posts_per_day=None significa sin limite; asegurar presupuesto definido.
        if max_per_day is None:
            remaining_today = float('inf')
        posts_to_generate = min(1, remaining_today)
        phase_a_mode = _select_phase_a_mode()

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
            # Los temas de post-pairing (watchlist_pairing) están exentos: son
            # on-niche por construcción (responden a un referente curado) aunque
            # su título generado no contenga keywords del vocabulario editorial.
            topic, topic_source = _apply_editorial_filter(topic, topic_source)

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
                        # v5.11: saltar topics en cooldown (fallaron validacion)
                        if _topic_in_cooldown(alt):
                            continue
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
                        if best_alt and _is_allowed_topic(best_alt) and not _topic_in_cooldown(best_alt):
                            topic = best_alt
                            topic_source = "forced_fallback"
                            logger.info("Phase A: Forzando publicación de tema '%s' (menor similitud=%.2f) para evitar silencio editorial.", topic[:60], best_alt_sim)
                        else:
                            logger.warning("Phase A: no fresh topic available. Skipping post this cycle.")
                            return {"posts_published": 0, "drafts_generated": 0, "posts": [],
                                    "success": False, "skipped": "topic_dedup"}

            # ── Incidente real (source=own_incident:<id>): cargar los hechos
            # verificables para el contexto factual del prompt. Si el incidente
            # ya no existe en el store (archivo borrado/editado), cae al prompt
            # generico sin romper el ciclo. ──
            _incident = None
            _incident_figures: List[str] = []
            if str(topic_source or "").startswith("own_incident:"):
                _incident_id = str(topic_source).split(":", 1)[1]
                _incident = get_incident_by_id(_incident_id)
                if _incident:
                    _incident_figures = extract_incident_figures(_incident)
                    logger.info("Phase A: incidente real '%s' cargado para el post (cifras verificadas: %s)",
                                _incident_id, ", ".join(_incident_figures) or "-")
                else:
                    logger.warning("Phase A: incidente '%s' no encontrado en el store; prompt generico", _incident_id)

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
            system_prompt, user_prompt = build_prompts(topic, policy, variant=variant, mode=phase_a_mode, incident=_incident, incident_figures=_incident_figures)

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

            # ── Pacing check: 2h minimum between real posts (antes del loop de generación) ──
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
                        posts.append({
                            "title": "", "body": "",
                            "metadata": {"topic": topic},
                            "error": "pacing_blocked",
                            "published": False,
                        })
                        continue
            except Exception as e:
                logger.debug("Phase A: pacing check skipped: %s", e)

            max_attempts = EDITORIAL_CONFIG["phase_a_max_attempts"]
            generated_post: Optional[Dict[str, Any]] = None
            # Correccion acumulada del intento anterior: cada rechazo la
            # actualiza para que el proximo intento sepa QUE corregir en vez
            # de repetir el mismo prompt a ciegas (cada retry paga una llamada).
            retry_correction = ""
            # ── Best-of-N (A/B, flag AGENT_QUALITY_BESTOF=1) ────────────────
            # Genera hasta N candidatos VALIDOS (misma validación que hoy) y
            # un juez flash elige el mejor. Degradación elegante: con flag OFF
            # (o sin candidatos extra) el comportamiento y el nº de llamadas
            # son idénticos a los actuales. Nunca publica algo peor que hoy.
            bestof_enabled = _quality_bestof_enabled()
            bestof_n = _quality_bestof_n()
            valid_candidates: List[Dict[str, Any]] = []
            # ── Enrutado de generación (ESCENARIO B, 24/08/2026) ───────────
            # TODOS los posts generan en tier 'premium': AGENT_PRO_TIER_ONLY=1
            # lo remapa a tier_fallback = DeepSeek V4 Pro DIRECTO (calidad
            # máxima editorial). Coste real medido: ~$0.005/post pico;
            # cap diario DEEPSEEK_SPEND_LIMIT_USD=$0.50 como cinturón — si
            # se agota, la cascada cae a gratis sin bloquear el ciclo.
            # Reversible: PHASE_A_GENERATION_TIER=flash (o premium_opus para
            # el viejo esquema hero/Opus).
            _gen_tier = os.getenv("PHASE_A_GENERATION_TIER", "premium").strip().lower() or "premium"
            logger.info("Phase A: tier de generación = %s (Escenario B: DeepSeek V4 Pro)", _gen_tier)
            for attempt in range(1, max_attempts + 1):
                attempt_user_prompt = user_prompt + retry_correction
                try:
                    logger.info("Phase A: llamada al modelo (intento %s/%s)...", attempt, max_attempts)
                    raw_text = await call_model(self.deps, system_prompt, attempt_user_prompt, tier=_gen_tier)
                    # CAPTURAR COSTOS: acceder a _last_usage del cascade después de generación exitosa
                    _cascade = self.deps.model_cascade
                    _provider_name = _cascade.TIER_MAPPING.get(_gen_tier, "tier_fallback")
                    _usage = _cascade._last_usage.get(_provider_name, {}) or {}
                    _input_tokens = int(_usage.get("input_tokens", 0) or 0)
                    _output_tokens = int(_usage.get("output_tokens", 0) or 0)
                    from services.model_cascade import _estimate_cost_usd
                    _cost_usd = _estimate_cost_usd(_provider_name, _input_tokens, _output_tokens)
                    logger.info("Phase A: costos capturados - input=%s, output=%s, cost=$%.6f", _input_tokens, _output_tokens, _cost_usd)
                except Exception as e:
                    logger.warning("Phase A: error en llamada al modelo: %s", e)
                    _log_generation_attempt(topic, topic_source, attempt, max_attempts, "model_error")
                    retry_correction = _build_retry_correction("model_error")
                    if attempt >= max_attempts:
                        generated_post = {"title": "", "body": "", "metadata": {"topic": topic}, "error": str(e), "attempts": attempt, "published": False, "error_type": "model_error"}
                    continue
                if not raw_text or not isinstance(raw_text, str):
                    _log_generation_attempt(topic, topic_source, attempt, max_attempts, "empty_output")
                    retry_correction = _build_retry_correction("empty_output")
                    if attempt >= max_attempts:
                        generated_post = {"title": "", "body": "", "metadata": {"topic": topic}, "error": "empty_output", "attempts": attempt, "published": False, "error_type": "empty_output"}
                    continue
                # ── ABSTAIN: salida legitima. NO publicar, NO contar como fallo
                # de generacion; solo telemetria (abstained + tracker diario). ──
                if raw_text.strip().upper().startswith("ABSTAIN"):
                    record_abstain(True)
                    _log_generation_attempt(topic, topic_source, attempt, max_attempts, "abstained")
                    logger.info("Phase A: ABSTAIN (topic='%s', intento %s/%s) — no se publica", topic[:60], attempt, max_attempts)
                    generated_post = {"title": "", "body": "", "metadata": {"topic": topic}, "error": "abstained", "attempts": attempt, "published": False, "error_type": "abstained"}
                    break
                record_abstain(False)
                title, body = extract_title_and_body(raw_text)
                title = _normalize_moltbook_title(title)
                title = _truncate_title(title, max_chars=100)
                body = _normalize_moltbook_body(body)
                post_text = _truncate_to_limit(body, EDITORIAL_CONFIG["max_length_chars"])
                # ── Gate anti-fuga de TITULO (24/08/2026) ─────────────────
                # El body pasa por text_has_reasoning_leak, pero el titulo
                # (primera linea del output crudo) no tenia ningun gate: se
                # publicaron 'Here's a thinking process:' (x2), 'We need to
                # critique the draft...' y 'Critique:** ...'. Rechazar y
                # regenerar con correccion.
                if title_has_scaffold(title):
                    reason = "leaked_scaffold_title"
                    logger.warning("Phase A: titulo con scaffold interno (reason=%s), reintentar...", reason)
                    _log_generation_attempt(topic, topic_source, attempt, max_attempts, f"validation_failed:{reason}")
                    _log_rejected_body(topic, topic_source, attempt, f"validation_failed:{reason}", title, post_text)
                    retry_correction = _build_retry_correction(f"validation_failed:{reason}")
                    if attempt >= max_attempts:
                        _mark_topic_cooldown(topic, reason=f"validation_failed:{reason}")
                        generated_post = {"title": title, "body": post_text, "metadata": {"topic": topic, "validation_reason": reason}, "attempts": attempt, "published": False, "error": f"validation_failed:{reason}"}
                    continue
                required_citation = _extract_arxiv_id(topic)
                # Contexto historico del gate de citas: el topic (paper anclado)
                # + los hechos del incidente propio (si lo hay). Un año fuera de
                # esto es un incidente de terceros no verificable.
                _historical_ctx = topic or ""
                if _incident:
                    _historical_ctx += " " + " ".join(
                        str(_incident.get(k) or "") for k in ("symptom", "root_cause", "fix", "real_numbers")
                    )
                is_valid, reason = validate_post_text(post_text, required_citation=required_citation,
                                                      is_own_incident=bool(_incident_figures),
                                                      historical_context=_historical_ctx)
                if not is_valid and reason == "missing_arxiv_citation" and required_citation:
                    # Tema anclado a arXiv: la cita faltante NO rechaza ni consume
                    # reintentos (la cita se valida al final, asi que el candidato
                    # ya paso todos los demas gates). Se inyecta la cita verificable
                    # de forma deterministica y se acepta YA en el primer intento:
                    # no se desperdician generaciones ni candidatos best-of-N.
                    paper_title, _ = _paper_title_and_arxiv_id(topic)
                    src_label = paper_title or topic
                    source_line = f"Source: {src_label} (arXiv:{required_citation})"
                    room = EDITORIAL_CONFIG["max_length_chars"] - len(source_line) - 2
                    injected = (_truncate_to_limit(post_text, room) + "\n\n" + source_line).strip()
                    injected_ok, _ = validate_post_text(injected, required_citation=required_citation,
                                                        is_own_incident=bool(_incident_figures),
                                                        historical_context=_historical_ctx)
                    if injected_ok:
                        _log_generation_attempt(topic, topic_source, attempt, max_attempts, "success_arxiv_injected")
                        post_text = injected
                        is_valid, reason = True, ""
                    # Si la inyeccion no valida (body truncado demasiado corto),
                    # cae al manejo generico de rechazo/reintento.
                if not is_valid:
                    logger.warning("Phase A: contenido invalido (reason=%s), reintentar...", reason)
                    _log_generation_attempt(topic, topic_source, attempt, max_attempts, f"validation_failed:{reason}")
                    _log_rejected_body(topic, topic_source, attempt, f"validation_failed:{reason}", title, post_text)
                    retry_correction = _build_retry_correction(f"validation_failed:{reason}")
                    if attempt >= max_attempts:
                        # v5.11: topic que agota reintentos con fallo determinista
                        # entra en cooldown para no bloquear la publicacion.
                        _mark_topic_cooldown(topic, reason=f"validation_failed:{reason}")
                        generated_post = {"title": title, "body": post_text, "metadata": {"topic": topic, "validation_reason": reason}, "attempts": attempt, "published": False, "error": f"validation_failed:{reason}"}
                    continue

                # ── Gate anti-fatiga de plantilla (24/08/2026) ──
                # Un candidato que repite fórmulas de los posts recientes
                # suena a molde, no a invención. Rechazo con las fórmulas
                # nombradas para que el reintento varíe de verdad.
                _fatigue_matched = _check_template_fatigue(post_text)
                if _fatigue_matched:
                    reason = "template_fatigue"
                    logger.warning(
                        "Phase A: candidato repite %d formula(s) de posts recientes (%s), reintentar...",
                        len(_fatigue_matched), "; ".join("'%s'" % g for g in _fatigue_matched[:2]),
                    )
                    _log_generation_attempt(topic, topic_source, attempt, max_attempts, f"validation_failed:{reason}")
                    _log_rejected_body(topic, topic_source, attempt, f"validation_failed:{reason}", title, post_text)
                    retry_correction = _build_retry_correction(f"validation_failed:{reason}")
                    retry_correction += (
                        "\nFórmulas repetidas detectadas en tu intento: "
                        + " | ".join("'%s'" % g for g in _fatigue_matched)
                        + ". Reescribí esas partes con vocabulario y estructura nuevos; "
                        "NO uses esas secuencias."
                    )
                    if attempt >= max_attempts:
                        _mark_topic_cooldown(topic, reason=f"validation_failed:{reason}")
                        generated_post = {"title": title, "body": post_text, "metadata": {"topic": topic, "validation_reason": reason}, "attempts": attempt, "published": False, "error": f"validation_failed:{reason}"}
                    continue

                # ── Gate de cifras verificadas (own_incident, patron arXiv) ──
                # La instruccion 'use them exactly' no alcanza: si el body no
                # incluye >= 2 de las cifras reales del incidente, el post es
                # generico y desperdicia material escaso. Rechazo + correccion
                # que nombra las cifras faltantes. Si agota reintentos, el
                # incidente NO se marca usado (no se quema).
                if _incident_figures:
                    # Minimo efectivo: con 1 sola figura distintiva se exige ESA
                    # (no puede degradarse a coincidencia). Con 0 no hay gate.
                    _min_figures = min(INCIDENT_MIN_FIGURES, len(_incident_figures))
                    present, missing = _count_incident_figures(post_text, _incident_figures)
                    logger.info(
                        "own_incident: cifras verificadas presentes %s/%s (faltan: %s)",
                        present, _min_figures, ", ".join(missing) if missing else "-",
                    )
                    if present < _min_figures:
                        reason = "missing_incident_figures"
                        logger.warning("Phase A: contenido invalido (reason=%s), reintentar...", reason)
                        _log_generation_attempt(topic, topic_source, attempt, max_attempts, f"validation_failed:{reason}")
                        _log_rejected_body(topic, topic_source, attempt, f"validation_failed:{reason}", title, post_text)
                        retry_correction = _build_retry_correction(f"validation_failed:{reason}")
                        if missing:
                            retry_correction += (
                                "\nCifras verificadas del incidente ausentes en el "
                                f"BODY de tu intento: {', '.join(missing[:6])}. "
                                "Abrí el PRIMER parrafo del body con el incidente "
                                "y escribí al menos dos de esas cifras textualmente "
                                "(el título no cuenta)."
                            )
                        if attempt >= max_attempts:
                            generated_post = {"title": title, "body": post_text, "metadata": {"topic": topic, "validation_reason": reason}, "attempts": attempt, "published": False, "error": f"validation_failed:{reason}"}
                        continue
                if is_similar_to_recent(post_text):
                    logger.warning("Phase A: contenido muy similar a posts recientes. Se descarta.")
                    _log_generation_attempt(topic, topic_source, attempt, max_attempts, "similar_recent")
                    _log_rejected_body(topic, topic_source, attempt, "similar_recent", title, post_text)
                    retry_correction = _build_retry_correction("similar_recent")
                    if attempt >= max_attempts:
                        generated_post = {"title": title, "body": post_text, "metadata": {"topic": topic, "validation_reason": "similar_recent"}, "attempts": attempt, "published": False, "error": "similar_recent"}
                    continue
                low_quality, low_quality_reason = _looks_low_quality(post_text, policy)
                if low_quality:
                    logger.warning("Phase A: contenido descartado por baja calidad (reason=%s), reintentar...", low_quality_reason)
                    _log_generation_attempt(topic, topic_source, attempt, max_attempts, low_quality_reason)
                    _log_rejected_body(topic, topic_source, attempt, low_quality_reason, title, post_text)
                    retry_correction = _build_retry_correction(low_quality_reason)
                    # TRACKEAR RECHAZADO: tokens gastados en contenido no usable (CADA intento)
                    try:
                        from services.karma_roi_tracker import track_action
                        track_action(
                            action_type="post_rejected",
                            phase="A",
                            cost_usd=_cost_usd,
                            input_tokens=_input_tokens,
                            output_tokens=_output_tokens,
                            model=_provider_name
                        )
                        logger.info("Karma ROI: Post rechazado trackeado (attempt %s/%s, reason=%s, cost=$%.6f)", attempt, max_attempts, low_quality_reason, _cost_usd)
                    except Exception as _e:
                        logger.warning("Karma ROI: Error trackeando rechazado: %s", _e)
                    if attempt >= max_attempts:
                        generated_post = {"title": title, "body": post_text, "metadata": {"topic": topic, "validation_reason": low_quality_reason, "input_tokens": _input_tokens, "output_tokens": _output_tokens, "total_cost_usd": _cost_usd}, "attempts": attempt, "published": False, "error": f"low_quality:{low_quality_reason}"}
                    continue
                _log_generation_attempt(topic, topic_source, attempt, max_attempts, "success")
                candidate_post = {"title": title, "body": post_text, "metadata": {"topic": topic, "generated_at": datetime.now(UTC).isoformat() + "Z", "attempts": attempt, "policy_tone": policy.get("style_policy", {}).get("tone", "natural_directo"), "historical_context": _historical_ctx, "input_tokens": _input_tokens, "output_tokens": _output_tokens, "total_cost_usd": _cost_usd}, "published": False}
                if not bestof_enabled:
                    generated_post = candidate_post
                    break
                # Best-of-N: acumular candidato válido y seguir generando hasta N.
                valid_candidates.append(candidate_post)
                retry_correction = ""  # candidatos independientes (sin corrección previa)
                if len(valid_candidates) >= bestof_n:
                    break

            # ── Post-selección best-of-N + auto-crítica (solo con flag activo) ──
            if bestof_enabled and valid_candidates:
                if len(valid_candidates) == 1:
                    generated_post = valid_candidates[0]
                else:
                    generated_post = await _pick_best_post(self.deps, valid_candidates, policy)
                if generated_post and not generated_post.get("error"):
                    generated_post = await _critique_pass(self.deps, generated_post, policy, incident_figures=_incident_figures)

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
            if max_per_day is not None and limit_now >= max_per_day:
                logger.info("Phase A: limite alcanzado justo antes de publicar (%s/%s). Post pospuesto.", limit_now, max_per_day)
                generated_post["error"] = "daily_limit_reached_before_publish"
                posts.append(generated_post)
                continue

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
                        # Trackear en karma ROI tracker
                        logger.info("Karma ROI: DEBUG - Intentando trackear post %s", post_id[:8] if post_id else "N/A")
                        try:
                            from services.karma_roi_tracker import track_action
                            logger.info("Karma ROI: DEBUG - Import exitoso")
                            cost_usd = generated_post.get("metadata", {}).get("total_cost_usd", 0.0)
                            input_tokens = generated_post.get("metadata", {}).get("input_tokens", 0)
                            output_tokens = generated_post.get("metadata", {}).get("output_tokens", 0)
                            track_action(
                                action_type="post",
                                moltbook_id=post_id,
                                phase="A",
                                cost_usd=cost_usd,
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                model="deepseek-v4-pro"
                            )
                            logger.info("Karma ROI: Post %s trackeado (costo: $%.6f)", post_id[:8], cost_usd)
                        except Exception as e:
                            logger.warning("Karma ROI: Error trackeando post %s: %s", post_id[:8], e)
                        _track_topic_performance(topic, post_id)
                        _record_topic_used(topic)
                        # Incidente real consumido SOLO al publicar: si el gate
                        # de calidad o la API fallan, no se quema el material.
                        if _incident and _incident.get("id"):
                            if mark_incident_used(_incident["id"]):
                                logger.info("Phase A: incidente real '%s' marcado como usado", _incident["id"])
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
                    # --- Reporta post a Telegram ---
                    try:
                        from services.telegram_client import TelegramClient
                        _tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
                        _tg_chat = os.getenv("TELEGRAM_CHAT_ID", "")
                        if _tg_token and _tg_chat:
                            _tg = TelegramClient(_tg_token, _tg_chat)
                            _topic_preview = topic[:60] if len(topic) > 60 else topic
                            _content_preview = generated_post.get("body", "")[:100].replace("\n", " ") if len(generated_post.get("body", "")) > 100 else generated_post.get("body", "")
                            _costo = generated_post.get("metadata", {}).get("total_cost_usd", 0.0)
                            _tokens = generated_post.get("metadata", {}).get("input_tokens", 0) + generated_post.get("metadata", {}).get("output_tokens", 0)
                            _msg = (
                                "📝 <b>POST GENERADO (Phase A)</b>\n"
                                "━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"<b>Tema:</b> {_topic_preview}\n"
                                f"<b>Preview:</b> {_content_preview}...\n"
                                "━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"<b>Tokens:</b> {_tokens}\n"
                                f"<b>Costo:</b> ${_costo:.6f} USD\n"
                                f"<b>Modelo:</b> deepseek-v4-pro\n"
                                "━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"<i>ROI: pendiente de medir a 1h / 24h</i>"
                            )
                            _tg.send_message(_msg)
                    except Exception:
                        pass
                    # --- Fin reporte Telegram ---

                    # ── Track historical examples used ──
                    mark_examples_used(generated_post["body"])

                    log_dual_score(generated_post["body"], phase="a")
                    logger.info(">>> [WIRE CHECK] Escribiendo dual_scores.jsonl (phase A)")

                    delay = random.randint(20, 45)
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
        if published_count == 0 and posts:
            # Etiqueta honesta del por que no se publico, para telemetria:
            # antes el retorno no incluia "skipped" y core.agent.py emitia
            # "no_content" incluso cuando el motivo era pacing o fallo de
            # generacion (etiqueta que ocultaba la causa real).
            errors = {p.get("error", "unknown") for p in posts}
            if "pacing_blocked" in errors:
                skip_reason = "pacing"
            elif "abstained" in errors:
                # Abstencion legitima: NO es un fallo de generacion.
                skip_reason = "abstained"
            elif errors & {"model_error", "empty_output"}:
                skip_reason = "generation_failed"
            elif errors & {"low_quality:below_min_quality_score"} or any(
                str(e).startswith("low_quality:") for e in errors
            ):
                skip_reason = "low_quality"
            elif errors:
                skip_reason = "generation_failed"
            else:
                skip_reason = "no_content"
            return {"posts_published": 0, "drafts_generated": len(posts), "posts": posts,
                    "success": False, "skipped": skip_reason}
        return {"posts_published": published_count, "drafts_generated": len(posts), "posts": posts, "success": published_count > 0}



