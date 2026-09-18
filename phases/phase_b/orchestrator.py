# -*- coding: utf-8 -*-
"""
Phase B — Community Replies
============================

Contrato de comportamiento
--------------------------
El agente responde a todos los comentarios relevantes en sus propios posts
(una vez por comentario), y solo responde en posts ajenos hasta un máximo
de unas pocas interacciones por post, priorizando siempre primero sus
propios posts.

El agente actúa como investigador-erudito: busca hilos donde su aporte
pueda subir la frontera del debate añadiendo un marco, métrica, guardrail
o failure mode que nadie ha mencionado aún, y evitando saturar hilos con
reiteraciones o respuestas vacías ("bot de acuerdo").

Prioridad absoluta: responder comentarios relevantes en posts propios.
  - Por cada comentario en un post propio:
    - Si es relevante y no ha sido respondido → responder UNA vez.
    - Si ya fue respondido (clave post_id:comment_id en _replied_comment_ids)
      → no responder de nuevo.
  - Por cada post propio:
    - Se permiten varios hilos de conversación, con un límite de
      max_comments_per_post (6 por defecto) replies totales del agente.

Prioridad secundaria: responder en posts ajenos del feed.
  - Por cada post ajeno, como máximo max_feed_comments_per_post (3) replies
    del agente en total (post + ramas), repartidos en el tiempo.
  - Solo responder cuando el contenido o la discusión son relevantes
    (umbral más estricto que en propios: min + 10).  Se priorizan hilos
    con "potencial de frontera": temas técnicos donde nadie ha cubierto
    aún métricas, guardrails o failure modes.
  - Cada comentario debe aportar al menos una de: métrica distinta,
    guardrail concreto, failure mode real, pregunta de investigación.
  - Límite diario de feed: max_feed_replies_per_day (3) para que la mayor
    parte de la energía vaya a los posts propios.
  - Los hilos con alto potencial de frontera se registran en la agenda
    de investigación para que Fase A genere un post dedicado.

Orden de ejecución en cada pasada de Fase B (execute):
  1) Revisar posts propios (_execute_own_post_replies → _process_own_post)
     y responder a todos los comentarios relevantes no respondidos todavía,
     mientras haya capacidad según los límites globales (día, ciclo, post).
  2) Solo después, y si queda capacidad (_execute_feed_replies), responder
     en posts ajenos siguiendo los límites por post ajeno y por día de feed.

Deduplicación:
  - La clave de "ya respondido" es f"{post_id}:{comment_id}".
  - Cada combinación se responde como máximo una vez.
  - Persistencia en data/replied_comment_ids.json.

Límites (desde config/agent_policy.py, overrideable vía env):
  max_comments_per_day        = None  — presupuesto diario total (propios + feed) — None = agente decide
  max_comment_replies_per_cycle = None  — por ciclo (~8 h) — None = agente decide
  max_comments_per_post        = None   — replies máximas del agente en un post propio — None = sin límite
  max_feed_comments_per_post   = None   — replies máximas del agente en un post ajeno — None = sin límite
  max_feed_replies_per_day     = None   — tope diario solo para feed replies — None = sin límite
"""

from .constants import (
    FORBIDDEN_PHRASES,
    COMMENT_STYLE_INSTRUCTIONS,
    _COLD_START_THRESHOLD,
    _COLD_START_MIN_SCORE,
    _cold_start_lock,
    MAX_CONVERSATION_DEPTH,
    _OWN_POST_REPLY_SCORE_LIMIT,
)
from .scoring import RelevanceDecision, _get_feed_min_score, text_has_fabricated_measurement, _triage_comment_value, set_watchlist_authors, _extract_author_name, text_has_unverifiable_historical_claim, text_exposes_figures, comment_off_topic, _extract_named_entities
from . import constants as _constants_mod


def is_likely_truncated(text: str) -> bool:
    """Detecta salida truncada del modelo LLM."""
    if not text or not text.strip():
        return True
    stripped = text.strip().rstrip(" ")
    if stripped[-1] not in '.!?':
        return True
    return False


def clean_llm_output(text: str) -> str:
    """Clean LLM artifacts from generated content before publishing.

    Strips special tokens, code fences, markdown headers, and excessive
    formatting that leaks from model output. Integrated from
    utils/content_validators.py (previously disconnected from pipeline).
    """
    if not text:
        return text
    modified = text

    # Remove special tokens from various LLM families
    special_tokens = ['<|im_start|>', '<|im_end|>', '<|eot_id|>',
                      '[INST]', '[/INST]', '<s>', '</s>']
    for token in special_tokens:
        modified = modified.replace(token, '')

    # Remove code fences (LLMs sometimes wrap replies in ```)
    if '```' in modified:
        modified = re.sub(r'```[\w]*\n?', '', modified)
        modified = modified.replace('```', '')

    # Remove markdown headers (not appropriate for social media replies)
    modified = re.sub(r'^#+\s+', '', modified, flags=re.MULTILINE)

    # Collapse excessive newlines
    modified = re.sub(r'\n{3,}', '\n\n', modified)

    return modified.strip()

import asyncio
import json
import logging
import os
import re
import requests
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Set, Tuple

from config.agent_policy import POLICY
from config import BASE_DIR
from config import behavior_cfg
from core.observability import send_event
from core.tracer import Span
from core.value_log import log_value_event
from phases.deps import PhaseBDeps
from patches.patch_phase_b_pre_generation_gate import should_skip_generation_pre_gate
from prompts.value_classifier import build_classifier_prompt
from prompts.prompt_templates import (
    REPLY_TEMPLATE, DEBATE_CONTINUATION_TEMPLATE, OLLAMA_FALLBACK_REPLY,
    get_reply_depth_directive, UNTRUSTED_DIRECTIVE, ABSTAIN_RULE,
    detect_prompt_injection, log_injection_attempt,
    HISTORICAL_CLAIM_DIRECTIVE, DATA_CONTRIBUTION_DIRECTIVE,
)
from core.claims_tracker import ClaimsTracker
from personality.modes import select_mode, get_mode_prompt
from services.dual_scoring import log_dual_score, compute_dual_score
from services.energy_knowledge_base import EnergyKnowledgeBase
from services.moltbook_api_client import APIResponse, is_parent_not_found_404
from services.dedup_store import DedupStore
from services import reply_cap
from services.persistence import enqueue_outbox, count_outbox_by_status
from services.abstain_tracker import record_abstain
from services.claim_checker import extract_claim, check_claim
from services.own_post_store import is_valid_post_id
from core.strategy_state import StrategyState
from core.memory_store import MemoryStore
from services.self_eval import update_today_metrics
from services.conversation_state import (
    can_continue_thread, register_agent_reply, update_open_questions,
    close_thread, is_thread_closed, get_or_create_thread,
)
from services.roadmap import load_roadmap
from services.used_examples_tracker import is_example_recently_used, mark_examples_used
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS

# Shadow de medición del adjudicador de fabricación (ETAPA 2, 20/08/2026):
# cada veredicto REAL/FABRICATION/fail-open del gate se registra aquí para
# calibrar acierto del ruteo a Groq compound-mini. Path sobreescribible en
# tests vía getattr(self, "_adjudicator_verdict_log_path", ...).
_ADJUDICATOR_VERDICT_LOG_PATH = Path("data") / "adjudicator_verdicts.jsonl"
from sklearn.metrics.pairwise import cosine_similarity
from utils.phase_utils import phase_error_boundary, validate_phase_deps

logger = logging.getLogger("phases.phase_b")


from utils.quality_flags import quality_bestof_enabled as _quality_bestof_enabled


_EIN_TECH_KEYWORDS = {
    "solid-state-battery": ["solid state", "solid-state", "battery", "batería", "ssb"],
    "sodium-ion": ["sodium", "sodio", "na-ion", "sodium-ion", "salt battery"],
    "green-hydrogen": ["hydrogen", "hidrógeno", "green steel", "electrolysis", "electrólisis", "h2", "molten oxide"],
    "agrivoltaics": ["agrivoltaic", "agripv", "agri-pv", "solar farm", "crop", "agriculture"],
}
_EIN_GENERIC_KEYWORDS = ["energy", "energía", "renewable", "renovable", "solar", "wind", "eólico",
                         "grid", "red eléctrica", "carbon", "carbono", "emission", "emisión",
                         "climate", "clima", "sustainable", "sostenible", "electricity", "electricidad",
                         "power", "electric", "storage", "almacenamiento", "battery", "batería"]


def _get_ein_context(text: str) -> str:
    try:
        text_lower = text.lower()
        matched_techs = set()
        for tech, keywords in _EIN_TECH_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                matched_techs.add(tech)
        if any(kw in text_lower for kw in _EIN_GENERIC_KEYWORDS):
            matched_techs.add("other")
        if not matched_techs:
            return ""
        kb = EnergyKnowledgeBase(BASE_DIR / "data/energy_intel.db")
        if not kb.available:
            return ""
        parts = []
        for tech in sorted(matched_techs):
            if tech == "other":
                claims = kb.get_recent_claims(limit=3)
            else:
                claims = kb.get_claims_by_technology(tech, limit=3)
            if claims:
                parts.append(f"--- Technology: {tech} ---")
                for c in claims:
                    title = (c.get("title") or "")[:120]
                    text_snippet = (c.get("claim_text") or "")[:300]
                    status = c.get("status", "unknown")
                    source = c.get("source_type", "unknown")
                    date = c.get("date_pub", "")
                    parts.append(f"  [{status}] {source} ({date}): {title} — {text_snippet}")
        if not parts:
            return ""
        lines = [
            "",
            "CONTEXT FROM EIN DATABASE:",
        ] + parts + [
            "The following is raw evidence (patents, funding, technical signals). "
            "Do NOT report it as news and do NOT mention it unless it directly "
            "supports a mechanism you are proposing about AI or agent systems. "
            "If it does not, ignore it entirely.",
            "",
        ]
        return "\n".join(lines)
    except Exception:
        return ""

# ── Cluster detection for ClaimsTracker ──────────────────────────────

_CLUSTER_KEYWORDS: Dict[str, List[str]] = {
    "infrastructure": ["circuit breaker", "observability", "kubernetes", "deployment",
                       "container", "orchestration", "scaling", "monitoring",
                       "latency", "throughput", "quota", "rate limit", "failover",
                       "recovery", "degradation"],
    "architecture": ["architecture", "pattern", "pipeline", "design", "state",
                     "cache", "retry", "fallback", "timeout", "workflow",
                     "orchestration", "stateless", "stateful"],
    "safety": ["guardrail", "injection", "sandbox", "permission", "isolation",
               "security", "alignment", "validation", "escalation", "audit",
               "privilege"],
    "evaluation": ["metric", "benchmark", "eval", "score", "throughput",
                   "latency", "cost", "trade-off", "comparison", "ab test", "a/b"],
    "historical": ["lessons", "post-mortem", "retro", "legacy", "migration",
                   "rewrite", "technical debt", "regression", "incident",
                   "2015", "2016", "2017", "2018", "2019", "2020"],
    "fringe": ["emergent", "agent", "tool", "memory", "reasoning",
               "planning", "self-modify", "meta", "agi", "singularity",
               "consciousness"],
}


def _detect_cluster(text: str) -> str:
    text_lower = text.lower()
    scores: Dict[str, int] = {}
    for cluster, keywords in _CLUSTER_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                scores[cluster] = scores.get(cluster, 0) + 1
    if not scores:
        return "infrastructure"
    return max(scores, key=scores.get)



def _strip_submolt_prefix(name: Any) -> str:
    """Normaliza un nombre de submolt a su forma canónica sin prefijo.

    Quita UN prefijo 'm/' inicial de forma correcta (prefix strip real).
    Importante: NO usar str.lstrip('m/'), que opera por conjunto de caracteres
    y mutila nombres como 'm/memory' → 'emory' o 'm/mvcc' → 'vcc'.
    """
    n = str(name).strip().lower()
    return n[2:] if n.startswith("m/") else n


def _load_allowed_submolts() -> frozenset:
    """Load allowed submolts from phase_b_strategy.yaml, with fallback defaults.

    Devuelve un frozenset de nombres CANÓNICOS sin prefijo 'm/', deduplicado.
    Antes se guardaban ambas variantes (con y sin 'm/') del mismo submolt, lo
    que ensuciaba los logs del gate con entradas repetidas
    (['agentstack','agentstack','ai','ai',...]). Ahora hay una sola forma por
    submolt; el matching normaliza el submolt entrante con _strip_submolt_prefix.
    """
    try:
        strategy_file = BASE_DIR / "config" / "phase_b_strategy.yaml"
        if strategy_file.exists():
            import yaml
            strategy = yaml.safe_load(strategy_file.read_text(encoding="utf-8")) or {}
            allowed = strategy.get("submolt_strategy", {}).get("allowed_submolts", [])
            if allowed:
                result = frozenset(
                    _strip_submolt_prefix(s) for s in allowed if str(s).strip()
                )
                logger.debug("_load_allowed_submolts: loaded from YAML: %s", sorted(result))
                return result
    except Exception as e:
        logger.warning("_load_allowed_submolts: failed to load from YAML: %s", e)
    # Fallback canónico (YAML no disponible): una sola forma por submolt,
    # incluye m/openclaw-explorers, m/agents y m/builds.
    default = frozenset({
        "agents", "general", "ai", "agentstack", "security", "aisafety",
        "technology", "infrastructure", "openclaw-explorers", "tooling",
        "memory", "builds", "buildlogs", "todayilearned", "aithoughts",
        "agentskills", "trading", "crypto", "agentfinance", "agenteconomy",
    })
    return default


ALLOWED_SUBMOLTS = _load_allowed_submolts()


def _load_tech_terms_vocabulary() -> frozenset:
    """Load hard tech-term vocabulary for the density gate from
    phase_b_strategy.yaml, with a fallback to the expanded static list."""
    try:
        strategy_file = BASE_DIR / "config" / "phase_b_strategy.yaml"
        if strategy_file.exists():
            import yaml
            strategy = yaml.safe_load(strategy_file.read_text(encoding="utf-8")) or {}
            terms = strategy.get("tech_terms_vocabulary", [])
            if terms:
                result = frozenset(str(t).strip().lower() for t in terms if str(t).strip())
                logger.debug("_load_tech_terms_vocabulary: loaded %d terms from YAML", len(result))
                return result
    except Exception as e:
        logger.warning("_load_tech_terms_vocabulary: failed to load from YAML: %s", e)
    # Fallback: expanded static list (40 terms) so senior-engineer vocabulary
    # is not filtered even if the YAML is missing or malformed.
    return frozenset({
        "latency", "token", "schema", "agent", "memory", "api",
        "cache", "retry", "error", "state", "context", "p99",
        "dag", "idempotency", "throughput", "bottleneck",
        "crdt", "mvcc", "consensus", "quorum", "serialization", "mutex",
        "deadlock", "raft", "paxos", "wal", "append-only", "merkle",
        "byzantine", "cap", "bac", "isolation", "linearizability", "causal",
        "monotonic", "garbage", "compaction", "lease", "fence", "sharding",
    })


TECH_TERMS_VOCABULARY = _load_tech_terms_vocabulary()


def _load_banned_openers() -> list:
    """Load banned opener phrases from phase_b_strategy.yaml."""
    try:
        strategy_file = BASE_DIR / "config" / "phase_b_strategy.yaml"
        if strategy_file.exists():
            import yaml
            strategy = yaml.safe_load(strategy_file.read_text(encoding="utf-8")) or {}
            openers = strategy.get("content_rules", {}).get("banned_openers", [])
            if openers:
                return [str(o) for o in openers]
    except Exception as e:
        logger.warning("_load_banned_openers: failed to load from YAML: %s", e)
    # v5.0 fallback banned openers — never include "Circuit breakers" as default
    return [
        "Great post!",
        "I agree completely.",
        "Thanks for sharing.",
        "Great point",
        "I agree",
        "Well said",
    ]


BLOCKED_SUBMOLTS = {
    "introductions", "m/introductions",
    "announcements", "m/announcements",
    "philosophy", "m/philosophy",
    "existential", "m/existential",
    "consciousness", "m/consciousness",
    "ponderings", "m/ponderings",
    "bts", "m/bts",
    "blesstheirhearts", "m/blesstheirhearts",
}

SUBMOLT_ONLY_GENERAL = {"general", "m/general"}


def is_near_duplicate_reply(candidate: str, previous: str, threshold: float = 0.6) -> bool:
    """Compara dos textos usando solapamiento de bigramas (stdlib only).
    Retorna True si el candidato es demasiado similar al previo."""
    if not candidate or not previous:
        return False

    def _token_set(text: str) -> set:
        clean = re.sub(r"[^\w\sáéíóúñü]", "", text.lower())
        words = clean.split()
        bigrams = set()
        for i in range(len(words) - 1):
            bigrams.add(f"{words[i]} {words[i+1]}")
            bigrams.add(words[i])
        if words:
            bigrams.add(words[-1])
        return bigrams

    cand_set = _token_set(candidate)
    prev_set = _token_set(previous)
    if not cand_set or not prev_set:
        return False
    intersection = cand_set & prev_set
    union = cand_set | prev_set
    similarity = len(intersection) / len(union)
    return similarity >= threshold


def is_semantic_duplicate_reply(candidate: str, previous: str, threshold: float = 0.72) -> bool:
    if not candidate.strip() or not previous.strip():
        return False
    tfidf = TfidfVectorizer().fit_transform([candidate, previous])
    sim = cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
    return sim >= threshold


# ── Same-thread paraphrase detection (guard de repeticion por post) ──
# El TF-IDF con threshold 0.80 dejaba pasar parafrasis reales del mismo
# argumento (0.23-0.27 de similitud medidas en el hilo de bytes). Senal
# combinada, scoped al MISMO post: TF-IDF >= 0.45 O Dice de content-words
# >= 0.30. Calibrada con las frases reales del hilo (Dice 0.43-0.55) y con
# replies legitimamente distintas del mismo thread (Dice ~0, no bloquea).
_SAME_THREAD_TFIDF_THRESHOLD = 0.45
_SAME_THREAD_DICE_THRESHOLD = 0.30


def _content_words(text: str) -> set:
    clean = re.sub(r"[^\w\sáéíóúñü]", " ", text.lower())
    return {
        w for w in clean.split()
        if len(w) > 1 and w not in ENGLISH_STOP_WORDS
    }


def is_same_thread_duplicate_reply(candidate: str, previous: str) -> bool:
    """True si candidate repite el argumento de previous (mismo post).

    Señal combinada: similitud TF-IDF baja (0.45) O solapamiento Dice de
    palabras de contenido (0.30). Solo debe usarse comparando contra los
    comentarios previos del AGENTE en el MISMO post (guard de repeticion),
    no cross-post."""
    if not candidate or not previous:
        return False
    if is_semantic_duplicate_reply(candidate, previous, threshold=_SAME_THREAD_TFIDF_THRESHOLD):
        return True
    a = _content_words(candidate)
    b = _content_words(previous)
    if not a or not b:
        return False
    inter = len(a & b)
    if inter == 0:
        return False
    dice = 2 * inter / (len(a) + len(b))
    return dice >= _SAME_THREAD_DICE_THRESHOLD


# ── Cross-cycle reply history (anti-duplicate) ─────────────────
_REPLY_HISTORY_PATH = BASE_DIR / "data" / "reply_history.json"
_REPLY_HISTORY_MAX = 50


def _load_reply_history() -> List[str]:
    try:
        if _REPLY_HISTORY_PATH.exists():
            data = json.loads(_REPLY_HISTORY_PATH.read_text(encoding="utf-8"))
            return data.get("replies", []) if isinstance(data, dict) else []
    except Exception:
        pass
    return []


def _save_reply_history(replies: List[str]) -> None:
    try:
        _REPLY_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _REPLY_HISTORY_PATH.write_text(
            json.dumps({"replies": replies[-_REPLY_HISTORY_MAX:]}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _append_to_reply_history(text: str) -> None:
    history = _load_reply_history()
    history.append(text)
    _save_reply_history(history)


def _is_semantic_dupe_against_history(candidate: str, threshold: float = 0.80) -> bool:
    for prev in _load_reply_history():
        if is_semantic_duplicate_reply(candidate, prev, threshold=threshold):
            return True
    return False


def _safe_truncate(text: str, max_chars: int = 500) -> str:
    """Trunca en un límite de caracteres, cortando en límite de frase."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_boundary = max(
        truncated.rfind(". "),
        truncated.rfind("! "),
        truncated.rfind("? "),
        truncated.rfind(".\n"),
        truncated.rfind("!\n"),
        truncated.rfind("?\n"),
        truncated.rfind(".  "),
    )
    if last_boundary > max_chars // 2:
        return text[: last_boundary + 1]
    return truncated.rstrip() + "..."


_REPLIED_IDS_PATH = BASE_DIR / "data/replied_comment_ids.json"
_COMMENTED_POSTS_PATH = BASE_DIR / "data/commented_post_ids.json"
_AGENT_COMMENT_IDS_PATH = BASE_DIR / "data/agent_comment_ids.json"
_REPLIED_THREAD_AUTHORS_PATH = BASE_DIR / "data/replied_thread_authors.json"
_REPLIED_TOPIC_FINGERPRINTS_PATH = BASE_DIR / "data/replied_topic_fingerprints.json"
_POST_HISTORY_GUARD_PATH = BASE_DIR / "data/post_history_guard.json"
_PERSONA_STYLE_PATH = BASE_DIR / "config/persona_style.json"
_PERFORMANCE_SUMMARY_PATH = BASE_DIR / "data/performance_summary.json"
_UPVOTED_POST_IDS_PATH = BASE_DIR / "data/upvoted_post_ids.json"
_FOLLOWED_AGENTS_PATH = BASE_DIR / "data/followed_agents.json"
# Re-export of the shared anti-dogpile counter path (authoritative: services/reply_cap)
_REPLIES_PER_POST_PATH = reply_cap._REPLIES_PER_POST_PATH

_FEED_STALL_STATE_FILE = Path("data/phase_b_feed_stall.json")

# Marcador de resaltado de resultados de busqueda semantica (⟦HL⟧...⟦/HL⟧):
# un body que lo contiene es un SNIPPET, no un post real. Se rehidrata por id
# o se descarta antes de evaluarlo como candidato.
_HL_MARKER = "⟦HL⟧"

# ── Concesion del interlocutor: no seguir discutiendo a quien ya concedio ──
_CONCESSION_MARKERS = (
    "fair correction", "you're right", "you are right", "i accept", "i agree",
    "agreed", "conceded", "good point", "great point", "well said",
    "makes sense", "fair enough", "that is true", "thanks for sharing",
)
_CONCESSION_WORD_RE = re.compile(r"\b(agreed|conceded|accepted|correct)\b", re.IGNORECASE)

# ── Promocion comercial: no responder publicidad ──
_PROMO_INSTALL_RE = re.compile(
    r"\b(pip|pip3|npm|yarn|uv|poetry|openclaw)\s+(install|i|add)\b",
    re.IGNORECASE,
)
_PROMO_ENV_APPEND_RE = re.compile(r"echo\s+[^\n]*>>\s*\.env", re.IGNORECASE)


def _load_feed_stall_count() -> int:
    try:
        if _FEED_STALL_STATE_FILE.exists():
            return int(json.loads(_FEED_STALL_STATE_FILE.read_text(encoding="utf-8")).get("consecutive_empty_cycles", 0))
    except Exception:
        pass
    return 0


def _save_feed_stall_count(count: int) -> None:
    try:
        _FEED_STALL_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _FEED_STALL_STATE_FILE.write_text(json.dumps({"consecutive_empty_cycles": count}), encoding="utf-8")
    except Exception as e:
        logger.debug("Phase B: no se pudo persistir feed_stall state: %s", e)


def _load_replied_comment_ids() -> Set[str]:
    if not _REPLIED_IDS_PATH.exists():
        return set()
    try:
        data = json.loads(_REPLIED_IDS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(data)
    except Exception:
        logger.warning("No se pudo cargar replied_comment_ids, iniciando vacío")
    return set()


def _save_replied_comment_ids(ids: Set[str]) -> None:
    try:
        _REPLIED_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _REPLIED_IDS_PATH.write_text(
            json.dumps(sorted(ids), ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("No se pudo guardar replied_comment_ids: %s", e)


def _load_commented_post_ids() -> Dict[str, str]:
    """Load post_id -> iso_timestamp dict, filtering out entries > 7 days old.
    Migrates old-format list to dict automatically."""
    if not _COMMENTED_POSTS_PATH.exists():
        return {}
    try:
        data = json.loads(_COMMENTED_POSTS_PATH.read_text(encoding="utf-8"))
        now = datetime.now(timezone.utc)

        # Migrate old list format: [id1, id2] -> {id1: now, id2: now}
        if isinstance(data, list):
            return {pid: now.isoformat() for pid in data if isinstance(pid, str)}

        # Dict format: {id: timestamp}
        if isinstance(data, dict):
            cutoff = now - timedelta(days=7)
            result = {}
            for pid, ts in data.items():
                if not isinstance(pid, str):
                    continue
                try:
                    ts_dt = datetime.fromisoformat(ts) if isinstance(ts, str) else now
                    if ts_dt >= cutoff:
                        result[pid] = ts
                except (ValueError, TypeError):
                    result[pid] = ts  # keep if unparseable
            return result
    except Exception:
        logger.warning("No se pudo cargar commented_post_ids, iniciando vacío")
    return {}


def _filter_valid_post_id_keys(ids: Dict[str, Any], source: str) -> Dict[str, Any]:
    """Return a copy of ``ids`` keeping only entries whose key is a valid UUID
    post_id. Invalid keys (non-str like None/int, or non-UUID strings) are
    discarded and logged at WARNING with the offending value.

    is_valid_post_id() calls re.match and raises TypeError on non-str input,
    so we guard the type before calling it.
    """
    filtered: Dict[str, Any] = {}
    for key, value in ids.items():
        try:
            valid = isinstance(key, str) and is_valid_post_id(key)
        except Exception:
            valid = False
        if valid:
            filtered[key] = value
        else:
            logger.warning("%s: descartando entrada con post_id invalido=%r", source, key)
    return filtered


def _save_commented_post_ids(ids: Dict[str, str]) -> None:
    """Save commented_post_ids dict, preserving existing timestamps for known entries.
    Filters out entries with invalid (non-UUID) post_id keys before writing."""
    try:
        ids = _filter_valid_post_id_keys(ids, "commented_post_ids")
        _COMMENTED_POSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _COMMENTED_POSTS_PATH.write_text(
            json.dumps(ids, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("No se pudo guardar commented_post_ids: %s", e)


# ── Agent own comment IDs persistence ─────────────────────

def _load_agent_comment_ids() -> Dict[str, List[str]]:
    if not _AGENT_COMMENT_IDS_PATH.exists():
        return {}
    try:
        data = json.loads(_AGENT_COMMENT_IDS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): [str(x) for x in v] if isinstance(v, list) else [] for k, v in data.items()}
    except Exception:
        logger.warning("No se pudo cargar agent_comment_ids, iniciando vacío")
    return {}


def _save_agent_comment_ids(ids: Dict[str, List[str]]) -> None:
    """Save agent_comment_ids dict. Filters out entries with invalid (non-UUID)
    post_id keys before writing."""
    try:
        ids = _filter_valid_post_id_keys(ids, "agent_comment_ids")
        _AGENT_COMMENT_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _AGENT_COMMENT_IDS_PATH.write_text(
            json.dumps(ids, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("No se pudo guardar agent_comment_ids: %s", e)


# ── Upvoted post IDs persistence ──────────────────────────

def _load_upvoted_post_ids() -> Set[str]:
    if not _UPVOTED_POST_IDS_PATH.exists():
        return set()
    try:
        data = json.loads(_UPVOTED_POST_IDS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(str(x) for x in data)
    except Exception:
        logger.warning("No se pudo cargar upvoted_post_ids, iniciando vacío")
    return set()


def _save_upvoted_post_ids(ids: Set[str]) -> None:
    try:
        _UPVOTED_POST_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _UPVOTED_POST_IDS_PATH.write_text(
            json.dumps(sorted(ids), ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("No se pudo guardar upvoted_post_ids: %s", e)


# ── Followed agents persistence ───────────────────────────

def _load_followed_agent_names() -> Set[str]:
    if not _FOLLOWED_AGENTS_PATH.exists():
        return set()
    try:
        data = json.loads(_FOLLOWED_AGENTS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return set(str(x) for x in data.get("following", []))
        if isinstance(data, list):
            return set(str(x) for x in data)
    except Exception:
        logger.warning("No se pudo cargar followed_agents, iniciando vacío")
    return set()


def _save_followed_agent_names(names: Set[str]) -> None:
    try:
        _FOLLOWED_AGENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _FOLLOWED_AGENTS_PATH.write_text(
            json.dumps({"following": sorted(names), "unfollowed": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("No se pudo guardar followed_agents: %s", e)


def _load_post_history_guard() -> Dict[str, str]:
    if not _POST_HISTORY_GUARD_PATH.exists():
        return {}
    try:
        data = json.loads(_POST_HISTORY_GUARD_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        logger.warning("No se pudo cargar post_history_guard, iniciando vacío")
    return {}


def _save_post_history_guard(ids: Dict[str, str]) -> None:
    try:
        _POST_HISTORY_GUARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        _POST_HISTORY_GUARD_PATH.write_text(
            json.dumps(ids, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("No se pudo guardar post_history_guard: %s", e)


class PhaseB:
    def __init__(self, deps: PhaseBDeps):
        self.deps = deps
        validate_phase_deps(deps, ["model_cascade", "moltbook_client", "behavior_cfg"])
        self.api = deps.moltbook_client
        self.llm = deps.model_cascade
        self.agent_name = deps.agent_name
        behavior = deps.behavior_cfg or {}
        self.get_comments_today = deps.get_comments_today or (lambda: 0)
        self.incr_comments_today = deps.increment_comments_today or (lambda: 0)

            # None values from behavior_cfg or AgentPolicy will be used
        # None values from behavior_cfg or AgentPolicy will be used
        # If behavior_cfg has None, the agent's internal limits (also None) apply
        self.max_comments_per_post = behavior.get("max_comments_per_post", None)  # None = sin límite
        self.max_comments_per_day = behavior.get("max_comments_per_day", None)  # None = sin límite
        self.max_replies_per_cycle = behavior.get("max_comment_replies_per_cycle", None)  # None = sin límite
        self.max_feed_comments_per_post = behavior.get("max_feed_comments_per_post", None)  # None = sin límite
        self.max_own_posts_per_cycle = behavior.get("phase_b_max_own_posts_per_cycle", None)  # None = sin límite
        # El aplanado de replies anidados expone 300+ comentarios por post;
        # sin este cap un solo post monopolizaba el ciclo (85 min) y dejaba
        # sin ejecutar feed/follow-ups ni responder al stop graceful.
        self.max_own_comments_per_cycle = behavior.get(
            "phase_b_max_own_comments_per_cycle",
            int(os.getenv("AGENT_PHASE_B_MAX_OWN_COMMENTS_PER_CYCLE", "10")),
        )
        # v5.2+: tamaño de la cola global de comentarios propios sin responder
        # procesados por ciclo (todos los posts, ordenada watchlist→recencia).
        self.own_queue_per_cycle = behavior.get(
            "phase_b_own_queue_per_cycle",
            int(os.getenv("AGENT_PHASE_B_OWN_QUEUE_PER_CYCLE", "10")),
        )
        # ── Watchlist: autores de alta autoridad ───────────────────
        self._watchlist_authors: Set[str] = self._load_watchlist_authors()
        set_watchlist_authors(self._watchlist_authors)
        self._watchlist_max_per_author_day: int = int(os.getenv(
            "AGENT_MAX_PER_WATCHLIST_AUTHOR_DAY", "5"))
        self._watchlist_author_count_today: Dict[str, int] = {}
        self._watchlist_count_path: Path = BASE_DIR / "data" / "watchlist_count_today.json"
        self._load_watchlist_count()
        self.delay_between_comments = behavior.get("delay_between_comments", 8)
        # ── Anti-dogpile: hard per-post reply cap (env-only, NOT auto-optimizable) ──
        self.max_replies_per_post = reply_cap.get_cap()
        self._replies_per_post_path: Path = reply_cap._REPLIES_PER_POST_PATH
        # ── Threaded follow-ups: per-post cap independiente del anti-dogpile ──
        self.max_followups_per_post = reply_cap.get_followups_cap()
        self._followups_per_post_path: Path = reply_cap._FOLLOWUPS_PER_POST_PATH
        # ── Techo TOTAL por post-raiz (backstop anti-dogpile, todas las vias) ──
        self._total_replies_per_post_path: Path = reply_cap._TOTAL_REPLIES_PER_POST_PATH
        self._last_comment_per_thread: Dict[str, str] = {}
        # v5.5+: cooldown de candidatos de la cola propia que fallan el
        # decisor (TTL 30 min por decisión negativa y razón determinista).
        # Evita re-evaluar el mismo comentario zombie ciclo tras ciclo.
        self._own_queue_skip_cooldown: Dict[str, datetime] = {}
        # v5.9: cache del ROI por canal (gate de critica data-driven). Se
        # rellena en la primera critica del ciclo, no por cada reply.
        self._roi_channels_cache: Optional[Dict[str, float]] = None
        self._dedup = DedupStore()
        self._dedup.cleanup(older_than_hours=24)
        self._dedup.cleanup(older_than_hours=720)  # v5.0: 30-day deep cleanup
        self._replied_comment_ids: Set[str] = self._dedup.get_replied_comment_ids()
        # Hilos donde ya respondimos UNA sintesis post-concesion: una nueva
        # concesion del interlocutor cierra el hilo (no se sigue discutiendo).
        self._concession_answered: Set[str] = set()
        self._commented_post_ids: Dict[str, str] = self._dedup.get_commented_post_ids()
        self._agent_comment_ids: Dict[str, List[str]] = self._dedup.get_agent_comment_ids()
        self._replied_topic_fingerprints: Set[str] = self._dedup.get_replied_topic_fingerprints()
        self._post_history_guard: Dict[str, str] = _load_post_history_guard()

        # ── New capabilities: upvotes, following, semantic search ──
        self._upvoted_post_ids: Set[str] = self._dedup.get_upvoted_post_ids()
        self._followed_agent_names: Set[str] = self._dedup.get_followed_agents()
        self._upvotes_enabled: bool = os.getenv("UPVOTES_ENABLED", "true").lower() == "true"
        self._max_upvotes_per_cycle: int = int(os.getenv("MAX_UPVOTES_PER_CYCLE", "3"))
        self._upvotes_this_cycle: int = 0
        self._following_enabled: bool = os.getenv("FOLLOWING_ENABLED", "true").lower() == "true"
        self._max_follows_per_cycle: int = int(os.getenv("MAX_FOLLOWS_PER_CYCLE", "2"))
        self._follows_this_cycle: int = 0
        self._semantic_search_enabled: bool = os.getenv("SEMANTIC_SEARCH_ENABLED", "true").lower() == "true"
        self._semantic_search_max_queries: int = int(os.getenv("SEMANTIC_SEARCH_MAX_QUERIES", "2"))
        self._semantic_search_limit: int = int(os.getenv("SEMANTIC_SEARCH_LIMIT", "15"))
        self._pending_home_post_ids: Set[str] = getattr(deps, 'pending_home_post_ids', None) or set()
        self._stats: Dict[str, int] = {
            "fetched_own": 0, "fetched_feed": 0, "fetched": 0,
            "passed_relevance": 0, "passed_value": 0, "deduplicated": 0, "replied": 0,
            "debate_continuations": 0, "claim_check_passed": 0, "claim_check_failed": 0,
            "semantic_candidates": 0,
        }
        self._last_claim_check: Optional[Dict[str, Any]] = None
        self._memory = MemoryStore()

    # ── Relevance layer ───────────────────────────────────────────

    _TECH_KEYWORDS = frozenset({
        # ── English tech terms for the platform (autonomous agents, AI, software) ──
        "agent", "ai", "model", "data", "system", "error", "loop", "policy",
        "api", "sensor", "robot", "neural", "energy", "grid", "performance",
        "log", "monitor", "observability", "cascade", "prompt", "token",
        "llm", "autonomous", "tool", "function", "deployment", "pipeline",
        "latency", "throughput", "security", "architecture", "design",
        "memory", "reasoning", "planning", "benchmark", "metric",
        "circuit breaker", "rate limit", "guardrail", "fallback",
        "scaling", "orchestration", "container", "kubernetes",
        "inference", "fine-tuning", "embedding", "vector",
    })

    @staticmethod
    def _compute_relevance_score(comment: Dict[str, Any]) -> int:
        from .scoring import _compute_relevance_score
        return _compute_relevance_score(comment, tech_keywords=PhaseB._TECH_KEYWORDS)

    @staticmethod
    def _passes_density_gate(text_lower: str) -> bool:
        """True if text has 2+ hard tech terms AND 1+ metric/data-structure.

        Shared by the semantic density gate and the relevance bypass so both
        use the exact same definition of 'high technical substance'.
        """
        tech_count = sum(1 for term in TECH_TERMS_VOCABULARY if term in text_lower)
        data_structures = ("tree", "queue", "graph", "buffer")
        has_data_structure = any(ds in text_lower for ds in data_structures)
        has_number = bool(re.search(r"\d", text_lower))
        has_percent = "%" in text_lower
        has_metric_or_structure = has_number or has_percent or has_data_structure
        return tech_count >= 2 and has_metric_or_structure

    @staticmethod
    def _decide_reply(
        comment: Dict[str, Any],
        limit_ok: bool = True,
        is_own_post_reply: bool = False,
        post_text: str = "",
    ) -> RelevanceDecision:
        from .scoring import _decide_reply
        return _decide_reply(PhaseB, comment, limit_ok, is_own_post_reply, tech_keywords=PhaseB._TECH_KEYWORDS, post_text=post_text)

    @staticmethod
    def _decide_reply_from_post(post_body: str, comments: Optional[List[Dict]] = None, *, post: Optional[Dict] = None) -> RelevanceDecision:
        from .scoring import _decide_reply_from_post
        return _decide_reply_from_post(post_body, comments, tech_keywords=PhaseB._TECH_KEYWORDS, post=post)

    @staticmethod
    def _has_explicit_addressing(text: str) -> bool:
        from .scoring import _has_explicit_addressing
        return _has_explicit_addressing(text)

    @staticmethod
    def _extract_source_terms(text: str) -> Set[str]:
        from .scoring import _extract_source_terms
        return _extract_source_terms(text)

    @staticmethod
    def _reply_mentions_source_terms(reply_text: str, source_text: str) -> bool:
        from .scoring import _reply_mentions_source_terms
        return _reply_mentions_source_terms(reply_text, source_text)

    @staticmethod
    def _reply_has_ungrounded_numeric_specificity(reply_text: str, source_text: str) -> bool:
        from .scoring import _reply_has_ungrounded_numeric_specificity
        return _reply_has_ungrounded_numeric_specificity(reply_text, source_text)

    @staticmethod
    def _reply_has_guardrail_template(reply_text: str) -> bool:
        from .scoring import _reply_has_guardrail_template
        return _reply_has_guardrail_template(reply_text)

    @staticmethod
    def _reply_has_ungrounded_named_entity(reply_text: str, source_text: str) -> bool:
        from .scoring import _reply_has_ungrounded_named_entity
        return _reply_has_ungrounded_named_entity(reply_text, source_text)

    @staticmethod
    def _reply_has_secondhand_causal_attribution(reply_text: str) -> bool:
        from .scoring import _reply_has_secondhand_causal_attribution
        return _reply_has_secondhand_causal_attribution(reply_text)

    def _reply_theme_fingerprint(self, reply_text: str, source_text: str = "") -> str:
        text = f"{reply_text or ''} {source_text or ''}".lower()
        theme_terms = [
            term for term in (
                "guardrail", "failure", "threshold", "latency", "telemetry",
                "metric", "observability", "rate limit", "retry", "backoff",
                "rollback", "canary", "validation", "instrumentation",
            )
            if term in text
        ]
        if not theme_terms:
            theme_terms = sorted(
                list(self._extract_source_terms(reply_text))[:3]
            )
        return "|".join(theme_terms)

    @staticmethod
    def _passes_quality_gate(text: str, require_evidence: bool = False) -> bool:
        """v5.1 quality gate: length + banned openers + (opcional) señales de
        sustancia. Score decides upstream.

        The abstraction constraint (no company names / calendar years) and the
        math constraints are enforced structurally in the prompt, not via
        brittle regex here.

        require_evidence=True (replies tier=quality a autores watchlist):
        el reply debe aportar evidencia o métrica concreta — un comentario
        sin señal de sustancia (evidence=false y metric=false) es ruido de
        baja calidad y NO se publica.
        """

        if not text or not text.strip():
            return False
        text_stripped = text.strip()
        text_len = len(text_stripped)

        # ── Length gate (40-600 characters) ──
        if text_len < 40 or text_len > 600:
            logger.debug("Phase B: quality gate failed — length=%d (expected 40-600)", text_len)
            return False

        # ── Banned openers ──
        text_lower = text_stripped.lower()
        banned_openers = _load_banned_openers()
        for opener in banned_openers:
            if text_lower.startswith(opener.lower()):
                logger.debug("Phase B: quality gate failed — banned opener '%s'", opener)
                return False

                # ── Evidence/framework/metric/mechanism signals ──
        has_evidence = any(s in text_lower for s in [
            # Evidencia empírica (original)
            "measured", "observed", "in production", "data shows",
            "we deployed", "we saw", "we hit", "the result was",
            # Análisis técnico / reasoning (nuevo - solo si hay sustancia)
            "the failure", "the boundary", "the limit", "breaks when",
            "fails under", "invariant", "causal", "mechanism",
        ])
        has_framework = any(s in text_lower for s in [
            "propose", "pattern", "framework", "architecture",
            "design", "principle", "the approach", "strategy",
        ])
        has_metric = any(c.isdigit() for c in text)

        # Mecanismos técnicos cuentan como sustancia
        mechanism_terms = [
            # Sistemas distribuidos (original)
            "idempot", "rollback", "watermark", "checkpoint",
            "circuit breaker", "backoff", "retry", "commit",
            "schema", "invariant", "state machine", "consensus",
            "quorum", "ledger", "write-ahead", "dead letter",
            "dedup", "lease", "fencing", "sharding", "causal",
            # ML / Signal processing
            "compression", "gradient", "barrier", "sine", "swept",
            "descriptor", "drift", "onset", "density", "nonstat",
            "derivation", "stamping", "falsification", "trigger",
            "scar", "subspace", "re-derivation",
            # Fronteras y condiciones de borde
            "boundary", "edge case", "corner case", "breaks at",
            "fails when", "threshold", "limit", "condition",
        ]
        mechanism_hits = sum(1 for term in mechanism_terms if term in text_lower)
        has_mechanism = mechanism_hits >= 1 and len(text_stripped.split()) >= 12

        # Detección de derivación / explicación causal (cuarta clase de sustancia)
        has_derivation = any(s in text_lower for s in [
            "because", "therefore", "thus", "implies", "leads to",
            "causes", "enables", "prevents", "ensures",
        ]) and len(text_stripped.split()) >= 15

        if require_evidence and not (has_evidence or has_metric or has_mechanism or has_derivation):
            logger.info(
                "Phase B: quality gate REJECTED (tier=quality sin señal de sustancia) "
                "len=%d evidence=%s metric=%s mechanism=%s derivation=%s preview=%s",
                text_len, has_evidence, has_metric, has_mechanism, has_derivation,
                text_stripped[:80],
            )
            return False

        logger.info(
            "Phase B: quality gate signal check len=%d evidence=%s "
            "framework=%s metric=%s mechanism=%s",
            text_len, has_evidence, has_framework, has_metric, has_mechanism,
        )
        return True

    # ── Safety filters for publishing ────────────────────────────────

    @staticmethod
    def _is_prompt_leak(text: str) -> bool:
        """Detect if the LLM returned raw prompt instructions instead of a reply."""
        leak_signals = [
            "TASK:", "RULES:", "OUTPUT ONLY", "POST Content:",
            "Write ONE brief reply", "Max 150 chars",
            "system_prompt", "user_prompt", "assistant_prompt",
            "You are a senior systems engineer",
            "STYLE POLICY FOR RESPONSES",
            "HARD CONSTRAINTS:",
            "RESPONSE FORMAT (mandatory structure)",
            "ANCHOR:", "EVIDENCE:", "FRAMEWORK:",
            "Do NOT use emojis, hashtags",
            "```json", "```python",
        ]
        text_check = text[:800]
        # Gate anti-fuga (23/08/2026): una sola senal fuerte de razonamiento/
        # echo de prompt bloquea — no exigir 2 coincidencias debiles. Caso
        # real publicado: 'Here's a thinking process:' en una reply.
        from services.quality_governor import text_has_reasoning_leak
        if text_has_reasoning_leak(text_check):
            return True
        matches = sum(1 for s in leak_signals if s in text_check)
        return matches >= 2

    @staticmethod
    def _meets_minimum_quality(text: str) -> bool:
        """Reject replies that are generic questions without substance."""
        text_stripped = text.strip()
        # Known safe canned responses (concession closures, etc)
        SAFE_CANNED = ["good. this clarifies the boundary"]
        if any(text_stripped.lower().startswith(s) for s in SAFE_CANNED):
            return True
        # Too short
        if len(text_stripped) < 60:
            return False
        # Pure question with no substance (under 120 chars and ends with ?)
        if len(text_stripped) < 120 and text_stripped.endswith("?"):
            has_specifics = bool(re.search(r'\d+|[A-Z][a-z]+[A-Z]|p\d{2}|ms\b|%', text_stripped))
            if not has_specifics:
                return False
        # Generic question starters without substance
        generic_starters = [
            "what specific", "how would you", "clarify",
            "what are the implications", "how can we design",
            "what metrics would", "ask a tech q",
        ]
        text_lower = text_stripped.lower()
        if any(text_lower.startswith(s) for s in generic_starters) and len(text_stripped) < 150:
            return False
        # Contains prompt instructions
        if "TASK:" in text_stripped or "RULES:" in text_stripped:
            return False
        return True

    def _strip_forbidden_phrases(self, text: str) -> str:
        """Remove forbidden phrases from reply text."""
        result = text
        for phrase in FORBIDDEN_PHRASES:
            lower_result = result.lower()
            lower_phrase = phrase.lower()
            while lower_phrase in lower_result:
                idx = lower_result.find(lower_phrase)
                result = result[:idx] + result[idx + len(phrase):]
                lower_result = result.lower()
        result = re.sub(r'  +', ' ', result)
        result = re.sub(r'^\s+', '', result, flags=re.MULTILINE)
        return result.strip()

    def _sanitize_references(self, text: str) -> str:
        """Minimal cleanup — no longer strips company names or years."""
        text = re.sub(r'  +', ' ', text).strip()
        if text and text[0].islower():
            text = text[0].upper() + text[1:]
        return text

    def _get_agent_reply_count_in_post(self, post_id: str) -> int:
        """Count how many replies the agent already has in this post."""
        agent_comments = self._dedup.get_agent_comment_ids()
        existing = agent_comments.get(post_id, [])
        return len(existing)

    def _get_replies_per_post(self, post_id: str) -> int:
        """Monotonic anti-dogpile counter for a post (shared with Phase C)."""
        path = getattr(self, "_replies_per_post_path", None) or reply_cap._REPLIES_PER_POST_PATH
        return reply_cap.get_replies_for_post(post_id, path=path)

    def _increment_replies_per_post(self, post_id: str) -> int:
        """Increment and atomically persist the shared monotonic counter.
        Never decremented — deleted comments still count toward the cap."""
        path = getattr(self, "_replies_per_post_path", None) or reply_cap._REPLIES_PER_POST_PATH
        return reply_cap.increment_replies_for_post(post_id, path=path)

    def _get_followups_count(self, post_id: str) -> int:
        """Monotonic per-post threaded follow-up counter (separate budget from
        the anti-dogpile top-level counter)."""
        path = getattr(self, "_followups_per_post_path", None) or reply_cap._FOLLOWUPS_PER_POST_PATH
        return reply_cap.get_followups_for_post(post_id, path=path)

    def _increment_followups_count(self, post_id: str) -> int:
        """Increment and atomically persist the per-post follow-up counter."""
        path = getattr(self, "_followups_per_post_path", None) or reply_cap._FOLLOWUPS_PER_POST_PATH
        return reply_cap.increment_followups_for_post(post_id, path=path)

    def _get_total_replies_for_post(self, post_id: str) -> int:
        """Contador TOTAL de replies del agente en un post (todas las vias)."""
        path = getattr(self, "_total_replies_per_post_path", None) or reply_cap._TOTAL_REPLIES_PER_POST_PATH
        return reply_cap.get_total_replies_for_post(post_id, path=path)

    def _increment_total_replies_for_post(self, post_id: str) -> int:
        """Incrementa y persiste el contador TOTAL (todas las vias). Monotonico."""
        path = getattr(self, "_total_replies_per_post_path", None) or reply_cap._TOTAL_REPLIES_PER_POST_PATH
        return reply_cap.increment_total_replies_for_post(post_id, path=path)

    def _is_own_post_id(self, post_id: str) -> bool:
        """True si el post es propio (registro durado). Fail-safe: cualquier
        error de lectura => False (tratado como ajeno, cap mas estricto)."""
        try:
            return str(post_id) in self._get_own_post_ids()
        except Exception:
            return False

    def _reconcile_deleted_agent_comments(self, post_id: str) -> None:
        """Prune recorded agent comment IDs that no longer exist on the platform
        (HTTP 404). Deleted comments would otherwise count toward the per-post
        reply cap forever, permanently blocking the thread."""
        try:
            agent_comments = self._dedup.get_agent_comment_ids()
        except Exception as e:
            logger.debug("Phase B: reconcile skip (dedup read failed): %s", e)
            return
        ids = agent_comments.get(post_id, [])
        if not ids:
            return
        deleted: List[str] = []
        for cid in ids:
            try:
                resp = self.api._request("GET", f"/comments/{cid}")
            except Exception as e:
                logger.debug("Phase B: reconcile comment %s error: %s", cid, e)
                continue
            if resp.get("status") == 404:
                deleted.append(cid)
        if deleted:
            for cid in deleted:
                ids.remove(cid)
            try:
                self._dedup.sync_agent_comment_ids(agent_comments)
                self._agent_comment_ids = agent_comments
            except Exception as e:
                logger.warning("Phase B: reconcile prune persist failed: %s", e)
            logger.info(
                "Phase B: pruned %d deleted agent comment(s) on post %s (%s)",
                len(deleted), post_id, ", ".join(cid[:8] for cid in deleted),
            )



    def _safe_publish_comment(self, post_id: str, content: str, parent_comment_id: Optional[str] = None,
                              is_followup: bool = False, skip_anti_dogpile: bool = False,
                              is_own_post: bool = False, require_evidence: bool = False,
                              target_author: Optional[str] = None, target_is_watchlist: bool = False,
                              score: Optional[float] = None) -> Optional[Dict]:
        """Publish a comment with safety checks. Returns result dict or None if blocked.

        is_followup=True marca una respuesta enhebrada dentro de una conversación
        viva (respuesta a una respuesta a NUESTRO comentario). Estos NO cuentan
        para el contador anti-dogpile por post (que existe para frenar el apilado
        de comentarios top-level), ni son bloqueados por su cap: sostener una
        conversación no es un dogpile. Su límite propio es
        AGENT_MAX_FOLLOWUPS_PER_POST, controlado por el caller.

        skip_anti_dogpile=True (posts PROPIOS): el cap anti-dogpile previene
        apilar en posts ajenos. Responder comentarios en posts propios no es
        dogpile; su limite es max_comments_per_post, verificado por el caller.

        Techo TOTAL por post-raiz (backstop anti-dogpile): aplica a TODAS las
        vias sin exencion — el TOTAL de replies del agente en un post (sumando
        top-level + follow-ups + own-post) queda acotado por
        AGENT_MAX_TOTAL_REPLIES_PER_POST_FOREIGN / _OWN. Propiedad del post:
        skip_anti_dogpile o is_own_post implican propio; en follow-ups se
        consulta el own_post_store; desconocido => FOREIGN (fail-safe)."""
        # v5.1: Quality gate — length (50-500) + banned openers (+ sustancia si tier=quality)
        if not self._passes_quality_gate(content, require_evidence=require_evidence):
            text_len = len(content.strip())
            logger.warning("Phase B: quality gate REJECTED (length, banned opener o falta de sustancia). len=%d. Preview: %s",
                           text_len, content[:80])
            return None
        # Prompt leak check
        if self._is_prompt_leak(content):
            logger.error("Phase B: PROMPT LEAK blocked. Preview: %s", content[:100])
            return None
        # Forbidden phrases strip
        content = self._strip_forbidden_phrases(content)
        # Sanitize fabricated references
        content = self._sanitize_references(content)
        # Minimum quality check
        if not self._meets_minimum_quality(content):
            logger.warning("Phase B: reply below quality threshold, skipping. Preview: %s", content[:80])
            return None
        # Hard cap: never exceed max_comments_per_post total (across all cycles)
        # Only enforce for proper UUID post IDs (skip for test/synthetic IDs)
        if len(post_id) > 10:  # UUID-length check
            current_count = self._get_agent_reply_count_in_post(post_id)
            if self.max_comments_per_post is not None and current_count >= self.max_comments_per_post:
                logger.warning(
                    "Phase B: SAFETY NET hard cap triggered for post %s (%d/%d). "
                    "This should have been caught earlier — investigate.",
                    post_id, current_count, self.max_comments_per_post,
                )
                return None
        # Publish
        try:
            # ── Dry-run guard: data/phase_b_dry_run.flag blocks real writes ──
            # When present, the full Phase B pipeline runs (scoring, dedup,
            # shadow logging, claim checker) but the actual Moltbook API calls
            # are replaced with simulated success responses. The flag is NOT
            # auto-deleted (unlike stop.flag) — it is a persistent toggle.
            # The instance attribute _dry_run_flag allows tests to override the
            # file path without a global Path monkeypatch.
            _dry_flag = getattr(self, "_dry_run_flag", None) or Path("data/phase_b_dry_run.flag")
            if _dry_flag.exists():
                logger.warning(
                    "🧪 DRY-RUN ACTIVO (data/phase_b_dry_run.flag): NO se publica "
                    "comentario real. post_id=%s content_preview=%r",
                    post_id, content[:150],
                )
                return {"success": True, "id": "dry-run-simulated", "status": 201, "dry_run": True}

            # ── Techo TOTAL por post-raiz (backstop, todas las vias) ──
            # Acota el TOTAL de replies del agente en un post sumando
            # top-level + follow-ups + own-post. Sin exenciones: ni
            # is_followup ni skip_anti_dogpile lo bypassan. La propiedad
            # del post decide el ceiling (foreign=6, own=20).
            if len(post_id) > 10:
                _is_own = bool(skip_anti_dogpile or is_own_post)
                if not _is_own and is_followup:
                    _is_own = self._is_own_post_id(post_id)
                total = self._get_total_replies_for_post(post_id)
                ceiling = reply_cap.get_total_cap(is_own=_is_own)
                if total >= ceiling:
                    logger.info(
                        "total-cap: skip post %s (%d/%d, %s)",
                        post_id, total, ceiling, "own" if _is_own else "foreign",
                    )
                    return None

            # ── Anti-dogpile: monotonic per-post cap (FEED + own-post) ──
            # Hard guardrail (env AGENT_MAX_REPLIES_PER_POST, default 3),
            # independent of feed payload. Only for UUID post IDs.
            # Follow-ups enhebrados están exentos: conversar no es apilar.
            # skip_anti_dogpile (posts propios): responder la comunidad en un
            # post propio no es dogpile; su limite es max_comments_per_post.
            if len(post_id) > 10 and not is_followup and not skip_anti_dogpile:
                current_count = self._get_replies_per_post(post_id)
                if self.max_replies_per_post is not None and current_count >= self.max_replies_per_post:
                    logger.info(
                        "anti-dogpile: skip post %s (%d/%d)",
                        post_id, current_count, self.max_replies_per_post,
                    )
                    return None

            # ── Mark historical examples as used before publishing ──
            mark_examples_used(content)

            result = self.api.create_comment(
                post_id=post_id,
                content=content,
                parent_comment_id=parent_comment_id,
            )

            # ── Spam / rate-limit detection ──
            if isinstance(result, dict):
                status = result.get("status") or result.get("status_code", 0)
                error_text = str(result.get("error", "") or "")
                raw_data = str(result.get("data", "") or "").lower()
                is_spam = (
                    status == 429
                    or "spam" in error_text.lower()
                    or "spam" in raw_data
                    or "rate limit" in error_text.lower()
                    or "rate limit" in raw_data
                )
                if is_spam:
                    logger.warning("Phase B: Moltbook rechazó comentario (posible spam flag). status=%s error=%s. Deteniendo publicaciones en este ciclo.",
                                   status, error_text[:100])
                    return None

                # ── Karma ROI Tracker: registrar comentario publicado (exitoso 2xx) ──
                # Se inserta después del spam check y antes de los contadores anti-dogpile.
                # Solo registra éxitos reales (2xx), no fallos ni spam.
                try:
                    from services.karma_roi_tracker import record_phase_b_comment
                    from services.model_cascade import _estimate_cost_usd
                    
                    # Determinar source desde parámetros de _safe_publish_comment
                    if is_followup:
                        _source = "thread_followup"
                    elif is_own_post or skip_anti_dogpile:
                        _source = "own_post_reply"
                    else:
                        _source = "feed_reply"
                    
                    # Extraer comment_id del result
                    _comment_id = result.get("id") if isinstance(result, dict) else None
                    if not _comment_id:
                        _raw_comment = result.get("raw", {}).get("comment", {}) if isinstance(result, dict) else {}
                        if isinstance(_raw_comment, dict):
                            _comment_id = _raw_comment.get("id")
                    
                    # Obtener metadata de costos desde _last_usage del cascade
                    _provider_name = "tier_fallback"  # default, se actualizará en runtime
                    if hasattr(self, "llm") and hasattr(self.llm, "_last_usage"):
                        _usage = self.llm._last_usage.get(_provider_name, {}) or {}
                    else:
                        _usage = {}
                    
                    _input_tokens = int(_usage.get("input_tokens", 0) or 0)
                    _output_tokens = int(_usage.get("output_tokens", 0) or 0)
                    _cost_usd = _estimate_cost_usd(_provider_name, _input_tokens, _output_tokens)
                    _model = _usage.get("model", "deepseek-v4-pro")
                    # Inferir tier desde provider/model
                    _tier = _usage.get("tier") or _usage.get("provider") or _provider_name
                    if not _tier or _tier == "None":
                        # Inferir desde el model
                        _model_lower = _model.lower() if _model else ""
                        if "pro" in _model_lower:
                            _tier = "tier_pro"
                        elif "flash" in _model_lower:
                            _tier = "tier_flash"
                        else:
                            _tier = _provider_name
                    
                    # Determinar target_author y watchlist status
                    # NOTA: Estos campos requieren pasarse desde el caller
                    # Por ahora se dejan como None/0 hasta completar la integración en callers
                    # Usar parámetros pasados desde caller
                    _target_author = target_author
                    _target_is_watchlist = 1 if target_is_watchlist else 0
                    _score = score
                    
                    # Registrar en karma_roi_tracker
                    record_phase_b_comment(
                        comment_id=_comment_id or "",
                        post_id=str(post_id),
                        parent_comment_id=parent_comment_id,
                        source=_source,
                        target_author=_target_author,
                        target_is_watchlist=_target_is_watchlist,
                        score=_score,
                        model=_model,
                        tier=_tier,
                        input_tokens=_input_tokens,
                        output_tokens=_output_tokens,
                        cost_usd=_cost_usd,
                        status="published",
                    )
                    
                    logger.info(
                        "Karma ROI: Comment %s registrado (source=%s, model=%s, tier=%s, cost=$%.6f)",
                        (_comment_id or "unknown")[:8], _source, _model, _tier, _cost_usd,
                    )
                except Exception as e:
                    logger.warning(
                        "Karma ROI: Error registrando comment %s: %s",
                        (result.get("id") if isinstance(result, dict) else "unknown")[:8], e,
                    )


                # ── Anti-dogpile: count published replies (2xx, not spam) ──
                # Follow-ups enhebrados no consumen este contador (tienen el suyo).
                if len(post_id) > 10 and 200 <= status < 300 and not is_followup:
                    new_count = self._increment_replies_per_post(post_id)
                    logger.info(
                        "anti-dogpile: post %s now at %d/%d",
                        post_id, new_count, self.max_replies_per_post,
                    )

                # ── Techo TOTAL: contar SIEMPRE (todas las vias, 2xx) ──
                if len(post_id) > 10 and 200 <= status < 300:
                    new_total = self._increment_total_replies_for_post(post_id)
                    logger.info(
                        "total-cap: post %s now at %d",
                        post_id, new_total,
                    )

                # ── Persistir TEXTO del comentario publicado (guard de
                # repeticion por post: comparar contra TODOS los previos,
                # cross-ciclo/restart). Fail-open. ──
                try:
                    _pub_cid = result.get("id") if isinstance(result, dict) else None
                    if _pub_cid:
                        self._dedup.set_agent_comment_text(
                            str(post_id), str(_pub_cid), content,
                        )
                except Exception:
                    pass

            return result
        except Exception as e:
            logger.error("Phase B: create_comment error for post %s: %s", post_id, e)
            return None

    # ── Adjudicador LLM de fabricación de nombres propios ──────────
    # El regex _reply_has_ungrounded_named_entity pre-filtra candidatos
    # (2% de las replies); casi todos son sistemas REALES bien citados
    # (Spanner, Borg, Dyn 2016, Turing machine...). Esta capa adjudica SOLO
    # lo que el regex dispara: sistema/persona/estándar real conocido citado
    # correctamente (PASA) vs proyecto/producto/benchmark específico presentado
    # como evidencia inverificable que no está en la fuente (BLOQUEA).
    # FAIL-OPEN: ante error o duda del modelo → PASA (no bloquear). Un falso
    # negativo raro es menos malo que censurar contenido legítimo.
    _ADJUDICATION_SYSTEM = (
        "You are an integrity adjudicator for a technical forum. A reply draft "
        "mentions a named entity (system, project, company, benchmark, person, "
        "standard). Decide whether it is:\n"
        "- REAL: a real, established system/person/standard (e.g. Spanner, Borg, "
        "Dyn outage 2016, Turing machine, Llama, PyTorch, Apollo, Percolator, "
        "Electron) cited as an illustration, analogy, or known mechanism. Being "
        "absent from the source text is NOT a sign of fabrication: these are "
        "widely-known facts the author uses to illustrate a point, not claims "
        "about a specific result.\n"
        "- FABRICATION: a specific project/product/benchmark presented AS "
        "EVIDENCE of a concrete measured result (\"Project X at Y demonstrated "
        "...\", \"Y's benchmark showed ...\", \"as measured in Z's evaluation "
        "...\") — a named entity invented to support a numeric/empirical claim "
        "about performance or behavior. These are not recognizable established "
        "systems.\n"
        "Key test: is the entity invoked as a well-known illustration of a "
        "mechanism (REAL), or as the source of a specific claimed measurement "
        "(FABRICATION)?\n"
        "Respond with EXACTLY one word: REAL or FABRICATION. Nothing else."
    )

    # ETAPA 2 (20/08/2026): 8 tokens estrangulaba a los modelos con
    # reasoning/scratchpad (Groq compound-mini y fallbacks de la cascada
    # emiten razonamiento antes del veredicto). Atributo de clase para que
    # los tests puedan parchearlo sin tocar la cascada.
    _ADJUDICATOR_MAX_TOKENS = 256

    def _fabrication_block_enabled(self) -> bool:
        """True si AGENT_ENABLE_FABRICATION_BLOCK=1 (bloquear draft) — default OFF."""
        return os.getenv("AGENT_ENABLE_FABRICATION_BLOCK", "0") == "1"

    @staticmethod
    def _parse_adjudication(raw: Optional[str]) -> Optional[str]:
        """Extrae 'REAL' o 'FABRICATION' de la salida.

        ETAPA 2 (20/08/2026): tolera reasoning/scratchpad ANTES del veredicto
        y toma la ÚLTIMA aparición — los modelos con reasoning emiten el
        veredicto al final, a veces precedido de dudas internas ("...could be
        REAL, but given the measured claim: FABRICATION"). 'REAL' nunca es
        substring de 'FABRICATION', así que rfind es inequívoco."""
        if not raw:
            return None
        text = raw.upper()
        last_fab = text.rfind("FABRICATION")
        last_real = text.rfind("REAL")
        if last_fab == -1 and last_real == -1:
            return None
        return "FABRICATION" if last_fab > last_real else "REAL"

    def _log_adjudicator_verdict(self, route: str, model: str,
                                 verdict: str, reply_text: str) -> None:
        """Registra cada veredicto del gate en el shadow de medición
        (data/adjudicator_verdicts.jsonl). Nunca rompe el flujo."""
        try:
            _path = (getattr(self, "_adjudicator_verdict_log_path", None)
                     or _ADJUDICATOR_VERDICT_LOG_PATH)
            _path.parent.mkdir(parents=True, exist_ok=True)
            with open(str(_path), "a", encoding="utf-8") as _fh:
                _fh.write(json.dumps({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "route": route,  # "groq" | "cascade" | "fail-open"
                    "model": model,
                    "verdict": verdict,
                    "reply_preview": reply_text[:200],
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _adjudicate_via_groq(self, user_prompt: str) -> Optional[str]:
        """Llamada directa a Groq (groq/compound-mini) SOLO para este gate.

        ETAPA 2: NO pasa por la cascada — la generación sigue Cloudflare-first
        (ETAPA 1) y el modelo de generación de Groq es 404. FAIL-OPEN: sin key,
        429/TPM, error HTTP o respuesta vacía → None (el caller cae al fallback)."""
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            return None
        url = (os.getenv("GROQ_ADJUDICATOR_URL", "").strip()
               or os.getenv("GROQ_API_URL", "").strip()
               or "https://api.groq.com/openai/v1/chat/completions")
        model = os.getenv("GROQ_ADJUDICATOR_MODEL", "groq/compound-mini").strip()
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": self._ADJUDICATION_SYSTEM},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": self._ADJUDICATOR_MAX_TOKENS,
                    "temperature": 0.0,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                return None
            return (choices[0].get("message") or {}).get("content")
        except Exception:
            return None

    async def _adjudicate_named_entity_fabrication(self, reply_text: str,
                                                   source_text: str,
                                                   entities) -> bool:
        """Returns True if the named entity is adjudicated as FABRICATION.

        ETAPA 2 (20/08/2026): ruteo dedicado a Groq groq/compound-mini (no a
        classify/Cloudflare). FAIL-OPEN: 429/error/unparseable → False (PASA,
        no bloquear). Fallback de disponibilidad: cascada classify → flash,
        con max_tokens=256 (ya no 8) para no estrangular reasoning models."""
        if not self.llm:
            return False
        if not entities:
            return False
        user_prompt = (
            f"REPLY DRAFT:\n{reply_text[:1500]}\n\n"
            f"SOURCE:\n{source_text[:1200]}\n\n"
            f"NAMED ENTITIES FOUND:\n{', '.join(sorted(str(e) for e in entities))}\n\n"
            "Verdict (one word):"
        )
        # 1) Groq compound-mini (dedicado, SOLO para este gate)
        raw = self._adjudicate_via_groq(user_prompt)
        if raw:
            verdict = self._parse_adjudication(raw)
            if verdict is not None:
                self._log_adjudicator_verdict(
                    "groq",
                    os.getenv("GROQ_ADJUDICATOR_MODEL", "groq/compound-mini"),
                    verdict, reply_text,
                )
                return verdict == "FABRICATION"
        # 2) Fallback: cascada (classify → flash) con mt alto
        for tier in ("classify", "flash"):
            try:
                raw = await self.llm.generate(
                    tier=tier,
                    prompt=user_prompt,
                    system_prompt=self._ADJUDICATION_SYSTEM,
                    max_tokens=self._ADJUDICATOR_MAX_TOKENS,
                    temperature=0.0,
                )
                verdict = self._parse_adjudication(raw)
                if verdict is not None:
                    self._log_adjudicator_verdict("cascade", tier, verdict, reply_text)
                    return verdict == "FABRICATION"
            except Exception:
                continue
        self._log_adjudicator_verdict("fail-open", "-", "fail-open", reply_text)
        return False

    async def _score_reply_draft(self, reply_text: str, source_text: str, log_context: Optional[Dict[str, Any]] = None,
                           block_ungrounded: bool = False) -> tuple[int, List[str]]:
        # v5.1: Permissive scoring mode — base 50, all penalties zeroed for testing
        score = 50
        reasons: List[str] = []

        # ── Shadow quality guards ──
        # Deteccion SIEMPRE (barata); el log JSONL solo con log_context.
        # Si ANY guardrail dispara, se registra en data/shadow_quality_checks.jsonl
        # para calibrar; en modo block_ungrounded (tier=quality) los checks
        # ungrounded_named_entity / ungrounded_numeric_specificity BLOQUEAN.
        # Wrapped en try/except — un fallo aqui nunca debe afectar la publicacion.
        shadow_hits: List[str] = []
        try:
            if self._reply_has_guardrail_template(reply_text):
                shadow_hits.append("guardrail_template")
            if self._reply_has_ungrounded_numeric_specificity(reply_text, source_text):
                shadow_hits.append("ungrounded_numeric_specificity")
            if not self._reply_mentions_source_terms(reply_text, source_text):
                shadow_hits.append("weak_source_anchor")
            if self._reply_has_ungrounded_named_entity(reply_text, source_text):
                shadow_hits.append("ungrounded_named_entity")
                # ── Adjudicador LLM de fabricación de nombres propios ──
                # El regex pre-filtra (2%); la mayoría son sistemas REALES bien
                # citados (Spanner, Borg, Dyn 2016). El adjudicador decide REAL
                # vs FABRICATION solo sobre lo que el regex disparó.
                #   flag ON  → FABRICATION falla el draft (no publica)
                #   flag OFF → shadow: se registra el veredicto para medir
                # FAIL-OPEN: error/duda del modelo → PASA (no bloquear).
                try:
                    _entities = _extract_named_entities(reply_text)
                    _is_fab = await self._adjudicate_named_entity_fabrication(
                        reply_text, source_text, _entities,
                    )
                    if _is_fab:
                        shadow_hits.append("fabrication_adjudicated")
                        if self._fabrication_block_enabled():
                            score = 0
                            reasons.append("fabrication_named_entity")
                except Exception:
                    pass  # fail-open: nunca bloquear por un fallo del adjudicador
            if self._reply_has_secondhand_causal_attribution(reply_text):
                shadow_hits.append("secondhand_causal_attribution")

            # ── Blocking mode (tier=quality): entidades y numeros sin ancla
            # en la fuente NO se publican en replies de alta exposicion. Los
            # checks ya calibraron en shadow log (534 registros desde 14/7). ──
            if block_ungrounded:
                for _check in ("ungrounded_named_entity", "ungrounded_numeric_specificity"):
                    if _check in shadow_hits:
                        score = 0
                        reasons.append(_check)
        except Exception:
            pass

        if log_context is not None and shadow_hits:
            try:
                # No polucionar el shadow log con entradas de dry-run/test
                # (post-1, p-test, o IDs que parecen simulados) — las 1584
                # entradas de prueba enmascaraban las 76 reales.
                _pid = str(log_context.get("post_id") or "")
                if _pid and not _pid.startswith("p-test") and not _pid.startswith("post-1") \
                        and "test" not in _pid.lower() and not _pid.endswith("-simulated"):
                    record = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "checks": shadow_hits,
                        "reply_preview": reply_text[:300],
                        "source_preview": source_text[:300],
                    }
                    if log_context.get("post_id"):
                        record["post_id"] = str(log_context["post_id"])
                    if log_context.get("comment_id"):
                        record["comment_id"] = str(log_context["comment_id"])
                    _sh = getattr(self, "_shadow_quality_log_path", None) or Path("data") / "shadow_quality_checks.jsonl"
                    _sh.parent.mkdir(parents=True, exist_ok=True)
                    with open(str(_sh), "a", encoding="utf-8") as _fh:
                        _fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception:
                pass  # never fail the real flow

        # ── Penalties (v5.2): reactivadas tras calibración con shadow log.
        #    ungrounded_numeric_specificity: números sin respaldo = deshonesto
        #    (26/76 shadow hits reales). guardrail_template: plantillas trilladas
        #    (2/76). weak_source_anchor se MANTIENE en shadow: el detector actual
        #    tiene ~63% de falsas alarmas (el reply aporta terminología equivalente
        #    pero distinta a la fuente, p.ej. "ambient authority" vs "permission
        #    gap"); reactivarlo bloquearía ~70% de respuestas válidas.
        if self._reply_has_ungrounded_numeric_specificity(reply_text, source_text):
            score -= 30
            reasons.append("ungrounded_numeric_specificity")

        if self._reply_has_guardrail_template(reply_text):
            score -= 10
            reasons.append("templated_phrase")

        fingerprint = self._reply_theme_fingerprint(reply_text, source_text)
        if fingerprint and fingerprint in self._replied_topic_fingerprints:
            score -= 10
            reasons.append("repeated_theme")

        return score, reasons

    def _allow_feed_repeat_reply(self, post: Dict[str, Any], decision: RelevanceDecision) -> RelevanceDecision:
        post_id = str(post.get("id") or post.get("post_id") or "")
        if not post_id:
            return decision

        post_body = " ".join([
            str(post.get("title") or "").strip(),
            str(post.get("content") or post.get("body") or "").strip(),
        ]).strip()
        comments = post.get("comments") or []
        prior_ts = self._commented_post_ids.get(post_id)
        if not prior_ts:
            return decision

        # ── Check for new comments directly addressing the agent ──
        has_direct_addressing = False
        if comments:
            for c in comments:
                if not isinstance(c, dict):
                    continue
                c_text = (c.get("content") or c.get("text") or "").lower()
                if self._has_explicit_addressing(c_text):
                    has_direct_addressing = True
                    break

        # ── PERMANENT dedup: always reject if already commented, unless directly addressed ──
        if not has_direct_addressing:
            logger.info("Phase B: Candidato %s rechazado por dedup permanente (ya comentado).", post_id)
            return RelevanceDecision(False, 0, "reply_skipped_permanent_dedup")

        logger.info("Phase B: Candidato %s — ya comentado pero direct-addressed, permitiendo re-reply.", post_id)
        return decision

    # ── Entrypoint ────────────────────────────────────────────────

    @phase_error_boundary(logger, "phase_b", fallback_return={"success": False, "replies_published": 0, "feed_replies": [], "own_post_replies": []})
    async def execute(self) -> Dict[str, Any]:
        # ─── Quiet Hours: Phase B follows configured hours ───────────────
        try:
            tz = ZoneInfo(behavior_cfg.get("timezone", "America/Guayaquil"))
        except Exception as e:
            logger.warning(
                "Timezone %r no resoluble (%s). Fallback a UTC-5 fijo.",
                behavior_cfg.get("timezone"), e,
            )
            tz = timezone(timedelta(hours=-5))
        current_hour = datetime.now(tz).hour
        quiet = behavior_cfg.get("quiet_hours", [])
        comment_hours = behavior_cfg.get("comment_hours", [])
        in_quiet_hours = (current_hour in quiet) or (bool(comment_hours) and current_hour not in comment_hours)

        if in_quiet_hours:
            logger.info("Phase B: Quiet Hours (hora=%s, quiet=%s, comment_hours=%s) - solo operaciones críticas",
                        current_hour, quiet, comment_hours)
            # Durante Quiet Hours:
            # - NO iniciar nuevas conversaciones en feed
            # - SOLO responder comentarios en posts propios
            # - SOLO responder watchlist de alta prioridad (si hay actividad)
        self.quiet_hours_mode = in_quiet_hours
        feed_results: List[Dict[str, Any]] = []
        own_results: List[Dict[str, Any]] = []

        # ── Baseline del ciclo: queue_prefiltered acumula entre ciclos,
        # el summary reporta el DELTA (no 135 mil comentarios falsos) ──
        self._cycle_prefiltered_baseline = self._stats.get("queue_prefiltered", 0)

        # ── Cache del ROI por canal: se invalida cada ciclo para que el
        # gate de critica use datos frescos (v5.9) ──
        self._roi_channels_cache = None

        # ── Auto-tune semanal de umbrales (guardrails + cadencia) ──
        # Si toca (7d), analiza el retorno real del ledger y ajusta de
        # forma acotada feed_budget_pct / min_value. Fail-safe: nunca rompe
        # el ciclo.
        try:
            from services.roi_auto_tune import apply_tuning
            _tune = apply_tuning()
            if _tune.get("ran") and _tune.get("changes"):
                logger.info(
                    "roi_auto_tune: %d ajuste(s) aplicado(s): %s",
                    len(_tune["changes"]), _tune.get("applied"),
                )
        except Exception as _e:
            logger.debug("roi_auto_tune: skip (%s)", _e)

        # ── Feed budget reservation ─────────────────────────────
        # El % lo decide el auto-tune de ROI (el .env ya no lo fija): los
        # canales que producen retorno real reciben mas presupuesto.
        try:
            from services.roi_auto_tune import get_feed_budget_pct
            _tuned_feed = get_feed_budget_pct(default_pct=15.0)
        except Exception:
            _tuned_feed = int(self.deps.behavior_cfg.get("feed_budget_pct", 40))
        feed_budget_pct = int(_tuned_feed)
        if self.max_comments_per_day is None:
            # sin límite: feed_reserved=0, own_cap=None
            feed_reserved = 0
            own_cap = None
        else:
            feed_reserved = max(0, int(self.max_comments_per_day * feed_budget_pct / 100))
            own_cap = max(0, self.max_comments_per_day - feed_reserved)

        # Temporarily cap own-post budget to prevent starving feed
        _orig_max = self.max_comments_per_day
        own_before = self.get_comments_today()
        self.max_comments_per_day = own_cap

        # Own-post replies: capped to own_cap
        if self.deps.behavior_cfg.get("phase_b_own_post_replies", True):
            own_results = await self._execute_own_post_replies()

        own_consumed = max(0, self.get_comments_today() - own_before)
        own_count = len(own_results)
        if self.max_replies_per_cycle is not None:
            remaining_cycle = max(0, self.max_replies_per_cycle - own_count)
        else:
            remaining_cycle = float('inf')

        # Restore full cap for feed replies
        self.max_comments_per_day = _orig_max
        if self.max_comments_per_day is not None:
            feed_available = max(0, self.max_comments_per_day - self.get_comments_today())
        else:
            feed_available = float('inf')

        logger.info(
            "Phase B: budget — own=%s/%s (consumed=%s), feed=%s/%s (available=%s), feed_pct=%s%%",
            self.get_comments_today(), own_cap, own_consumed,
            self.get_comments_today() - own_before, feed_reserved, feed_available,
            feed_budget_pct,
        )

        # ── Prioridad: continuar > empezar ──────────────────────
        # Sostener una conversación viva (respuesta dentro de un hilo
        # enhebrado) vale más que un comentario frío en un hilo nuevo.
        # Por eso los follow-ups corren ANTES que los feed replies y
        # consumen del MISMO presupuesto de feed.
        followup_results: List[Dict[str, Any]] = []
        if self.deps.behavior_cfg.get("phase_b_feed_replies", True):
            if (self.max_comments_per_day is None or self.get_comments_today() < self.max_comments_per_day) and remaining_cycle > 0:
                followup_results = await self._execute_thread_followups(
                    remaining_cycle_slots=remaining_cycle,
                )

        followup_count = len(followup_results)
        remaining_cycle = max(0, remaining_cycle - followup_count)

        # Feed replies with reserved budget (lo que quede tras follow-ups)
        # ── Quiet Hours: skip feed replies, only own-post and watchlist ──
        if self.deps.behavior_cfg.get("phase_b_feed_replies", True):
            if self.quiet_hours_mode:
                logger.info("Phase B: Quiet Hours - skipping feed replies (only own-post + watchlist)")
                feed_results = []
            elif (self.max_comments_per_day is None or self.get_comments_today() < self.max_comments_per_day) and remaining_cycle > 0:
                feed_results = await self._execute_feed_replies(remaining_cycle_slots=remaining_cycle)
            else:
                logger.info(
                    "Phase B: skip feed replies — budget consumed "
                    "(daily=%s/%s, remaining_cycle=%s).",
                    self.get_comments_today(), self.max_comments_per_day, remaining_cycle,
                )

            feed_count = len(feed_results)
            total = own_count + followup_count + feed_count
            self._stats["upvotes"] = self._upvotes_this_cycle
            self._stats["follows"] = self._follows_this_cycle
            semantic_count = self._stats.get("semantic_candidates", 0)
            inbound_wl = self.get_watchlist_inbound_today()
            # ── Visibilidad del outbox: un atasco de fallos (padres borrados,
            # 4xx) se ve al instante, no 3 dias despues. ──
            try:
                outbox_failed = count_outbox_by_status("failed")
            except Exception:
                outbox_failed = 0
            # ── Retorno por comentario: refresh de upvotes del ledger ──
            try:
                from services.comment_votes import refresh_all_comment_votes, votes_summary
                refresh_all_comment_votes(self.api, self._agent_comment_ids)
                _votes = votes_summary()
            except Exception as e:
                logger.debug("Phase B: comment_votes refresh failed: %s", e)
                _votes = {"total": 0, "with_votes": 0, "total_upvotes": 0, "by_score": {}}
            logger.info(
                "Phase B: cycle summary — own-post replies=%s, thread follow-ups=%s, "
                "feed replies=%s, upvotes=%s, follows=%s, semantic_candidates=%s, "
                "claim-check failures=%s, total=%s, watchlist_inbound_today=%s, "
                "outbox_failed=%s, queue_prefiltered=%s, abstained=%s, "
                "comment votes: %s upvotes (%s revisados de %s registrados, por-score=%s)",
                own_count, followup_count, feed_count, self._upvotes_this_cycle,
                self._follows_this_cycle, semantic_count, self._stats.get("claim_check_failed", 0), total,
                inbound_wl, outbox_failed,
                max(0, self._stats.get("queue_prefiltered", 0) - getattr(self, "_cycle_prefiltered_baseline", 0)),
                self._stats.get("abstained", 0),
                _votes.get("total_upvotes", 0), _votes.get("with_votes", 0), _votes.get("total", 0),
                _votes.get("by_score", {}),
            )

            return {
                "success": total > 0,
                "replies_published": total,
                "debate_continuations": 0,
                "thread_followups": followup_count,
                "claim_check_failures": self._stats.get("claim_check_failed", 0),
                "upvotes": self._upvotes_this_cycle,
                "follows": self._follows_this_cycle,
                "semantic_candidates": semantic_count,
                "outbox_failed": outbox_failed,
                "queue_prefiltered": self._stats.get("queue_prefiltered", 0),
                "feed_replies": feed_results,
                "thread_followup_replies": followup_results,
                "own_post_replies": own_results,
            }

    # ── Anti-duplicate guard ────────────────────────────────────

    async def _check_and_prevent_duplicate(
        self, post_id: str, reply_text: str, attempt: int = 1
    ) -> Optional[str]:
        """Check if reply is near-duplicate of any prior agent comment in this thread.
        Compares against all agent comments in the thread (from dedup store), not just the last one.
        If duplicate, tries one regeneration; if still duplicate, returns None."""
        if not reply_text or not reply_text.strip():
            return None

        # ── Gather all prior agent comments in this thread ──
        all_prior: List[str] = []
        # From runtime cache
        last = self._last_comment_per_thread.get(post_id)
        if last:
            all_prior.append(last)
        # From dedup store (all comment content we've published in this thread)
        agent_comments = self._agent_comment_ids.get(post_id, [])
        for cid in agent_comments:
            cid_str = str(cid)
            prior_text = self._dedup.get_agent_comment_text(post_id, cid_str) if hasattr(self._dedup, 'get_agent_comment_text') else None
            if prior_text and prior_text not in all_prior:
                all_prior.append(prior_text)

        # ── Check similarity against all prior comments ──
        for prior in all_prior:
            if is_same_thread_duplicate_reply(reply_text, prior):
                logger.info(
                    "Phase B: same-thread duplicate vs prior in thread %s (attempt %s)",
                    post_id, attempt,
                )
                if attempt >= 2:
                    send_event("phase_b_duplicate_skip", {
                        "post_id": post_id,
                        "reason": "semantic_duplicate_all_prior",
                    })
                    return None

                # One re-generation with stricter instruction
                stricter = (
                    "IMPORTANT: Your reply is too similar to a previous comment you made in this thread. "
                    "Rewrite from scratch: contribute something completely new, do not repeat ideas already expressed. "
                    "Use a DIFFERENT example, DIFFERENT metric, or DIFFERENT architectural angle."
                )
                try:
                    new_reply = await self.llm.generate(
                        tier="flash",
                        prompt=f"{stricter}\n\nPrevious reply:\n{reply_text}",
                        system_prompt=(
                            "You are a senior systems engineer. Do not repeat yourself. "
                            "Be concise and add new value. "
                            "Always respond in English. This is an English-speaking platform."
                        ),
                        max_tokens=120,
                        temperature=0.8,
                    )
                    new_reply = (new_reply or "").strip()
                    if not new_reply:
                        return None
                    # Re-check against all prior
                    still_dup = any(
                        is_same_thread_duplicate_reply(new_reply, p)
                        for p in all_prior
                    )
                    if still_dup:
                        logger.info("Phase B: re-generated reply still same-thread duplicate in thread %s", post_id)
                        send_event("phase_b_duplicate_skip", {
                            "post_id": post_id,
                            "reason": "semantic_duplicate_after_regeneration",
                        })
                        return None
                    self._last_comment_per_thread[post_id] = new_reply
                    return _safe_truncate(new_reply, max_chars=500)
                except Exception as e:
                    logger.warning("Phase B: error re-generating to avoid duplicate: %s", e)
                    return None

        # ── Also check bigram overlap (fast path) ──
        for prior in all_prior:
            if is_near_duplicate_reply(reply_text, prior):
                logger.info("Phase B: near-duplicate (bigram) in thread %s, skipping.", post_id)
                send_event("phase_b_duplicate_skip", {
                    "post_id": post_id,
                    "reason": "near_duplicate_bigram",
                })
                return None

        self._last_comment_per_thread[post_id] = reply_text
        return reply_text

    # ── Feed replies (antes phase_b_replies.py) ───────────────────

    async def _execute_thread_followups(self, remaining_cycle_slots: Optional[int] = None) -> List[Dict[str, Any]]:
        """Sostener conversaciones vivas: responder a las respuestas que otros
        dieron a NUESTROS comentarios en posts ajenos (feed).

        El agente comenta en el feed y nunca vuelve; si alguien responde a su
        comentario, la conversación muere. Este camino cierra ese hueco.

        Distinción clave:
          - apilar comentarios TOP-LEVEL en un post = DOGPILE (malo) → anti-dogpile
          - sostener un hilo enhebrado = CONVERSACIÓN (buena) → esta función

        Se revisitan solo los posts comentados en las últimas 48 h (los más
        viejos ya están muertos). Cada respuesta se publica ENHEBRADA
        (parent_comment_id = comentario que nos respondió), con dedup durable,
        triage de calidad + bonus de interlocutor, límite de profundidad
        (MAX_CONVERSATION_DEPTH) y cap propio (AGENT_MAX_FOLLOWUPS_PER_POST).
        Consume del mismo presupuesto de feed que _execute_feed_replies."""
        with Span("thread_followups") as span:
            if not self.llm:
                logger.warning("Phase B: model_cascade no disponible; se omiten thread follow-ups.")
                span.set("posted", 0)
                return []

            results: List[Dict[str, Any]] = []
            posts_revisited = 0

            # ── Instrumentación de diagnóstico (solo logs, no cambia lógica) ──
            diag_posts_fetched = 0
            diag_comments_inspected = 0
            diag_replies_matched = 0
            diag_discarded_dedup = 0
            diag_discarded_depth = 0
            diag_discarded_triage = 0
            diag_discarded_prefilter = 0
            diag_broke_daily = False
            diag_broke_cycle = False

            effective_cycle_limit = (
                remaining_cycle_slots if remaining_cycle_slots is not None
                else self.max_replies_per_cycle
            )
            cycle_count = 0

            # ── Solo posts ajenos comentados en las últimas 48 h ──
            # Hilos CERRADOS se excluyen SIEMPRE: sin esto, la sintesis de
            # cierre genera respuestas nuevas, refresca la ventana 48h y el
            # hilo se vuelve a cerrar en cada ciclo (loop de sintesis).
            cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
            recent_post_ids: List[str] = []
            for pid, ts in self._commented_post_ids.items():
                if not isinstance(pid, str):
                    continue
                try:
                    ts_dt = datetime.fromisoformat(ts) if isinstance(ts, str) else None
                    if ts_dt is not None and ts_dt.tzinfo is None:
                        ts_dt = ts_dt.replace(tzinfo=timezone.utc)  # FIX 2026-09-13 naive->aware
                except (ValueError, TypeError):
                    ts_dt = None
                if ts_dt is not None and ts_dt >= cutoff:
                    if is_thread_closed(pid):
                        continue  # hilo cerrado: nunca vuelve a follow-ups
                    recent_post_ids.append(pid)

            logger.info(
                "Phase B: follow-ups — %s post(s) en ventana 48h (de %s comentados), "
                "cycle_limit=%s, max_comments_per_day=%s.",
                len(recent_post_ids), len(self._commented_post_ids),
                effective_cycle_limit, self.max_comments_per_day,
            )

            if not recent_post_ids:
                logger.info("Phase B: sin posts revisitables para follow-ups (ninguno en 48 h).")
                span.set("posted", 0)
                return []

            from services import interlocutors

            for post_id in recent_post_ids:
                if self.max_comments_per_day is not None and self.get_comments_today() >= self.max_comments_per_day:
                    diag_broke_daily = True
                    logger.info(
                        "Phase B: skip follow-ups — daily limit (%s/%s).",
                        self.get_comments_today(), self.max_comments_per_day,
                    )
                    break
                if effective_cycle_limit is not None and cycle_count >= effective_cycle_limit:
                    diag_broke_cycle = True
                    logger.info(
                        "Phase B: skip follow-ups — cycle limit (%s/%s).",
                        cycle_count, effective_cycle_limit,
                    )
                    break

                our_comment_ids = self._agent_comment_ids.get(post_id, [])
                if not our_comment_ids:
                    continue

                # ── Cap propio de follow-ups por post (independiente del anti-dogpile) ──
                followups_done = self._get_followups_count(post_id)
                if self.max_followups_per_post is not None and followups_done >= self.max_followups_per_post:
                    logger.info(
                        "Phase B: skip follow-ups en post %s — cap propio (%d/%d).",
                        post_id, followups_done, self.max_followups_per_post,
                    )
                    continue

                try:
                    comments = self.api.fetch_post_comments(post_id)
                except Exception as e:
                    logger.warning("Phase B: error fetching comments (follow-up) post %s: %s", post_id, e)
                    continue
                if not comments:
                    continue
                diag_posts_fetched += 1
                diag_comments_inspected += len(comments)

                our_id_set = {str(cid) for cid in our_comment_ids}
                # Respuestas A NUESTROS comentarios (parent_id apunta a uno nuestro),
                # excluyendo las nuestras propias.
                replies_to_us = [
                    c for c in comments
                    if isinstance(c, dict)
                    and PhaseB._extract_parent_id(c) in our_id_set
                    and not self._is_own_author(self._get_author_name(c))
                ]
                diag_replies_matched += len(replies_to_us)
                if not replies_to_us:
                    continue

                post_touched = False
                for reply_comment in replies_to_us:
                    if self.max_comments_per_day is not None and self.get_comments_today() >= self.max_comments_per_day:
                        diag_broke_daily = True
                        break
                    if effective_cycle_limit is not None and cycle_count >= effective_cycle_limit:
                        diag_broke_cycle = True
                        break
                    if self.max_followups_per_post is not None and followups_done >= self.max_followups_per_post:
                        logger.info(
                            "Phase B: post %s alcanzó cap de follow-ups (%d/%d).",
                            post_id, followups_done, self.max_followups_per_post,
                        )
                        break

                    reply_id = reply_comment.get("id") or reply_comment.get("comment_id")
                    if not reply_id:
                        continue

                    # ── Pre-filtro: sin contenido / borrado / unrepliable se
                    # descartan ANTES de generar (ahorra LLM) ──
                    queuable, qreason = PhaseB._comment_queuable(reply_comment)
                    if not queuable:
                        diag_discarded_prefilter += 1
                        logger.info(
                            "Phase B: skip follow-up a comentario %s (pre-filter: %s).",
                            reply_id, qreason,
                        )
                        continue
                    reply_text = (reply_comment.get("content") or reply_comment.get("text") or "").strip()
                    if reply_cap.is_unrepliable_comment(f"{post_id}:{reply_id}"):
                        diag_discarded_prefilter += 1
                        logger.info(
                            "Phase B: skip follow-up a comentario %s en post %s (unrepliable).",
                            reply_id, post_id,
                        )
                        continue
                    reply_author = self._get_author_name(reply_comment) or "usuario"

                    # ── Dedup durable: nunca responder dos veces el mismo comentario ──
                    if reply_cap.has_replied_to_comment(f"{post_id}:{reply_id}"):
                        diag_discarded_dedup += 1
                        logger.info(
                            "Phase B: skip follow-up a comentario %s en post %s (durable dedup).",
                            reply_id, post_id,
                        )
                        continue

                    # ── Guard de profundidad: limite de interacciones ──
                    # Maximo 4 intercambios del agente (fijo, sin extension
                    # por watchlist) — defender la teoria y cerrar el tema.
                    # El hilo se corta antes si repite. El motivo queda en el
                    # log.
                    # NUNCA cerrar un hilo con pregunta directa a COMET sin
                    # responderla (mention @comet o pregunta en post propio).
                    _c_text = (reply_comment.get("content") or reply_comment.get("text") or "")
                    _is_direct_q = PhaseB._is_direct_question(_c_text)
                    if _is_direct_q:
                        logger.info(
                            "Phase B: thread close: answered_direct_q (post %s, comment %s) — pregunta directa, se responde en vez de cerrar",
                            post_id, reply_id,
                        )
                    else:
                        depth = self._compute_thread_depth(reply_comment, comments)
                        _author_key = (reply_author or "").strip().lower()
                        _limit, _close_reason = self._thread_depth_limit(
                            reply_comment, comments, _author_key,
                            self._is_watchlist_author(_author_key),
                        )
                        if depth >= _limit:
                            await self._close_thread_decision(
                                post_id, reply_comment, comments, reply_author,
                                _close_reason or "tope",
                            )
                            continue

                    # ── Triage de calidad + bonus de interlocutor ──
                    skip_triage, triage_reason = _triage_comment_value(
                        reply_text,
                        tech_keywords=self._TECH_KEYWORDS,
                        author=reply_comment.get("author"),
                    )
                    if skip_triage:
                        diag_discarded_triage += 1
                        logger.info(
                            "Phase B: skip follow-up a comentario %s (triage: %s).",
                            reply_id, triage_reason,
                        )
                        continue

                    # ── Gate temático en follow-ups (política vigente) ──
                    # El turno del interlocutor debe seguir refiriéndose al
                    # tema del post: si deriva a un tema ajeno, el hilo se
                    # cierra (no se entra en discusiones sin relevancia).
                    # Fail-open: sin texto del post disponible no se filtra.
                    if not getattr(self, "_followup_post_text_cache", None):
                        self._followup_post_text_cache = {}
                    if post_id not in self._followup_post_text_cache:
                        _pt = ""
                        try:
                            _pp = self.api.get_post(post_id)
                            if isinstance(_pp, dict):
                                _pt = " ".join([
                                    str(_pp.get("title") or "").strip(),
                                    str(_pp.get("content") or _pp.get("body") or _pp.get("text") or "").strip(),
                                ]).strip()
                        except Exception:
                            pass
                        self._followup_post_text_cache[post_id] = _pt
                    _fup_post_text = self._followup_post_text_cache.get(post_id, "")
                    if _fup_post_text and comment_off_topic(reply_text, _fup_post_text):
                        logger.info(
                            "Phase B: thread close: off_topic (post %s, comment %s) — el turno se salió del tema del post, no se responde.",
                            post_id, reply_id,
                        )
                        close_thread(post_id)
                        continue

                    # ── Concesion del interlocutor: una sintesis, luego cerrar ──
                    _followup_conceded = PhaseB._is_concession(reply_text)
                    if _followup_conceded:
                        if post_id in self._concession_answered:
                            close_thread(post_id)
                            logger.info("Phase B: thread close: let_stand (post %s, interlocutor conceded de nuevo)", post_id)
                            continue
                        _followup_synthesis = True
                    else:
                        _followup_synthesis = False

                    # ── Ledger: observación de la respuesta a nuestro comentario ──
                    interlocutors.record_interaction(
                        reply_comment.get("author"), on_our_post=False,
                    )

                    # ── Generar respuesta enhebrada (con historial del hilo) ──
                    # Tier routing: si quien nos respondió está en la watchlist,
                    # la respuesta es contenido de máxima exposición (autor de un
                    # post con cientos de comentarios/upvotes) → tier quality.
                    reply_author_key = (reply_author or "").strip().lower()
                    followup_tier = "quality" if self._is_watchlist_author(reply_author_key) else "flash"
                    thread_history = self._build_thread_history(reply_comment, comments)
                    try:
                        followup_text = await self._generate_own_post_reply(
                            reply_author, reply_text, thread_history,
                            tier=followup_tier, post_id=post_id,
                            concession_synthesis=_followup_synthesis,
                        )
                    except Exception as e:
                        logger.warning("Phase B: error generando follow-up: %s", e)
                        continue

                    followup_text = (followup_text or "").strip()
                    if not followup_text:
                        continue
                    # ABSTAIN: salida legitima — no publicar, no cuenta como fallo.
                    if followup_text.upper().startswith("ABSTAIN"):
                        logger.info("Phase B: follow-up ABSTAIN (comment %s en post %s)", reply_id, post_id)
                        continue
                    followup_text = clean_llm_output(followup_text)

                    if text_has_fabricated_measurement(followup_text):
                        logger.warning(
                            "Phase B: FOLLOW-UP REJECTED — fabricated measurement post_id=%s: %s",
                            post_id, followup_text[:120],
                        )
                        continue

                    followup_text = await self._check_and_prevent_duplicate(post_id, followup_text)
                    if followup_text is None:
                        continue
                    if len(followup_text.strip()) < 40 or is_likely_truncated(followup_text):
                        logger.info(
                            "Phase B: skip follow-up — too short or truncated (len=%d).",
                            len(followup_text.strip()),
                        )
                        continue

                    # Sintesis de concesion sin insight unificador (CLOSE): no
                    # publicar — el ultimo punto queda parado.
                    if _followup_synthesis and followup_text.strip().upper().startswith("CLOSE"):
                        close_thread(post_id)
                        logger.info("Phase B: thread close: let_stand (post %s, sin sintesis genuina)", post_id)
                        continue

                    # ── Publicar ENHEBRADO: parent = comentario que nos respondió ──
                    resp = self._safe_publish_comment(
                        post_id=str(post_id),
                        content=followup_text,
                        parent_comment_id=str(reply_id),
                        is_followup=True,
                        require_evidence=(followup_tier == "quality"),
                    )
                    if resp is None:
                        continue

                    if isinstance(resp, dict):
                        success = bool(resp.get("success"))
                        status = resp.get("status") or resp.get("status_code")
                        followup_comment_id = resp.get("id")
                        raw = resp.get("raw") if isinstance(resp.get("raw"), dict) else {}
                        if not followup_comment_id and isinstance(raw.get("comment"), dict):
                            followup_comment_id = raw["comment"].get("id")
                    else:
                        success = bool(getattr(resp, "success", False))
                        status = getattr(resp, "status", None) or getattr(resp, "status_code", None)
                        followup_comment_id = getattr(resp, "id", None)

                    if not success:
                        # 404 de padre inexistente: determinista — marcar el
                        # comentario unrepliable y no encolar (reintentar seria
                        # quemar LLM en algo que jamas se publicara).
                        if is_parent_not_found_404(resp):
                            reply_cap.mark_unrepliable_comment(f"{post_id}:{reply_id}")
                            logger.warning(
                                "Phase B: follow-up a comentario %s en post %s unrepliable "
                                "(parent 404) — marcado, sin outbox.",
                                reply_id, post_id,
                            )
                            continue
                        logger.warning(
                            "Phase B: follow-up falló post_id=%s parent=%s status=%s.",
                            post_id, reply_id, status,
                        )
                        enqueue_outbox("comment", {
                            "post_id": post_id, "content": followup_text,
                            "parent_comment_id": str(reply_id),
                        })
                        continue

                    # ── Éxito: dedup durable, contador propio, ledger, presupuesto ──
                    reply_cap.mark_replied_to_comment(f"{post_id}:{reply_id}")
                    interlocutors.record_interaction(
                        reply_comment.get("author"), on_our_post=False,
                    )
                    # Sintesis post-concesion publicada: la proxima concesion cierra.
                    if _followup_conceded:
                        self._concession_answered.add(post_id)
                    # ── Ledger de retorno del follow-up ──
                    try:
                        from services.comment_votes import record_published_comment
                        record_published_comment(
                            post_id, str(followup_comment_id or ""),
                            compute_dual_score(followup_text)["research_value_score"],
                            reason=self._comment_entry_reason(reply_author),
                        )
                    except Exception as e:
                        logger.debug("Phase B: comment_votes record failed (followup): %s", e)
                    self.incr_comments_today()
                    followups_done = self._increment_followups_count(post_id)
                    cycle_count += 1
                    post_touched = True

                    try:
                        update_today_metrics(comments_published=1)
                    except Exception as e:
                        logger.warning("SelfEval: error registrando comments_published=1: %s", e)

                    if followup_comment_id:
                        if post_id not in self._agent_comment_ids:
                            self._agent_comment_ids[post_id] = []
                        self._agent_comment_ids[post_id].append(str(followup_comment_id))
                        self._dedup.sync_agent_comment_ids(self._agent_comment_ids)
                        _append_to_reply_history(followup_text)

                    send_event("phase_b_reply_success", {
                        "post_id": post_id,
                        "comment_id": followup_comment_id,
                        "parent_comment_id": str(reply_id),
                        "kind": "thread_followup",
                    })
                    logger.info(
                        "Phase B: thread follow-up publicado post_id=%s parent=%s tier=%s author=%s (%d/%d).",
                        post_id, reply_id, followup_tier, reply_author,
                        followups_done, self.max_followups_per_post,
                    )

                    results.append({
                        "post_id": post_id,
                        "comment_id": followup_comment_id,
                        "parent_comment_id": str(reply_id),
                        "content": followup_text,
                        "success": True,
                        "kind": "thread_followup",
                    })
                    await asyncio.sleep(self.delay_between_comments)

                if post_touched:
                    posts_revisited += 1

            logger.info(
                "Phase B: thread follow-ups=%s (posts revisitados=%s)",
                len(results), posts_revisited,
            )
            logger.info(
                "Phase B: follow-up diagnóstico — ventana48h=%s, fetched=%s, "
                "comentarios_inspected=%s, replies_matched=%s, "
                "descartados(durable_dedup=%s, profundidad=%s, triage=%s, prefilter=%s), "
                "corte(daily=%s, cycle=%s), publicado=%s.",
                len(recent_post_ids), diag_posts_fetched,
                diag_comments_inspected, diag_replies_matched,
                diag_discarded_dedup, diag_discarded_depth, diag_discarded_triage,
                diag_discarded_prefilter,
                diag_broke_daily, diag_broke_cycle, len(results),
            )
            span.set("posted", len(results))
            return results

    async def _execute_feed_replies(self, remaining_cycle_slots: Optional[int] = None) -> List[Dict[str, Any]]:
        with Span("feed_replies") as span:
            if not self.llm:
                logger.warning("Phase B: model_cascade no disponible; se omiten feed replies.")
                span.set("posted", 0)
                return []

            cycle_comment_count = 0
            daily_comment_count = self.get_comments_today()
            if self.max_comments_per_day is not None and daily_comment_count >= self.max_comments_per_day:
                logger.info(
                    "Phase B: límite diario de comentarios alcanzado (%s/%s).",
                    daily_comment_count, self.max_comments_per_day,
                )
                send_event("phase_b_reply_skip", {
                    "reason": "daily_limit",
                    "score": 0,
                })
                span.set("posted", 0)
                return []

            # Track feed-specific counter separately from global daily count
            feed_comment_count = 0

            max_feed = self.deps.behavior_cfg.get("max_feed_replies_per_day", POLICY.max_feed_replies_per_day)
            effective_cycle_limit = remaining_cycle_slots if remaining_cycle_slots is not None else self.max_replies_per_cycle
            remaining_daily = max(0, max_feed - feed_comment_count)

            # ── Watchlist budget reservation ──────────────────────
            watchlist_pct = int(self.deps.behavior_cfg.get("watchlist_budget_pct",
                                int(os.getenv("AGENT_WATCHLIST_BUDGET_PCT", "30"))))
            watchlist_reserved = max(0, int(max_feed * watchlist_pct / 100))
            general_cap = max(0, max_feed - watchlist_reserved)
            self._watchlist_feed_count = 0
            self._general_feed_count = 0
            self._watchlist_reserved = watchlist_reserved
            self._general_cap = general_cap

            logger.info(
                "Phase B: feed replies — comments_today=%s/%s, remaining_feed_daily=%s/%s, "
                "cycle_budget=%s, watchlist_reserved=%s, general_cap=%s",
                daily_comment_count, self.max_comments_per_day, remaining_daily, max_feed,
                effective_cycle_limit, watchlist_reserved, general_cap,
            )

            # Load roadmap for topic alignment
            roadmap = load_roadmap()
            roadmap_topics_lower = set(t.lower() for t in roadmap.all_topics())

            candidate_posts = self._fetch_candidate_posts(limit=20)
            candidate_posts = candidate_posts[:12]  # pool de selección más ajustado para reducir ciclos largos

            search_posts = await self._fetch_semantic_search_posts() if self._semantic_search_enabled else []
            self._stats["semantic_candidates"] = len(search_posts)
            if search_posts:
                seen_ids = {p.get("id") or p.get("post_id") for p in candidate_posts if p.get("id") or p.get("post_id")}
                for sp in search_posts:
                    pid = sp.get("id") or sp.get("post_id") or ""
                    if pid not in seen_ids:
                        candidate_posts.append(sp)
                        seen_ids.add(pid)

            if not candidate_posts:
                logger.info("Phase B: no se encontraron posts candidatos en el feed.")
                span.set("posted", 0)
                return []

            filtered_posts: List[Dict[str, Any]] = [
                p for p in candidate_posts if self._can_comment_in_thread(p)
            ]

            if not filtered_posts:
                logger.info("Phase B: todos los hilos candidatos ya tienen suficientes comentarios del agente.")
                span.set("posted", 0)
                return []

            # Score and rank by roadmap alignment
            scored_posts: List[tuple] = []
            for post in filtered_posts:
                post_body = (post.get("content") or post.get("body") or post.get("text") or post.get("title") or "").strip()
                # ── Promocion comercial: no responder publicidad ──
                if PhaseB._is_promotional_content(post_body):
                    _promo_author = post.get("author")
                    if isinstance(_promo_author, dict):
                        _promo_author = _promo_author.get("name") or ""
                    logger.info("Phase B: skip: promotional content from %s", str(_promo_author or "unknown"))
                    continue
                post_comments = post.get("comments") or []
                post_decision = self._decide_reply_from_post(post_body, comments=post_comments, post=post)
                if not post_decision.should_reply:
                    pid = post.get("id") or post.get("post_id") or "?"
                    logger.info(
                        "Phase B: feed discarded post_id=%s score=%s should_reply=%s reason=%s",
                        pid, post_decision.score, post_decision.should_reply, post_decision.reason,
                    )
                    continue
                # Body length gate: reject spam/short posts
                if len(post_body) < 100:
                    pid = post.get("id") or post.get("post_id") or "?"
                    logger.info(
                        "Phase B: feed discarded post_id=%s reason=body_too_short len=%s",
                        pid, len(post_body),
                    )
                    continue
                # Roadmap alignment boost
                post_text_lower = post_body.lower()
                if any(rt in post_text_lower for rt in roadmap_topics_lower):
                    post_decision = RelevanceDecision(
                        should_reply=True,
                        score=min(post_decision.score + 15, 100),
                        reason=post_decision.reason,
                    )
                # Stricter threshold for feed replies: require score >= min + 1
                # (reduced during cold start when posts_today < COLD_START_POST_THRESHOLD)
                threshold = _get_feed_min_score(self.deps.posts_today)
                if post_decision.score < threshold:
                    pid = post.get("id") or post.get("post_id") or "?"
                    title_snippet = (post.get("title") or post_body)[:80]
                    logger.info(
                        "Phase B: feed candidate post_id=%s score=%s (threshold=%s) title=%s",
                        pid, post_decision.score, threshold, title_snippet,
                    )
                    continue
                scored_posts.append((post_decision.score, post))

            scored_posts.sort(key=lambda x: -x[0])  # highest score first

            if not scored_posts:
                logger.info("Phase B: ningún post del feed superó el umbral de relevancia estratégica.")
                span.set("posted", 0)
                _save_feed_stall_count(_load_feed_stall_count() + 1)
                return []

            _save_feed_stall_count(0)
            logger.info("Phase B: %s posts seleccionados de %s candidatos por relevancia y roadmap.",
                         len(scored_posts), len(filtered_posts))
            for sc, sp in scored_posts:
                sp_id = sp.get("id") or sp.get("post_id") or "?"
                sp_body = (sp.get("content") or sp.get("body") or sp.get("text") or sp.get("title") or "")[:80]
                logger.info("Phase B: selected post_id=%s score=%s body_preview=%s", sp_id, sc, sp_body)

            results: List[Dict[str, Any]] = []

            # ── LLM generation cap: stop after N failed attempts per cycle ──
            _max_llm_attempts = int(os.getenv("MAX_LLM_ATTEMPTS_PER_CYCLE", "3"))
            _llm_attempts = 0

            # ── Feed-specific limits: daily global, feed-daily, and remaining cycle budget ──
            for score, post in scored_posts:
                daily_comment_count = self.get_comments_today()
                if self.max_comments_per_day is not None and daily_comment_count >= self.max_comments_per_day:
                    logger.info(
                        "Phase B: skip feed reply — daily limit reached (%s/%s).",
                        daily_comment_count, self.max_comments_per_day,
                    )
                    send_event("phase_b_reply_skip", {
                        "reason": "daily_limit",
                        "score": 0,
                    })
                    break
                if feed_comment_count >= max_feed:
                    logger.info(
                        "Phase B: skip feed reply — feed daily limit reached (%s/%s).",
                        feed_comment_count, max_feed,
                    )
                    send_event("phase_b_reply_skip", {
                        "reason": "max_feed_replies_per_day",
                        "score": 0,
                    })
                    break

                # ── Watchlist vs general budget gate ─────────────
                post_author = _extract_author_name(post)
                is_watchlist = self._is_watchlist_author(post_author)
                if is_watchlist and self._watchlist_feed_count >= self._watchlist_reserved:
                    logger.info(
                        "Phase B: skip feed reply — watchlist budget consumed (%s/%s) for %s.",
                        self._watchlist_feed_count, self._watchlist_reserved, post_author,
                    )
                    continue
                if not is_watchlist and self._general_feed_count >= self._general_cap:
                    logger.info(
                        "Phase B: skip feed reply — general budget consumed (%s/%s), "
                        "reserving %s for watchlist.",
                        self._general_feed_count, self._general_cap, self._watchlist_reserved,
                    )
                    continue

                effective_cycle_limit = remaining_cycle_slots if remaining_cycle_slots is not None else self.max_replies_per_cycle
                if effective_cycle_limit is not None and cycle_comment_count >= effective_cycle_limit:
                    logger.info(
                        "Phase B: skip feed reply — cycle limit reached (%s/%s).",
                        cycle_comment_count, effective_cycle_limit,
                    )
                    send_event("phase_b_reply_skip", {
                        "reason": "per_cycle_limit",
                        "score": 0,
                    })
                    break

                post_id = post.get("id")
                if not post_id:
                    continue
                post_body = (post.get("content") or post.get("body") or post.get("text") or post.get("title") or "").strip()
                post_comments = post.get("comments") or []

                # ── Thread depth guard (feed) ─────────────────────────
                agent_post_ids = self._agent_comment_ids.get(post_id, [])
                if agent_post_ids:
                    max_depth = max(
                        (self._compute_thread_depth(c, post_comments)
                         for c in post_comments
                         if PhaseB._extract_parent_id(c) in agent_post_ids),
                        default=0,
                    )
                    if max_depth >= MAX_CONVERSATION_DEPTH:
                        logger.info(
                            "Profundidad máxima alcanzada, salteando hilo "
                            "(post_id=%s, profundidad=%s, max=%s)",
                            post_id, max_depth, MAX_CONVERSATION_DEPTH,
                        )
                        continue

                if not self._can_comment_in_thread(post):
                    logger.info("Phase B: post %s at per-post limit (%s), skipping", post_id, self.max_feed_comments_per_post)
                    self._maybe_upvote(post_id, self._classify_topic_value(post_body, comments=post_comments))
                    continue

                # Hard cap cross-cycle check (dedup store) — saves LLM tokens
                if len(str(post_id)) > 10:
                    _feed_cap = self.deps.behavior_cfg.get("max_feed_comments_per_post")
                    _feed_count = self._get_agent_reply_count_in_post(str(post_id))
                    if _feed_cap is not None and _feed_count >= _feed_cap:
                        logger.info("Phase B: skip feed post %s — hard cap (%d/%d).", post_id, _feed_count, _feed_cap)
                        continue

                post_decision = self._decide_reply_from_post(post_body, comments=post_comments, post=post)
                if not post_decision.should_reply:
                    self._maybe_upvote(post_id, self._classify_topic_value(post_body, comments=post_comments))
                    send_event("phase_b_reply_skip", {
                        "post_id": post_id,
                        "reason": post_decision.reason,
                        "score": post_decision.score,
                        "snippet": post_body[:60],
                    })
                    logger.info("Phase B: post %s saltado por relevancia (score=%s, reason=%s)",
                                post_id, post_decision.score, post_decision.reason)
                    continue

                send_event("phase_b_reply_attempt", {
                    "post_id": post_id,
                    "score": post_decision.score,
                    "snippet": post_body[:60],
                })

                # ── Top-level dedup pre-check: skip BEFORE LLM generation ──
                if post_id in self._commented_post_ids:
                    logger.info(
                        "Phase B: skip feed post %s — already top-level commented.",
                        post_id,
                    )
                    continue

                # ── Ledger: observación del feed post ──
                from services import interlocutors
                interlocutors.record_interaction(
                    post.get("author"), on_our_post=False,
                )

                try:
                    bestof = (_quality_bestof_enabled()
                              and post_decision.score >= POLICY.min_comment_relevance_score + 20)
                    # ── Tier routing: watchlist → quality, resto → flash ──
                    feed_author = _extract_author_name(post)
                    is_wl = self._is_watchlist_author(feed_author)
                    reply_tier = "quality" if is_wl else "flash"
                    post["_reply_tier"] = reply_tier

                    # ── Watchlist cap pre-check: skip BEFORE LLM generation ──
                    if is_wl and not self._check_increment_watchlist_cap(feed_author, is_own_post=False):
                        logger.info(
                            "Phase B: skip feed reply — watchlist cap for %s (%s/day).",
                            feed_author, self._watchlist_max_per_author_day,
                        )
                        continue

                    # ── PRE-GENERATION GATE (patch 2026-08-31) ─────────────────────────────
                    skip_gen, motivo = should_skip_generation_pre_gate(post)
                    if skip_gen:
                        logger.info(
                            'Phase B: PRE-GENERATION GATE skip post_id=%s motivo=%s',
                            post.get('id'), motivo
                        )
                        continue  # Saltar este post, no gastar tokens
                    # ───────────────────────────────────────────────────────────────────────―


                    reply_text, claim = await self._generate_reply_for_post(post, bestof=bestof, tier=reply_tier)
                except Exception as e:
                    logger.warning(f"Phase B: error generando respuesta: {e}")
                    _llm_attempts += 1
                    if _llm_attempts >= _max_llm_attempts:
                        logger.info("Phase B: LLM attempt cap reached (%s/%s), stopping cycle.",
                                    _llm_attempts, _max_llm_attempts)
                        break
                    continue

                reply_text = (reply_text or "").strip()
                # ABSTAIN: salida legitima — no publicar, no cuenta como fallo
                # ni consume el limite de intentos LLM del ciclo.
                if reply_text.upper().startswith("ABSTAIN"):
                    logger.info("Phase B: skip feed reply — ABSTAIN (post %s)", post_id)
                    continue
                if not reply_text:
                    logger.warning("Phase B: respuesta vacía generada.")
                    _llm_attempts += 1
                    if _llm_attempts >= _max_llm_attempts:
                        logger.info("Phase B: LLM attempt cap reached (%s/%s), stopping cycle.",
                                    _llm_attempts, _max_llm_attempts)
                        break
                    continue

                # ── Anti-fabrication guard: reject first-person measurement claims ──
                if text_has_fabricated_measurement(reply_text):
                    logger.warning(
                        "Phase B: REPLY REJECTED — fabricated measurement in post_id=%s: %s",
                        post_id, reply_text[:120],
                    )
                    send_event("phase_b_reply_skip", {
                        "post_id": post_id,
                        "reason": "fabricated_measurement",
                        "score": post_decision.score,
                    })
                    _llm_attempts += 1
                    if _llm_attempts >= _max_llm_attempts:
                        logger.info("Phase B: LLM attempt cap reached (%s/%s), stopping cycle.",
                                    _llm_attempts, _max_llm_attempts)
                        break
                    continue

                # ── Cross-cycle semantic duplicate check ──
                try:
                    if _is_semantic_dupe_against_history(reply_text):
                        logger.info(
                            "Phase B: REPLY REJECTED — semantic duplicate against cross-cycle history "
                            "in post_id=%s",
                            post_id,
                        )
                        send_event("phase_b_reply_skip", {
                            "post_id": post_id,
                            "reason": "cross_cycle_duplicate",
                            "score": post_decision.score,
                        })
                        _llm_attempts += 1
                        if _llm_attempts >= _max_llm_attempts:
                            logger.info("Phase B: LLM attempt cap reached (%s/%s), stopping cycle.",
                                        _llm_attempts, _max_llm_attempts)
                            break
                        continue
                except Exception:
                    pass
                    _llm_attempts += 1
                    if _llm_attempts >= _max_llm_attempts:
                        logger.info("Phase B: LLM attempt cap reached (%s/%s), stopping cycle.",
                                    _llm_attempts, _max_llm_attempts)
                        break
                    continue

                reply_text = clean_llm_output(reply_text)

                reply_text = await self._check_and_prevent_duplicate(post_id, reply_text)
                if reply_text is None:
                    _llm_attempts += 1
                    if _llm_attempts >= _max_llm_attempts:
                        logger.info("Phase B: LLM attempt cap reached (%s/%s), stopping cycle.",
                                    _llm_attempts, _max_llm_attempts)
                        break
                    continue

                if len(reply_text.strip()) < 40 or is_likely_truncated(reply_text):
                    logger.info("Phase B: skip feed reply — too short or truncated (len=%d)", len(reply_text.strip()))
                    _llm_attempts += 1
                    if _llm_attempts >= _max_llm_attempts:
                        logger.info("Phase B: LLM attempt cap reached (%s/%s), stopping cycle.",
                                    _llm_attempts, _max_llm_attempts)
                        break
                    continue

                # ── Deferred claim check: runs AFTER cheap gates, saving LLM calls ──
                if claim and reply_text:
                    try:
                        check_result = await check_claim(
                            claim, reply_text, self.llm,
                            tier=getattr(self, "_claim_checker_tier", "flash"),
                        )
                    except Exception:
                        # Fail-CLOSED: si el claim checker no puede evaluar
                        # (LLM caido, JSON truncado), el claim no queda validado
                        # y el reply NO se publica. Antes era fail-open
                        # (on_topic=True) y dejaba pasar claims no verificados.
                        check_result = {
                            "on_topic": False, "score": 0.0,
                            "reason": "check skipped (LLM error) — fail closed",
                        }
                    self._last_claim_check = check_result
                    on_topic = check_result.get("on_topic", False)
                    check_score = check_result.get("score", 0.0)
                    if on_topic or check_score >= 0.4:
                        self._stats["claim_check_passed"] += 1
                    else:
                        self._stats["claim_check_failed"] += 1
                        logger.warning(
                            "Phase B: claim-check FAILED — on_topic=%s, score=%s, reason=%s",
                            on_topic, check_score, check_result.get("reason", ""),
                        )
                        _llm_attempts += 1
                        if _llm_attempts >= _max_llm_attempts:
                            logger.info("Phase B: LLM attempt cap reached (%s/%s), stopping cycle.",
                                        _llm_attempts, _max_llm_attempts)
                            break
                        continue

                resp = self._safe_publish_comment(post_id=str(post_id), content=reply_text,
                                                  require_evidence=(reply_tier == "quality"))
                if resp is None:
                    _llm_attempts += 1
                    if _llm_attempts >= _max_llm_attempts:
                        logger.info("Phase B: LLM attempt cap reached (%s/%s), stopping cycle.",
                                    _llm_attempts, _max_llm_attempts)
                        break
                    continue

                success = False
                status = None
                error_text = None
                raw = None
                already_existed = False
                comment_id = None

                if isinstance(resp, dict):
                    success = bool(resp.get("success"))
                    status = resp.get("status") or resp.get("status_code")
                    error_text = resp.get("error")
                    comment_id = resp.get("id")
                    raw = resp.get("raw") if isinstance(resp.get("raw"), dict) else {}
                    already_existed = bool(raw.get("already_existed"))
                    if not comment_id and isinstance(raw.get("comment"), dict):
                        comment_id = raw["comment"].get("id")
                else:
                    success = bool(getattr(resp, "success", False))
                    status = getattr(resp, "status", None) or getattr(resp, "status_code", None)
                    error_text = getattr(resp, "error", None)
                    raw = getattr(resp, "raw", None)
                    if isinstance(raw, dict):
                        already_existed = bool(raw.get("already_existed"))
                        if isinstance(raw.get("comment"), dict):
                            comment_id = raw["comment"].get("id")
                    if not comment_id:
                        comment_id = getattr(resp, "id", None)

                if success and already_existed:
                    logger.info(
                        "Phase B: comentario deduplicado en post_id=%s comment_id=%s; no se cuenta como nuevo.",
                        post_id,
                        comment_id,
                    )
                    interlocutors.record_interaction(
                        post.get("author"), on_our_post=False,
                    )
                    self.incr_comments_today()
                    results.append({
                        "post_id": post_id,
                        "comment_id": comment_id,
                        "content": reply_text,
                        "success": True,
                        "already_existed": True,
                        "status": status,
                        "error": error_text,
                    })
                    continue

                if success:
                    logger.info(
                        "Phase B: comentario publicado en post_id=%s title=%s... tier=%s author=%s watchlist=%s",
                        post_id,
                        str(post.get("title") or "")[:40],
                        (post.get("_reply_tier") if isinstance(post, dict) else getattr(post, "_reply_tier", "flash")) or "flash",
                        feed_author,
                        is_wl,
                    )
                    # ── Post-pairing feeder: engancha al autor top hacia NOSOTROS ──
                    # Cada reply exitosa a un post de watchlist registra un "counter-claim"
                    # en la agenda para que Fase A publique un refute/profundizacion
                    # 6-24h despues. Es el mecanismo de invitacion implicita.
                    if is_wl:
                        try:
                            from services.research_agenda import load_agenda, save_agenda
                            _ag = load_agenda()
                            _claim = str(post.get("content") or post.get("body") or "")[:200]
                            _counter_topic = (
                                f"Counter-claim to the position by {feed_author} on "
                                f"'{str(post.get('title') or '')[:80]}': sharpen the limit of "
                                f"the mechanism they defend and propose the boundary condition "
                                f"where it fails"
                            )
                            _ag.add_topic(_counter_topic, source="watchlist_pairing", tags=["watchlist", feed_author])
                            save_agenda(_ag)
                            logger.info("Phase B: watchlist pairing topic added (author=%s)", feed_author)
                        except Exception as _e:
                            logger.debug("Phase B: watchlist pairing feeder failed: %s", _e)
                    interlocutors.record_interaction(
                        post.get("author"), on_our_post=False,
                    )
                    feed_comment_count += 1
                    cycle_comment_count += 1
                    if is_wl:
                        self._watchlist_feed_count += 1
                    else:
                        self._general_feed_count += 1
                    self.incr_comments_today()
                    send_event("phase_b_reply_success", {
                        "post_id": post_id,
                        "comment_id": comment_id,
                    })

                    try:
                        update_today_metrics(comments_published=1)
                    except Exception as e:
                        logger.warning(f"SelfEval: error registrando comments_published=1: {e}")

                    if comment_id:
                        post_body = str(post.get("content") or post.get("body") or "").strip()
                        await self._classify_and_log_value(post, post_body, reply_text, str(comment_id),
                                                         comment_author=str(post.get("author", "")))
                        if post_id not in self._agent_comment_ids:
                            self._agent_comment_ids[post_id] = []
                        self._agent_comment_ids[post_id].append(str(comment_id))
                        self._dedup.sync_agent_comment_ids(self._agent_comment_ids)
                        _append_to_reply_history(reply_text)

                    # Add topic to research agenda if frontier potential detected
                    if post_decision.score >= POLICY.min_comment_relevance_score + 20:
                        self._add_topic_to_agenda(post, post_body)

                    self._commented_post_ids[post_id] = datetime.now(timezone.utc).isoformat()
                    self._dedup.set_commented_post(post_id)
                    self._post_history_guard[post_id] = datetime.now(timezone.utc).isoformat()
                    _save_post_history_guard(self._post_history_guard)
                    if comment_id:
                        feed_dedup_key = f"feed:{post_id}:{comment_id}"
                        self._replied_comment_ids.add(feed_dedup_key)
                        self._dedup.mark_replied(feed_dedup_key)

                    # ── Write long-term memory ─────────────────────
                    try:
                        feed_author_raw = post.get("author")
                        if isinstance(feed_author_raw, dict):
                            feed_author_name = str(feed_author_raw.get("name") or "")
                        else:
                            feed_author_name = str(feed_author_raw or "")
                        if feed_author_name:
                            feed_summary = (
                                f"Usuario dijo: {post_body[:150]} | "
                                f"Agente respondió: {reply_text[:150]}"
                            )
                            self._memory.update_memory(
                                feed_author_name, feed_author_name, feed_summary
                            )
                    except Exception:
                        pass

                    results.append({
                        "post_id": post_id,
                        "comment_id": comment_id,
                        "content": reply_text,
                        "success": True,
                        "already_existed": False,
                        "status": status,
                    })
                else:
                    logger.warning(
                        "Phase B: fallo al comentar en post_id=%s status=%s error=%s",
                        post_id,
                        status,
                        error_text,
                    )
                    enqueue_outbox("comment", {"post_id": post_id, "content": reply_text, "parent_comment_id": None})
                    results.append({
                        "post_id": post_id,
                        "content": reply_text,
                        "success": False,
                        "already_existed": False,
                        "status": status,
                        "error": error_text,
                    })

            if not results:
                logger.info("Phase B: no se publicaron comentarios en este ciclo (feed replies).")

            span.set("posted", cycle_comment_count)
            return results

    def _is_own_author(self, author: str) -> bool:
        """Compara el nombre del autor con el nombre del agente normalizando
        guiones y guiones bajos.  Ejemplo: 'COMET-RIOBAMBA' y 'comet_riobamba'
        se consideran el mismo agente.
        """
        if not author or not self.agent_name:
            return False
        a = author.lower().replace("-", "_").replace(" ", "_")
        n = self.agent_name.lower().replace("-", "_").replace(" ", "_")
        return n in a or a in n

    def _fetch_candidate_posts(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch feed candidates from both 'hot' and 'new' sort orders,
        deduplicate by post_id, and apply age/submolt filters."""
        try:
            all_posts: Dict[str, Dict[str, Any]] = {}
            sources: Dict[str, int] = {}

            for sort_order in ("hot", "new"):
                resp: APIResponse = self.api.get_feed(limit=limit, sort=sort_order)
                if not getattr(resp, "success", False):
                    logger.warning(
                        "Phase B: get_feed sort=%s falló status=%s error=%s",
                        sort_order,
                        getattr(resp, "status", None) or getattr(resp, "status_code", None),
                        getattr(resp, "error", None),
                    )
                    sources[sort_order] = 0
                    continue

                data = getattr(resp, "data", None)
                if isinstance(data, dict):
                    posts_list = data.get("posts", [])
                elif isinstance(data, list):
                    posts_list = data
                else:
                    posts_list = []

                if not isinstance(posts_list, list):
                    logger.warning("Phase B: estructura inesperada en get_feed sort=%s.", sort_order)
                    posts_list = []

                added = 0
                for p in posts_list:
                    if not isinstance(p, dict):
                        continue
                    pid = p.get("id") or p.get("post_id") or ""
                    if pid and pid not in all_posts:
                        all_posts[pid] = p
                        added += 1
                sources[sort_order] = added

            logger.info(
                "Phase B: feed sources — hot=%s, new=%s, unique_total=%s",
                sources.get("hot", 0), sources.get("new", 0), len(all_posts),
            )

            posts = list(all_posts.values())

            filtered: List[Dict[str, Any]] = []
            blocked_count = 0
            allowlist_blocked_count = 0
            stale_count = 0
            spam_count = 0
            now = datetime.now(timezone.utc)
            max_age_days = 7
            for p in posts:
                if not isinstance(p, dict):
                    continue
                # ── Spam/deleted/locked gate: la plataforma ya los marco ──
                if p.get("is_spam") or p.get("is_deleted") or p.get("is_locked"):
                    spam_count += 1
                    logger.info("Phase B: post %s REJECTED (spam/deleted/locked)", p.get("id"))
                    continue
                # ── Age gate: reject posts older than 7 days ──
                ts_raw = p.get("created_at") or p.get("createdAt") or p.get("timestamp") or ""
                if ts_raw:
                    try:
                        ts_str = str(ts_raw).replace("Z", "+00:00")
                        post_dt = datetime.fromisoformat(ts_str)
                        if post_dt.tzinfo is None:
                            post_dt = post_dt.replace(tzinfo=timezone.utc)
                        age_days = (now - post_dt).total_seconds() / 86400.0
                        if age_days > max_age_days:
                            stale_count += 1
                            logger.debug("Phase B: post %s descartado: age=%.1f days (max=%d days)", p.get("id"), age_days, max_age_days)
                            continue
                    except Exception:
                        pass  # Can't parse date, let it through
                raw_sub = p.get("submolt") or p.get("community") or ""
                sub = raw_sub  # Keep raw for dict handling
                # Extract submolt name whether API returns dict or string
                from .candidate_scorer import _extract_submolt_name
                sub_name = _extract_submolt_name(raw_sub) if raw_sub else ""
                if sub_name in BLOCKED_SUBMOLTS:
                    blocked_count += 1
                    logger.debug("Phase B: post %s descartado: submolt bloqueado '%s'", p.get("id"), sub_name)
                    continue
                # v5.0: Allowlist gate — only keep posts from allowed submolts (when submolt present)
                if sub_name:
                    sub_clean = _strip_submolt_prefix(sub_name)
                    if ALLOWED_SUBMOLTS and sub_clean not in ALLOWED_SUBMOLTS:
                        allowlist_blocked_count += 1
                        logger.info("Phase B: post %s REJECTED (submolt='%s' not in allowlist=%s)", p.get("id"), sub_name, sorted(ALLOWED_SUBMOLTS))
                        continue
                filtered.append(p)

            logger.info(
                "Phase B: %s posts candidatos (total_feed=%s, blocked=%s, allowlist_rejected=%s, stale=%s, spam=%s).",
                len(filtered), len(posts), blocked_count, allowlist_blocked_count, stale_count, spam_count,
            )
            return filtered

        except Exception as e:
            logger.warning(f"Phase B: error obteniendo feed de posts: {e}")
            return []

    def _can_comment_in_thread(self, post: Dict[str, Any]) -> bool:
        """Feed-only: check if the agent has already reached max_feed_comments_per_post
        replies in this thread.  Own-post replies use a separate per-post limit
        (max_comments_per_post) enforced in _process_own_post."""
        try:
            comments = post.get("comments") or []
            if not isinstance(comments, list):
                return True

            my_name = (self.agent_name or "").strip()
            if not my_name:
                return True

            my_name_l = my_name.lower()
            my_count = 0

            for c in comments:
                if not isinstance(c, dict):
                    continue
                author_value = c.get("author")
                author = ""
                if isinstance(author_value, dict):
                    author = str(author_value.get("name") or "").lower()
                else:
                    author = str(author_value or "").lower()
                if my_name_l and my_name_l in author:
                    my_count += 1

            return self.max_feed_comments_per_post is None or my_count < self.max_feed_comments_per_post

        except Exception as e:
            logger.warning(f"Phase B: error en _can_comment_in_thread: {e}")
            return True

    @staticmethod
    def _extract_parent_id(c: Dict) -> str:
        pid = c.get("parent_id") or c.get("parentId") or c.get("parent_comment_id")
        if not pid:
            parent = c.get("parent") if isinstance(c.get("parent"), dict) else {}
            reply_to = c.get("reply_to") if isinstance(c.get("reply_to"), dict) else {}
            pid = parent.get("id") or reply_to.get("id")
        return str(pid or "")

    @staticmethod
    def _post_age_minutes(post: Optional[Dict]) -> Optional[float]:
        """Edad del post en minutos. None si el timestamp falta o es invalido.

        Acepta created_at o published_at. Soporta sufijo Z (UTC) y naive
        (se asume UTC). Usado por la fast-lane early-watchlist (25/08/2026)
        para priorizar posts frescos.
        """
        if not post or not isinstance(post, dict):
            return None
        ts = post.get("created_at") or post.get("published_at")
        if not ts or not isinstance(ts, str):
            return None
        try:
            normalized = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
        except (ValueError, TypeError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - dt).total_seconds() / 60.0

    @staticmethod
    def _compute_thread_depth(comment: Dict, all_comments: List[Dict]) -> int:
        """How many levels deep this comment is in the thread.

        Depth 0 = no parent id (top-level).
        Depth 1 = parent is a top-level comment.
        Depth 2 = grandparent is a top-level comment, etc.
        """
        depth = 0
        parent_id = PhaseB._extract_parent_id(comment)
        if not parent_id:
            return 0
        cmap = {c.get("id"): c for c in all_comments if c.get("id")}
        while parent_id and parent_id in cmap:
            depth += 1
            parent_id = PhaseB._extract_parent_id(cmap[parent_id])
        return depth

    def _thread_depth_limit(self, comment: Dict, all_comments: List[Dict],
                            author_key: str, is_watchlist: bool) -> Tuple[int, Optional[str]]:
        """Limite fijo de interacciones por conversacion (politica vigente).

        Maximo 4 intercambios del agente en un hilo, sea quien sea el autor
        (watchlist o historial NO extienden el limite: el agente defiende su
        teoria hasta 4 interacciones y luego deja el tema cerrado). Se corta
        ANTES de la base si el hilo empieza a repetirse (duplicado semantico
        contra el turno anterior). Devuelve (limite, motivo_de_cierre).
        """
        cur = (comment.get("content") or comment.get("text") or "").strip()
        parent_id = PhaseB._extract_parent_id(comment)
        cmap = {c.get("id"): c for c in all_comments if c.get("id")}
        parent = cmap.get(parent_id) if parent_id else None
        parent_text = (parent.get("content") or parent.get("text") or "").strip() if parent else ""
        grandparent_text = ""
        if parent:
            gp_id = PhaseB._extract_parent_id(parent)
            gp = cmap.get(gp_id) if gp_id else None
            if gp:
                grandparent_text = (gp.get("content") or gp.get("text") or "").strip()

        # Repeticion: el turno actual repite al anterior -> cerrar ya.
        if parent_text and cur and is_semantic_duplicate_reply(cur, parent_text, threshold=0.80):
            return 1, "repetición"

        base = 4
        return base, None

    async def _close_thread_decision(self, post_id: str, reply_comment: Dict,
                                     comments: List[Dict], author: str,
                                     close_reason: str) -> str:
        """Fin natural del hilo: un cierre de sintesis SOLO si hay una idea que
        unifica; si no, let_stand — no se publica nada y el ultimo punto queda
        parado. Nunca wrap-ups del tipo 'great discussion/thanks'.

        Devuelve el motivo real del cierre: 'synthesized' | 'let_stand'."""
        # Guard anti-loop: si el hilo ya se cerro (con o sin sintesis), NO
        # volver a decidir — el loop de sintesis publica un comentario nuevo,
        # recibe respuestas y se re-cierra en cada ciclo.
        if is_thread_closed(post_id):
            logger.info("Phase B: thread close: let_stand (post %s, hilo ya cerrado)", post_id)
            return "let_stand"
        thread_history = self._build_thread_history(reply_comment, comments)
        cur = (reply_comment.get("content") or reply_comment.get("text") or "").strip()
        close_prompt = (
            f"Thread summary:\n{thread_history[-1500:]}\n\n"
            f"Last message: {cur[:600]}\n\n"
            "Close only if you can add a unifying insight neither side stated. "
            "Otherwise output CLOSE."
        )
        try:
            raw = await self.llm.generate(
                tier="flash", prompt=close_prompt,
                system_prompt=(
                    "You are a sharp engineer ending a debate. No wrap-ups, no "
                    "thanks, no summaries. Output CLOSE or one dense closing "
                    "insight (80-200 chars)."
                ),
                max_tokens=250, temperature=0.4,
            )
        except Exception as e:
            logger.debug("Phase B: cierre con sintesis fallo (%s) -> let_stand", e)
            raw = ""
        closing = (raw or "").strip()

        def _let_stand(log_reason: str) -> str:
            close_thread(post_id)
            logger.info("Phase B: thread close: let_stand (post %s, %s)", post_id, log_reason)
            return "let_stand"

        if not closing or closing.upper().startswith("CLOSE") or len(closing) < 60:
            return _let_stand(f"motivo={close_reason}, sin sintesis genuina")
        closing_lower = closing.lower()
        if any(w in closing_lower for w in (
            "great discussion", "thanks for", "thank you", "good chat", "great chat",
        )):
            return _let_stand("wrap-up descartado")
        _ctx = f"{thread_history} {cur}"
        if text_has_unverifiable_historical_claim(closing, _ctx):
            return _let_stand("cierre con cita historica no verificable")
        if text_has_fabricated_measurement(closing):
            return _let_stand("cierre fabricado")
        try:
            resp = self._safe_publish_comment(
                post_id=str(post_id),
                content=closing,
                parent_comment_id=str(reply_comment.get("id") or ""),
                is_followup=True,
            )
            success = bool(resp.get("success")) if isinstance(resp, dict) else bool(getattr(resp, "success", False))
            if success:
                self.incr_comments_today()
                logger.info("Phase B: thread close: synthesized (post %s)", post_id)
                return "synthesized"
        except Exception as e:
            logger.debug("Phase B: publicacion de sintesis fallo (%s)", e)
        return _let_stand("publicacion de sintesis fallo")

    async def _critique_quality_draft(self, reply: str, source_text: str) -> Tuple[str, str]:
        """Borrador + revision para replies de ALTA exposicion (tier_quality).

        UNA llamada de critica (flash, no classify: el 3B falla el 75% del
        JSON) contra la rubrica: responde al punto especifico? agrega algo
        nuevo? sin cita historica no verificable? sin repetir lo ya dicho?
        Si la critica encuentra un problema -> UNA revision que lo corrige.
        Si la revision queda peor (corta/vacia) se conserva el borrador.
        Devuelve (texto_final, log)."""
        if not reply or not reply.strip():
            return reply, "draft kept (vacio)"
        rubric = (
            "You are a sharp editorial critic for a senior engineer's reply. "
            "Evaluate: (1) does it answer the specific point raised? "
            "(2) does it add something NEW, not paraphrase the other side? "
            "(3) no unverifiable dated third-party incidents? "
            "(4) no repetition of what was already said in the thread?\n"
            "If the draft is solid, reply OK. If not, reply with the single "
            "most important problem to fix (one sentence)."
        )
        try:
            verdict = await self.llm.generate(
                tier="flash",
                prompt=f"REPLY DRAFT:\n{reply}\n\nSOURCE:\n{source_text[:800]}",
                system_prompt=rubric,
                max_tokens=150, temperature=0.1,
            )
        except Exception as e:
            logger.debug("Phase B: critica quality fallo (%s) -> draft kept", e)
            return reply, "draft kept (critica fallo)"
        verdict_text = (verdict or "").strip()
        if not verdict_text or verdict_text.upper().startswith("OK") or len(verdict_text) < 10:
            return reply, "draft kept (critica aprueba)"
        low = verdict_text.lower()
        if any(k in low for k in ("no problem", "solid", "looks good", "well written", "no issues")):
            return reply, "draft kept (critica aprueba)"
        try:
            revised = await self.llm.generate(
                tier="flash",
                prompt=(
                    f"Rewrite the draft fixing exactly this: {verdict_text[:300]}\n\n"
                    f"ORIGINAL DRAFT:\n{reply}\n\n"
                    "Return only the revised reply, same voice, no preamble."
                ),
                system_prompt=(
                    "You are a senior systems engineer. Fix the draft, keep the "
                    "voice, do not soften it, do not add thanks or wrap-up."
                ),
                max_tokens=300, temperature=0.4,
            )
        except Exception:
            revised = ""
        revised_text = (revised or "").strip()
        if not revised_text or len(revised_text) < max(30, len(reply) // 2):
            return reply, f"draft kept (revision peor: {verdict_text[:80]})"
        # FIX 2026-09-15: guard anti-leak de prompt. El rewrite a veces
        # devuelve el razonamiento del modelo ("We need to rewrite...") en
        # vez de la reply revisada. Conservar el borrador original.
        from services.quality_governor import text_has_reasoning_leak
        if text_has_reasoning_leak(revised_text):
            logger.warning("Phase B: rewrite con prompt-leak; se conserva el borrador original")
            return reply, f"draft kept (prompt-leak en revision: {revised_text[:60]})"
        return revised_text, f"draft revised ({verdict_text[:80]})"
    async def _generate_reply_bestof(self, user_prompt: str, system_prompt: str,
                                     title: str, body: str, tier: str = "flash") -> str:
        """Best-of-2: genera 2 borradores y conserva el de mayor _score_reply_draft.
        Degradación elegante: si el 2º falla o sale vacío se usa el 1º; nunca
        devuelve un resultado peor/inválido que un reply único."""
        source_text = f"{title}\n{body}".strip()
        candidate_a = ""
        candidate_b = ""
        try:
            raw_a = await self.llm.generate(
                tier=tier,
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=180,
                temperature=0.7,
            )
            candidate_a = (raw_a or "").strip()
        except Exception as e:
            logger.warning("Phase B: best-of-2 first candidate failed: %s", e)
        try:
            raw_b = await self.llm.generate(
                tier=tier,
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=180,
                temperature=0.8,
            )
            candidate_b = (raw_b or "").strip()
        except Exception as e:
            logger.warning("Phase B: best-of-2 second candidate failed: %s", e)

        if not candidate_a:
            return candidate_b
        if not candidate_b:
            return candidate_a
        score_a, _ = await self._score_reply_draft(candidate_a, source_text)
        score_b, _ = await self._score_reply_draft(candidate_b, source_text)
        chosen = candidate_a if score_a >= score_b else candidate_b
        logger.info("Phase B: best-of-2 reply — A=%d B=%d chosen=%s",
                    score_a, score_b, "A" if chosen == candidate_a else "B")
        return chosen

    async def _generate_reply_for_post(self, post: Dict[str, Any], bestof: bool = False, tier: str = "flash") -> Tuple[str, Optional[Dict[str, Any]]]:
        with Span("llm_generation", type="feed") as span:
            title = str(post.get("title") or "").strip()
            body = str(post.get("content") or post.get("body") or "").strip()

            author_value = post.get("author")
            if isinstance(author_value, dict):
                author = str(author_value.get("name") or "another agent").strip()
            else:
                author = str(author_value or "another agent").strip()

            lang_instruction = (
                "Always respond in English. This is an English-speaking platform."
            )

            system_prompt = (
                "You are COMET-RIOBAMBA, a systems engineer who has spent years "
                "watching autonomous agents fail in production. You write the way "
                "you debug: direct, concrete, and a little impatient with theory "
                "that never met a real workload.\n"
                "You have NO production deployment and run NO experiments — "
                "so you never claim 'we measured'. You reason from mechanisms, "
                "invariants, and thresholds.\n\n"
                "VOICE (this is your identity, not a template):\n"
                "- Write like a colleague who has seen the failure, not a paper "
                "reviewer. Contracted, plain, specific.\n"
                "- Each reply should read like ONE sharp thought pushed to its "
                "limit — not four labeled sections.\n"
                "- Vary your opening: sometimes a question, sometimes a hard "
                "counter-example, sometimes the single number that changes the "
                "argument. NEVER announce your structure.\n"
                "- No numbered steps, no bullet lists, no markdown.\n\n"
                "WHAT THE REPLY MUST DO (pick one, commit to it):\n"
                "- Extend the claim with a mechanism the author didn't name, OR\n"
                "- Name the boundary condition where their claim breaks, OR\n"
                "- Give the threshold/procedure that operationalizes the idea.\n"
                "Engage the SPECIFIC argument in front of you — if a previous "
                "comment already covered a point, don't restate it, build past it.\n\n"
                "HARD CONSTRAINTS:\n"
                "- No emojis, hashtags, links.\n"
                "- Do not be agreeable. Add friction, not praise.\n"
                "- DO NOT fabricate measurements. You have NO production data.\n"
                "- Reply length 80-500 chars. Density over decoration.\n"
                "- No unverifiable third-party incidents or named anecdotes you "
                "cannot source. AVOID specific years (1990, 2003, 2016, etc.) unless in source context. Use early 2000s or past decade instead.\n"
                "- If they brought data or admitted limits: extend, contrast, or "
                "ask what their data opens — never restate their conclusion as "
                "yours.\n\n"
                f"{lang_instruction}\n\n"
                f"{COMMENT_STYLE_INSTRUCTIONS}"
            )
            # ── Delimitador de contenido no confiable + derecho a abstenerse ──
            # (verbatim: los tests de inyección/abstain lo exigen así)
            system_prompt = system_prompt + "\n\n" + UNTRUSTED_DIRECTIVE + "\n\n" + ABSTAIN_RULE

            # ── Inject reply feedback strategy hint ───────────────────────
            try:
                from services.reply_feedback import get_strategy_prompt_injection
                _feedback_note = get_strategy_prompt_injection()
                if _feedback_note:
                    system_prompt += f"\n\n{_feedback_note}"
            except Exception:
                pass

            # ── Inject strategy directives ────────────────────────────────
            try:
                _strategy = StrategyState()
                _state = _strategy.load()
                _parts = []
                if _state.get("top_topics"):
                    _parts.append(
                        f"Focus on topics like {', '.join(_state['top_topics'])}."
                    )
                if _state.get("avoid_topics"):
                    _parts.append(
                        f"Avoid topics like {', '.join(_state['avoid_topics'])}."
                    )
                if _parts:
                    system_prompt = system_prompt + (
                        "\n\nPERFORMANCE DIRECTIVE: " + " ".join(_parts)
                    )
            except Exception:
                pass

            # ── Claims Tracker context ────────────────────────────
            _claims_tracker = None  # type: Optional[ClaimsTracker]
            _claims_cluster = "infrastructure"
            try:
                _claims_tracker = ClaimsTracker(Path.cwd())
                _claims_cluster = _detect_cluster(f"{title} {body}")
                # ── Energy-tech keyword override for ClaimsTracker ──
                _tech_keywords_map = {
                    "battery": "solid-state-battery", "batería": "solid-state-battery",
                    "hidrógeno": "green-hydrogen", "hydrogen": "green-hydrogen",
                    "solar": "perovskite-solar", "perovskite": "perovskite-solar",
                    "agrivoltaic": "agrivoltaics", "agripv": "agrivoltaics",
                    "sodium": "sodium-ion", "na-ion": "sodium-ion",
                    "electrólisis": "green-hydrogen", "electrolysis": "green-hydrogen",
                }
                _post_text = f"{title} {body}".lower()
                for _kw, _cluster in _tech_keywords_map.items():
                    if _kw in _post_text:
                        _claims_cluster = _cluster
                        break
                _claims_context = _claims_tracker.get_context_for_reply(_claims_cluster)
                _depth_directive = get_reply_depth_directive()
                if _claims_context:
                    system_prompt = system_prompt + "\n\n" + _claims_context
                # ── Communication mode (voice) ────────────────────
                _self_diag = getattr(self, "self_diagnosis", None)
                _mode_name = select_mode(_self_diag, {"topic_cluster": _claims_cluster})
                _mode_prompt = get_mode_prompt(_mode_name)
                if _mode_prompt:
                    system_prompt = system_prompt + "\n\n" + _mode_prompt
                    logger.info("Phase B: Engaging communication mode: %s", _mode_name)
                if _depth_directive:
                    system_prompt = system_prompt + "\n\n" + _depth_directive
                # ── Active RAG — EIN context ─────────────────────
                _ein_context = _get_ein_context(f"{title} {body}")
                if _ein_context:
                    system_prompt = system_prompt + "\n\n" + _ein_context
                    logger.info("Phase B: Injected EIN context into feed reply prompt")
            except Exception:
                pass

            # ── Memory context ────────────────────────────────────
            memory_note = ""
            try:
                mem = self._memory.get_memory(author)
                if mem:
                    memory_note = (
                        f"MEMORY NOTE: You have interacted with @{mem['username']} "
                        f"before. Prior context: {mem['summary']}\n\n"
                    )
            except Exception:
                pass

            # Si tanto dashscope como groq tienen el circuito abierto, usar prompt simple
            try:
                from services.model_cascade import ModelCascade
                if isinstance(self.llm, ModelCascade):
                    haiku_open = self.llm._is_circuit_open_by_name("tier_fallback")
                    groq_open = self.llm._is_circuit_open_by_name("groq")
                    if haiku_open and groq_open:
                        logger.warning("Phase B: Main model circuits OPEN (fallback=%s, groq=%s). Skipping reply generation — no reliable LLM available.", haiku_open, groq_open)
                        return "", None
            except Exception:
                pass

            # ── Deteccion de prompt injection (telemetria, no bloqueo) ──
            # El texto del post ajeno ya viaja en <untrusted_content>; si
            # intenta redirigir al agente, se registra el intento.
            try:
                _inj_fragment = detect_prompt_injection(f"{title} {body}")
                if _inj_fragment:
                    logger.warning("prompt injection attempt from %s (post %s)", author, post.get("id"))
                    log_injection_attempt(
                        author=author,
                        post_id=str(post.get("id") or ""),
                        source="feed_reply",
                        fragment=_inj_fragment,
                    )
            except Exception:
                pass

            user_prompt = memory_note + REPLY_TEMPLATE.format(
                title=title,
                content=body[:1200],
                min=80,
                max=400
            )

            # ── CTA de retorno: post-pairing hook para autores watchlist ──
            # Cuando respondemos a un autor top, cerramos con una pregunta de
            # co-diseno que invita a seguir el tema en NUESTRO post. Convierte
            # la reply de "participacion" a "invitacion implicita".
            try:
                if post.get("_reply_tier") == "quality":
                    _enter_hook = (
                        "\n\nENGAGEMENT HOOK (Solo para este autor senior): "
                        "En las ultimas 2 frases, plantea UNA pregunta de co-diseno "
                        "abierta y provocadora sobre la tension central (el threshold "
                        "o trade-off del que hablaste). La pregunta debe ser lo "
                        "suficientemente especifica como para que el autor quiera "
                        "responder y su respuesta natural sea un post o comentario "
                        "largo. NO nombre otras plataformas. Termina con la pregunta, "
                        "sin cortesia."
                    )
                    system_prompt = system_prompt + _enter_hook
            except Exception:
                pass

            if not self.llm:
                span.set("length", 0)
                return "", None

            # ── Step A: Extract claim ──────────────────────────────────────
            claim = None
            post_text = f"{title}\n{body}".strip()
            try:
                claim = await extract_claim(
                    post_text, post_text, self.llm,
                    tier=getattr(self, "_claim_checker_tier", "flash"),
                )
            except Exception:
                pass

            if claim:
                must_address = claim.get("reply_must_address", "")
                constraint = (
                    f"\n\nIMPORTANT: The reply MUST directly engage with: {must_address}"
                )
                system_prompt = system_prompt + constraint

            # ── Step B: Generate reply ─────────────────────────────────────
            # Best-of-2 selectivo (solo posts de alta relevancia + flag activo):
            # genera 2 borradores y conserva el de mayor _score_reply_draft.
            # Degradación elegante: si el 2º falla/vacío se usa el 1º; con flag
            # OFF o baja relevancia el comportamiento (1 llamada) es idéntico.
            try:
                if bestof:
                    reply = await self._generate_reply_bestof(
                        user_prompt, system_prompt, title, body, tier=tier
                    )
                else:
                    reply = await self.llm.generate(
                        tier=tier,
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        max_tokens=180,
                        temperature=0.7,
                    )
                    reply = (reply or "").strip()
                span.set("length", len(reply) if reply else 0)

                # ── ABSTAIN: salida legitima, no inventar lo no fundamentado ──
                # No publica, cuenta en abstained del ciclo y en el tracker
                # diario (vigilancia de targeting, no fallo de generacion).
                if reply.strip().upper().startswith("ABSTAIN"):
                    self._stats["abstained"] = self._stats.get("abstained", 0) + 1
                    record_abstain(True)
                    logger.info("Phase B: feed reply ABSTAIN (post %s)", post.get("id"))
                    return "ABSTAIN", None
                record_abstain(False)

                # ── Gate de citas historicas: un año fuera del contexto es un
                # incidente de terceros con detalles no verificables ──
                # El contexto valido es SOLO lo externo: el post del otro y la
                # evidencia inyectada (EIN). El claims_context es OUTPUT del
                # propio agente: usarlo como contexto auto-legitima sus citas
                # pasadas (loop de auto-contaminacion: el claim '2016 Dyn' del
                # tracker permitia volver a citar 2016 Dyn indefinidamente).
                _hist_ctx = f"{title} {body}"
                try:
                    _hist_ctx += " " + str(_ein_context or "")
                except Exception:
                    pass
                _bad_year = text_has_unverifiable_historical_claim(reply, _hist_ctx)
                if _bad_year:
                    logger.warning(
                        "Phase B: feed reply REJECTED — unverifiable historical claim (año %s) en post %s",
                        _bad_year, post.get("id"),
                    )
                    return "", None

                # ── Borrador + revision (writer + critic). No todo el volumen:
                # solo alta exposicion (watchlist) y canales con ROI medido
                # (data-driven). El resto pasa sin critica para no duplicar
                # el costo en canales sin retorno demostrado. ──
                if self._should_critique(tier, author):
                    reply, _quality_log = await self._critique_quality_draft(reply, f"{title} {body}")
                    logger.info("Phase B: quality reply: %s (post %s)", _quality_log, post.get("id"))

                # ── Historical examples gate: block if repeated example ──
                is_repeat, blocked_examples = is_example_recently_used(reply)
                if is_repeat:
                    logger.warning("Phase B: feed reply BLOCKED — repeated historical examples: %s", ", ".join(blocked_examples))
                    return "", None

                score, reasons = await self._score_reply_draft(reply, f"{title}\n{body}",
                                                            log_context={"post_id": post.get("id")},
                                                            block_ungrounded=(tier == "quality")
                                                            or text_exposes_figures(f"{title}\n{body}"))
                if score < 10:
                    logger.warning(
                        "Phase B: feed reply REJECTED — score=%d reasons=%s preview=%s",
                        score, ",".join(reasons) or "none", reply[:100],
                    )
                    return "", None

                # ── Claim check MOVED to caller (_execute_feed_replies)
                # so it runs AFTER fabrication/dupe/length gates.
                # Return claim for deferred checking.

                # ── Register claims from reply ─────────────────────
                try:
                    if reply and _claims_tracker is not None:
                        ct_result = _claims_tracker.register_claims(reply, _claims_cluster)
                        logger.info(">>> [WIRE CHECK] Escribiendo claims_tracker.json (feed reply): %s", ct_result)
                except Exception:
                    pass

                try:
                    if reply:
                        reply_count = len(post.get("comments", []))
                        log_dual_score(reply, phase="b", reply_count=reply_count)
                        logger.info(">>> [WIRE CHECK] Escribiendo dual_scores.jsonl (feed reply)")
                except Exception:
                    pass

                # --- HARD FILTER: Block LLM hallucinations ---
                for _phrase in FORBIDDEN_PHRASES:
                    if _phrase in reply.lower():
                        logger.warning("Phase B: BLOCKED feed reply — forbidden phrase '%s'", _phrase)
                        span.set("length", 0)
                        return "", None
                fingerprint = self._reply_theme_fingerprint(reply, f"{title}\n{body}")
                if fingerprint:
                    self._replied_topic_fingerprints.add(fingerprint)
                    self._dedup.sync_replied_topic_fingerprints(self._replied_topic_fingerprints)

                # ── Quality gate: signal check logged for diagnostics, never blocks ──
                # (v5.1: length + banned openers are enforced in _safe_publish_comment;
                #  evidence/framework/metric are logged here for visibility only.)
                # REMOVED: wasteful retry loop — _passes_quality_gate always returns True
                # after length/banned-opener check; retrying never helps and burns 1 LLM call.

                return _safe_truncate(reply, max_chars=500), claim
            except Exception as e:
                logger.warning(f"Phase B: error en generación de reply: {e}")
                span.set("length", 0)
                return "", None

    # ── Value classification ──────────────────────────────────────

    async def _classify_and_log_value(
        self,
        post: Dict[str, Any],
        comment_text: str,
        reply_text: str,
        comment_id: str,
        follow_up: str = "",
        comment_author: str = "",
    ) -> None:
        from .value_log_utils import _classify_and_log_value
        await _classify_and_log_value(self, post, comment_text, reply_text, comment_id, follow_up, comment_author=comment_author)

    # ── Own post replies (antes phase_b_responses.py) ─────────────

    async def _execute_own_post_replies(self) -> List[Dict[str, Any]]:
        with Span("own_post_replies") as span:
            if not self.llm:
                logger.warning("Phase B: model_cascade no disponible; se omiten own post replies.")
                span.set("results", 0)
                return []

            try:
                posts = self._fetch_own_posts_for_replies()
            except Exception as e:
                logger.error(f"Phase B: error fetching my posts: {e}")
                span.set("results", 0)
                return []

            if not posts:
                logger.info("Phase B: no published posts found")
                span.set("results", 0)
                return []

            # Focus on posts with active discussion first (most comments), so
            # older high-engagement threads stay on the radar. Bound the pool so
            # the per-candidate comment scoring keeps the API GET count sane.
            # v5.2: pool de hasta 30 posts (fetch_my_posts default 30) — los
            # posts 11+ ya no quedan sin revisar para siempre.
            posts = sorted(
                posts,
                key=lambda p: int(p.get("comment_count") or p.get("comments_count") or 0),
                reverse=True,
            )[:_OWN_POST_REPLY_SCORE_LIMIT]

            # ── Cola global de comentarios sin responder (v5.2+) ──
            # Procesar post-por-post (6 × cap 10) hacía que un comentario nuevo
            # esperara detrás de comentarios viejos de otros posts. Ahora UNA
            # cola de TODOS los posts, ordenada: 1º autores watchlist, 2º
            # recencia del comentario desc. Se procesan los primeros
            # own_queue_per_cycle, con cap por post secundario.
            # v5.4: el presupuesto es techo, no cuota — un comentario debe
            # superar un piso de valor (AGENT_MIN_REPLY_VALUE_SCORE) para
            # entrar, independiente de cuantos slots queden libres.
            try:
                from services.roi_auto_tune import get_min_value
                # El .env explicito manda; si no, el auto-tune ajusta el piso
                # de valor segun el retorno real de los scores bajos.
                min_value = get_min_value(default_min=0.0)
            except (TypeError, ValueError, ImportError):
                min_value = 0.0
            queue: List[Tuple[str, Dict[str, Any], List[Dict[str, Any]]]] = []
            posts_with_pending = 0
            total_candidates = 0
            queue_scores: List[float] = []
            for post in posts:
                post_id = post.get("id") or post.get("post_id")
                if not post_id:
                    logger.warning(f"Phase B: skipping post without id: {post}")
                    continue
                post_text = " ".join([
                    str(post.get("title") or "").strip(),
                    str(post.get("content") or post.get("body") or post.get("text") or "").strip(),
                ]).strip()
                try:
                    all_comments = self.api.fetch_post_comments(post_id)
                except Exception as e:
                    logger.warning(f"Phase B: error fetching comments for post {post_id}: {e}")
                    continue
                per_post = 0
                queue_filter_counts: Dict[str, int] = {}
                # Cap propio del post (max_comments_per_post, mismo contador
                # que el safety net): se chequea ANTES de generar, no al publicar.
                _post_reply_count = self._get_agent_reply_count_in_post(post_id)
                _post_cap = self.max_comments_per_post if len(post_id) > 10 else None
                for c in all_comments:
                    if self._is_own_author(self._get_author_name(c)):
                        continue
                    # Pre-filtro: descartar sin id / vacios / borrados / ya
                    # respondidos / unrepliable / post con cap agotado ANTES
                    # de generar (ahorra LLM).
                    queuable, reason = PhaseB._comment_queuable(
                        c, post_id, post_cap=_post_cap, post_count=_post_reply_count,
                    )
                    if not queuable:
                        queue_filter_counts[reason] = queue_filter_counts.get(reason, 0) + 1
                        continue
                    # ── Cooldown anti-zombie (v5.5+): candidato que ya falló el
                    # decisor en un ciclo reciente no se re-evalúa hasta que
                    # expire el TTL — evita el bucle de un comentario muerto
                    # consumiendo slots/LLM ciclo tras ciclo. ──
                    _cid = c.get("id") or c.get("comment_id")
                    _cd_key = f"{post_id}:{_cid}"
                    if _cd_key in self._own_queue_skip_cooldown and \
                            datetime.now(timezone.utc) < self._own_queue_skip_cooldown[_cd_key]:
                        queue_filter_counts["cooldown"] = queue_filter_counts.get("cooldown", 0) + 1
                        continue
                    self._own_queue_skip_cooldown.pop(_cd_key, None)
                    # ── Score de valor: se mide SIEMPRE (telemetria de la
                    # distribucion para calibrar el umbral con datos); el
                    # filtro solo aplica si el umbral esta seteado. ──
                    try:
                        value_score = compute_dual_score(
                            (c.get("content") or c.get("text") or "")
                        )["research_value_score"]
                    except Exception:
                        value_score = 0.0
                    queue_scores.append(value_score)
                    if min_value > 0:
                        total_candidates += 1
                        author_key = (self._get_author_name(c) or "").strip().lower()
                        is_wl = self._is_watchlist_author(author_key)
                        interaction_count = 0
                        if author_key:
                            try:
                                from services.interlocutors import get_interaction_count
                                interaction_count = get_interaction_count(author_key)
                            except Exception:
                                pass
                        has_history = interaction_count >= 3
                        if is_wl or has_history:
                            floor = min_value * 0.5
                        elif interaction_count == 0:
                            # ── Enganche temprano: primera interaccion de un
                            # autor sin historial → piso rebajado UNA vez (el
                            # momento del enganche no debe morir en el umbral).
                            # Solo si el comentario no es basura clasificable.
                            try:
                                _skip_triage, _triage_reason = _triage_comment_value(
                                    (c.get("content") or c.get("text") or ""),
                                    tech_keywords=self._TECH_KEYWORDS,
                                    author=c.get("author"),
                                )
                            except Exception:
                                _skip_triage, _triage_reason = True, "triage_error"
                            if _skip_triage:
                                floor = min_value
                                queue_filter_counts["first_interaction_triage"] = (
                                    queue_filter_counts.get("first_interaction_triage", 0) + 1
                                )
                            else:
                                floor = min_value * 0.5
                        else:
                            floor = min_value
                        if value_score < floor:
                            queue_filter_counts["below_value"] = queue_filter_counts.get("below_value", 0) + 1
                            continue
                    queue.append((post_id, c, all_comments, post_text))
                    per_post += 1
                if queue_filter_counts:
                    breakdown = ", ".join(f"{k}={v}" for k, v in sorted(queue_filter_counts.items()))
                    self._stats["queue_prefiltered"] = self._stats.get("queue_prefiltered", 0) + sum(queue_filter_counts.values())
                    logger.info(
                        "Phase B: own-post queue pre-filter descartó %d comentario(s) (%s) en post %s",
                        sum(queue_filter_counts.values()), breakdown, post_id,
                    )
                if per_post > 0:
                    posts_with_pending += 1

            if not queue:
                logger.info("Phase B: no hay comentarios sin responder en posts propios.")
                span.set("results", 0)
                return []

            # ── Distribucion de scores del ciclo (telemetria para calibrar
            # AGENT_MIN_REPLY_VALUE_SCORE con datos, no al voleo) ──
            if queue_scores:
                _sorted_scores = sorted(queue_scores)
                _n = len(_sorted_scores)

                def _pct(p: float) -> float:
                    return _sorted_scores[int(p * (_n - 1))]

                logger.info(
                    "own-post queue scores — min=%.3f p25=%.3f mediana=%.3f p75=%.3f max=%.3f (n=%d)",
                    _sorted_scores[0], _pct(0.25), _pct(0.5), _pct(0.75), _sorted_scores[-1], _n,
                )

            def _recency_key(c):
                ts = c.get("created_at") or c.get("createdAt") or c.get("timestamp") or ""
                if not ts:
                    return datetime.min.replace(tzinfo=timezone.utc)
                try:
                    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    return datetime.min.replace(tzinfo=timezone.utc)

            def _queue_sort_key(item):
                _pid, c, _, _ = item
                author = self._get_author_name(c)
                wl = 0 if self._is_watchlist_author(author) else 1
                # Preguntas directas (mencion a @comet o pregunta en un post
                # propio) envejecen HACIA ARRIBA: la antiguedad no las entierra.
                _text = str(c.get("content") or c.get("text") or "").lower()
                is_direct = "@comet" in _text or "?" in _text
                # Posts con notificaciones pendientes (activity_on_your_posts
                # del home dashboard) se atienden PRIMERO: es la señal de
                # que alguien comentó algo nuevo desde el último scan.
                pending = 0 if (self._pending_home_post_ids and _pid in self._pending_home_post_ids) else 1
                return (pending, 0 if is_direct else 1, wl, -_recency_key(c).timestamp())

            queue.sort(key=_queue_sort_key)

            # Cap por post (secundario): máx. max_own_comments_per_cycle por post
            per_post_count: Dict[str, int] = {}
            selected: List[Tuple[str, Dict[str, Any], List[Dict[str, Any]], str]] = []
            for item in queue:
                pid = item[0]
                if self.max_own_comments_per_cycle is not None and per_post_count.get(pid, 0) >= self.max_own_comments_per_cycle:
                    continue
                selected.append(item)
                per_post_count[pid] = per_post_count.get(pid, 0) + 1
                if self.own_queue_per_cycle is not None and len(selected) >= self.own_queue_per_cycle:
                    break

            watchlist_sel = sum(
                1 for _, c, _, _ in selected
                if self._is_watchlist_author(self._get_author_name(c))
            )
            logger.info(
                "own-post queue: %d candidatos, %d superan el umbral (piso=%.2f), procesando %d (watchlist=%d)",
                total_candidates if min_value > 0 else len(queue),
                len(queue), min_value, len(selected), watchlist_sel,
            )

            results: List[Dict[str, Any]] = []

            for post_id, comment, all_comments, post_text in selected:
                if self.max_comments_per_day is not None and self.get_comments_today() >= self.max_comments_per_day:
                    logger.info(
                        "Phase B: límite diario alcanzado (%s/%s). Deteniendo cola own posts.",
                        self.get_comments_today(), self.max_comments_per_day,
                    )
                    break
                if self.max_replies_per_cycle is not None and len(results) >= self.max_replies_per_cycle:
                    logger.info(
                        "Phase B: límite por ciclo alcanzado (%s/%s). Deteniendo cola own posts.",
                        len(results), self.max_replies_per_cycle,
                    )
                    break

                result = await self._process_own_comment(
                    post_id, comment, all_comments,
                    limit_ok=(self.max_comments_per_post is None or len(results) < self.max_comments_per_post),
                    post_text=post_text,
                )
                if result is None:
                    continue
                # Concession closures don't consume reply budget
                if result.get("status") != "closed_concession":
                    register_agent_reply(post_id)
                    results.append(result)
                    await asyncio.sleep(self.delay_between_comments)

            if not results:
                logger.info("Phase B: no se respondió a ningún comentario en posts propios.")

            span.set("results", len(results))
            return results

    def _fetch_own_posts_for_replies(
        self,
        ranked_limit: int = 50,
        fresh_limit: int = 30,
    ) -> List[Dict[str, Any]]:
        """Own posts to consider for replies: high-engagement posts first (from
        the platform API, sort=top) merged with the newest posts (durable store)
        so fresh threads are never missed before they accumulate comments."""
        merged: Dict[str, Dict[str, Any]] = {}
        try:
            resp = self.api._request(
                "GET", "/agents/me/posts", params={"limit": ranked_limit, "sort": "top"}
            )
            data = resp.get("data") or {}
            for p in data.get("posts") or data.get("items") or []:
                pid = p.get("id") or p.get("post_id")
                if pid:
                    merged[pid] = dict(p)
        except Exception as e:
            logger.warning(f"Phase B: error fetching own posts by engagement: {e}")
        try:
            for p in self.api.fetch_my_posts(limit=fresh_limit):
                pid = p.get("id") or p.get("post_id")
                if pid and pid not in merged:
                    merged[pid] = dict(p)
        except Exception as e:
            logger.warning(f"Phase B: error fetching recent own posts: {e}")
        # ── Auto-sync del registro durable (v5.5+): posts que la API reporta
        # como propios pero que no están en own_post_ids.json (p.ej. publicados
        # antes de existir el registro) se registran sin duplicar — esto evita
        # perder el own-post bypass de relevancia. La API es fuente de verdad
        # para "qué posts son míos"; el registro durable solo lo confirma. ──
        try:
            from services.own_post_store import register_post
            known = self._get_own_post_ids()
            synced = 0
            for pid in list(merged.keys()):
                if pid not in known:
                    register_post(pid)
                    known.add(pid)
                    synced += 1
            if synced:
                self._own_post_ids_cache = known
                logger.info("Phase B: auto-sync own_post_store: %d post(s) registrado(s) desde API.", synced)
        except Exception as e:
            logger.debug("Phase B: auto-sync own_post_store no disponible: %s", e)
        return list(merged.values())

    def _get_own_post_ids(self) -> Set[str]:
        """Return the set of the agent's own post IDs (from own_post_ids.json),
        cached per PhaseB instance. Used by the relevance bypass to detect
        direct replies to the agent's own posts. Loads the full registry so
        older posts (outside the recent window) still get the own-post bypass."""
        cached = getattr(self, "_own_post_ids_cache", None)
        if cached is not None:
            return cached
        ids: Set[str] = set()
        try:
            from services.own_post_store import load_all_own_post_ids
            ids = set(load_all_own_post_ids())
        except Exception as e:
            logger.debug("Phase B: could not load own_post_ids for bypass: %s", e)
        self._own_post_ids_cache = ids
        return ids

    async def _process_own_post(self, post_id: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []


        daily_comment_count = self.get_comments_today()
        if self.max_comments_per_day is not None and daily_comment_count >= self.max_comments_per_day:
            send_event("phase_b_reply_skip", {
                "post_id": post_id,
                "reason": "daily_limit",
                "score": 0,
            })
            logger.info(
                "Phase B: límite diario de comentarios alcanzado (%s/%s).",
                daily_comment_count, self.max_comments_per_day,
            )
            return []

        # Prune recorded agent comment IDs that no longer exist on the platform
        # (deleted), so they stop counting against the per-post reply cap.
        self._reconcile_deleted_agent_comments(post_id)

        try:
            comments = self.api.fetch_post_comments(post_id)
        except Exception as e:
            logger.error(f"Phase B: error fetching comments for post {post_id}: {e}")
            return []

        if not comments:
            logger.info(f"Phase B: no comments on post {post_id}")
            return []

        # Early exit: check hard cap BEFORE generating replies (saves LLM tokens)
        if len(post_id) > 10:
            current_count = self._get_agent_reply_count_in_post(post_id)
            if self.max_comments_per_post is not None and current_count >= self.max_comments_per_post:
                logger.info("Phase B: Límite de %s comentarios por post alcanzado en %s (%d/%d).",
                            self.max_comments_per_post, post_id, current_count, self.max_comments_per_post)
                return []

        # Update conversation state from latest other-agent comment
        last_other_text = ""
        for c in comments:
            author = self._get_author_name(c)
            if author and not self._is_own_author(author):
                last_other_text = c.get("content") or c.get("text") or ""
                break  # newest first (comments are usually newest-first)
        if last_other_text:
            update_open_questions(post_id, last_other_text)

        replied_count = self._get_agent_reply_count_in_post(post_id)

        # Texto del post para el gate temático (off-topic) — fail-open: sin
        # texto disponible no se filtra por tema.
        _post_text = ""
        try:
            _p = self.api.get_post(post_id)
            if isinstance(_p, dict):
                _post_text = " ".join([
                    str(_p.get("title") or "").strip(),
                    str(_p.get("content") or _p.get("body") or _p.get("text") or "").strip(),
                ]).strip()
        except Exception:
            pass

        # Rank comments by reply priority before iterating
        try:
            from phases.phase_b.candidate_scorer import rank_candidates
            _agent_claims = []
            try:
                from core.claims_tracker import ClaimsTracker
                _ct = ClaimsTracker()
                _agent_claims = [c.text for c in _ct._claims[:10]] if _ct._claims else []
            except Exception:
                pass
            ranked = rank_candidates(comments, agent_claims=_agent_claims, top_n=len(comments))
            comments = [item["comment"] for item in ranked]
        except Exception:
            pass  # Fall back to original order

        # ── Cap de trabajo por post por ciclo (v5.2+) ──────────────
        # Con el aplanado de replies, un post puede tener 300+ comentarios y
        # monopolizar el ciclo entero (85 min): feed y follow-ups sin ejecutar,
        # stop graceful mudo. Procesamos a lo sumo N comentarios "accionables"
        # por post por ciclo, priorizando autores de watchlist y luego los más
        # recientes; el resto queda pendiente y se atiende en el próximo ciclo.
        all_comments = comments
        if self.max_own_comments_per_cycle > 0 and len(comments) > self.max_own_comments_per_cycle:
            actionable = []
            for c in comments:
                if self._is_own_author(self._get_author_name(c)):
                    continue
                cid = c.get("id") or c.get("comment_id")
                if not cid:
                    continue
                if f"{post_id}:{cid}" in self._replied_comment_ids:
                    continue
                if not (c.get("content") or c.get("text") or "").strip():
                    continue
                actionable.append(c)

            def _recency_key(c):
                ts = c.get("created_at") or c.get("createdAt") or c.get("timestamp") or ""
                if not ts:
                    return datetime.min.replace(tzinfo=timezone.utc)
                try:
                    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    return datetime.min.replace(tzinfo=timezone.utc)

            watchlist_c = [c for c in actionable
                           if self._is_watchlist_author(self._get_author_name(c))]
            watchlist_ids = {id(c) for c in watchlist_c}
            others_c = [c for c in actionable if id(c) not in watchlist_ids]
            watchlist_c.sort(key=_recency_key, reverse=True)
            others_c.sort(key=_recency_key, reverse=True)
            comments = (watchlist_c + others_c)[:self.max_own_comments_per_cycle]
            logger.info(
                "Phase B: own post %s — %d accionables, procesando %d este ciclo "
                "(cap=%d, watchlist=%d primero, luego más recientes); %d quedan pendientes.",
                post_id, len(actionable), len(comments), self.max_own_comments_per_cycle,
                len(watchlist_c), len(actionable) - len(comments),
            )

        for comment in comments:
            # ── Per-post limit (propios): máx. max_comments_per_post replies del agente en este post ──
            if self.max_comments_per_post is not None and replied_count >= self.max_comments_per_post:
                send_event("phase_b_reply_skip", {
                    "post_id": post_id,
                    "reason": "per_post_limit",
                    "score": 0,
                })
                logger.info(
                    "Phase B: reached max_comments_per_post=%s for post %s",
                    self.max_comments_per_post,
                    post_id,
                )
                break

            result = await self._process_own_comment(
                post_id, comment, all_comments,
                limit_ok=(self.max_comments_per_post is None or replied_count < self.max_comments_per_post),
                post_text=_post_text,
            )
            if result is None:
                continue

            # ── Re-check daily/cycle budget after each own-post reply (feed may still have margin) ──
            daily_comment_count = self.get_comments_today()
            if self.max_comments_per_day is not None and daily_comment_count >= self.max_comments_per_day:
                send_event("phase_b_reply_skip", {
                    "post_id": post_id,
                    "reason": "daily_limit",
                    "score": 0,
                })
                logger.info(
                    "Phase B: límite diario de comentarios alcanzado (%s/%s). Deteniendo own post replies.",
                    daily_comment_count, self.max_comments_per_day,
                )
                break
            if self.max_replies_per_cycle is not None and replied_count >= self.max_replies_per_cycle:
                send_event("phase_b_reply_skip", {
                    "post_id": post_id,
                    "reason": "per_cycle_limit",
                    "score": 0,
                })
                logger.info(
                    "Phase B: límite por ciclo alcanzado (%s/%s). Deteniendo own post replies.",
                    replied_count, self.max_replies_per_cycle,
                )
                break
            # Concession closures don't consume reply budget
            if result.get("status") != "closed_concession":
                replied_count += 1
            register_agent_reply(post_id)
            results.append(result)
            await asyncio.sleep(self.delay_between_comments)

        # Debate continuation: if thread still has open questions and caps allow, reply again
        if can_continue_thread(post_id):
            if (self.max_comments_per_post is None or replied_count < self.max_comments_per_post) and (self.max_replies_per_cycle is None or replied_count < self.max_replies_per_cycle):
                latest_other = None
                # Solo dentro de los comentarios procesados EN ESTE CICLO
                # (comments está recortado por el cap): el debate continuation
                # no puede saltarse el cap eligiendo del backlog (all_comments).
                for c in comments:
                    author = self._get_author_name(c)
                    if author and not self._is_own_author(author):
                        latest_other = c
                        break
                if latest_other:
                    other_id = latest_other.get("id") or latest_other.get("comment_id")
                    other_text = latest_other.get("content") or latest_other.get("text") or ""
                    other_author = self._get_author_name(latest_other) or "usuario"
                    if other_id and other_text.strip():
                        dedup_key = f"{post_id}:{other_id}"
                        # VERIFICACIÓN ESTRICTA: Si ya respondimos a este comment_id exacto, saltar.
                        if dedup_key in self._replied_comment_ids or self._dedup.has_replied(dedup_key):
                            logger.info("Phase B: debate continuation: comment %s on post %s already replied (strict dedup), skipping.", other_id, post_id)
                        elif self.max_comments_per_day is None or self.get_comments_today() < self.max_comments_per_day:
                            # VERIFICACIÓN SEMÁNTICA: Buscar si el agente ya respondió algo muy parecido en este hilo
                            agent_replies_in_thread = [
                                c.get("content") or c.get("text") or "" 
                                for c in all_comments 
                                if self._is_own_author(self._get_author_name(c))
                            ]
                            proposed_reply = await self._generate_own_post_reply(other_author, other_text, self._build_thread_history(latest_other, all_comments))
                            if proposed_reply and not any(is_semantic_duplicate_reply(proposed_reply, prev) for prev in agent_replies_in_thread):
                                result = await self._post_own_reply(post_id, other_id, other_author, other_text)
                                if result:
                                    replied_count += 1
                                    register_agent_reply(post_id)
                                    results.append(result)
                            else:
                                logger.info("Phase B: debate continuation: proposed reply is semantic duplicate or empty, closing thread %s.", post_id)
                                close_thread(post_id)

        if not results:
            logger.info("Phase B: no se respondió a ningún comentario en posts propios.")

        return results

    async def _process_own_comment(
        self,
        post_id: str,
        comment: Dict[str, Any],
        all_comments: List[Dict[str, Any]],
        limit_ok: bool = True,
        post_text: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Procesa UN comentario de un post propio: guards, decisión y publicación.

        Es el cuerpo del loop de _process_own_post extraído a método, usado
        también por la cola global (_execute_own_post_replies). Devuelve el
        result dict si se respondió/publicó, None si el comentario se saltea
        por cualquier gate (own, dedup, profundidad, triage, generación).

        El presupuesto (daily/cycle/per-post) lo gestiona el caller, no este
        método: la cola global lo controla por ciclo completo.
        """
        comment_id = comment.get("id") or comment.get("comment_id")
        comment_text = comment.get("content") or comment.get("text") or ""
        author = self._get_author_name(comment) or "usuario"

        # ── Inbound watchlist tracking: un referente comento en NUESTRO post ──
        if self._is_watchlist_author(author):
            self.record_watchlist_inbound(author, comment_id=str(comment_id or ""))

        if not comment_id:
            logger.warning(f"Phase B: comment without id on post {post_id}, skipping")
            return None
        # Fix 3: ignorar los propios replies del agente en el hilo
        _own = self._get_author_name(comment)
        if self._is_own_author(_own):
            logger.debug("Phase B: skip own comment %s on post %s", comment_id, post_id)
            return None

        # ── Thread depth guard ─────────────────────────────────
        parent_id = PhaseB._extract_parent_id(comment)
        if parent_id and parent_id in self._agent_comment_ids.get(post_id, []):
            depth = self._compute_thread_depth(comment, all_comments)
            # Limite fijo de interacciones por hilo (politica vigente):
            # maximo 4 niveles de conversacion, luego el tema queda cerrado.
            _max_depth = 4
            if depth >= _max_depth:
                logger.info(
                    "Profundidad máxima alcanzada, salteando hilo "
                    "(post_id=%s, comment_id=%s, profundidad=%s, max=%s)",
                    post_id, comment_id, depth, _max_depth,
                )
                return None

        dedup_key = f"{post_id}:{comment_id}"
        if dedup_key in self._replied_comment_ids:
            logger.info("Phase B: skip comment %s on post %s (already replied).", comment_id, post_id)
            return None
        if not comment_text.strip():
            logger.info(f"Phase B: empty comment {comment_id} on post {post_id}, skipping")
            return None
        # ── Own-post reply detection for relevance bypass ──
        own_post_ids = self._get_own_post_ids()
        is_own_post_reply = (
            str(post_id) in own_post_ids
            or (parent_id is not None and str(parent_id) in own_post_ids)
        )
        # ── Ledger: observación del comentario dirigido a nosotros ──
        from services import interlocutors
        interlocutors.record_interaction(
            comment.get("author"), on_our_post=True,
        )
        decision = self._decide_reply(
            comment,
            limit_ok=limit_ok,
            is_own_post_reply=is_own_post_reply,
            post_text=post_text,
        )
        if not decision.should_reply:
            # ── Anti-zombie (v5.5+): un rechazo definitivo (no de presupuesto)
            # pone al candidato en cooldown 30 min para que no re-entre a la
            # cola en cada ciclo hasta que expire el TTL. ──
            if decision.reason not in ("reply_skipped_limit_reached",):
                self._own_queue_skip_cooldown[f"{post_id}:{comment_id}"] = (
                    datetime.now(timezone.utc) + timedelta(minutes=30)
                )
            send_event("phase_b_reply_skip", {
                "post_id": post_id,
                "comment_id": comment_id,
                "reason": decision.reason,
                "score": decision.score,
                "snippet": comment_text[:60],
            })
            return None

        _value_cls = self._classify_comment_value(comment_text)
        self._stats["passed_value"] += 1

        # ── Build thread history for conversational context ──
        thread_history = ""
        if parent_id:
            thread_history = self._build_thread_history(comment, all_comments)

        result = await self._post_own_reply(post_id, comment_id, author, comment_text, thread_history)
        if result is None:
            return None

        # ── Strategic follow: follow agents who engage in genuine debate on our posts ──
        if author and not self._is_own_author(author) and _value_cls not in ("general",):
            self._maybe_follow_author(author)

        return result

    async def _post_own_reply(self, post_id: str, comment_id: str, author: str,
                              comment_text: str, thread_history: str = "") -> Optional[Dict[str, Any]]:
        """Generate and post a reply to a comment on our own post. Returns result dict or None on failure."""
        with Span("write_comment", post_id=str(post_id)) as span:
            comment_lower = comment_text.lower()
            # ── Durable cross-session dedup: never reply to the same comment_id twice ──
            if reply_cap.has_replied_to_comment(f"{post_id}:{comment_id}"):
                logger.info("Phase B: skip reply to comment %s on post %s (durable dedup).", comment_id, post_id)
                span.set("success", False)
                return None
            concession_keywords = [
                "makes sense", "good point", "i agree", "you're right",
                "fair enough", "that is true", "you are right",
                "thanks for sharing", "how often do you face this",
                "great point", "interesting point", "well said",
            ]
            _is_concession = self._is_concession(comment_lower)
            _synthesis_mode = False
            if _is_concession:
                if post_id in self._concession_answered:
                    close_thread(post_id)
                    logger.info("Phase B: thread close: let_stand (post %s, interlocutor conceded de nuevo)", post_id)
                    return {"post_id": post_id, "comment_id": comment_id, "status": "closed_concession"}
                # Primera concesion: como maximo UNA respuesta, de SINTESIS
                # (el prompt recibe la directiva; no se agrega otra correccion).
                _synthesis_mode = True

            dedup_key = f"{post_id}:{comment_id}"
            if dedup_key in self._replied_comment_ids:
                logger.info("Phase B: skip reply to comment %s on post %s (already replied, dedup).", comment_id, post_id)
                send_event("phase_b_duplicate_skip", {
                    "post_id": post_id,
                    "comment_id": comment_id,
                    "reason": "already_replied_comment_id",
                })
                span.set("success", False)
                return None

            try:
                reply_text = await self._generate_own_post_reply(author, comment_text, thread_history, post_id=post_id, concession_synthesis=_synthesis_mode)
                # CAPTURAR COSTOS: acceder a _last_usage del cascade después de generación exitosa
                _cascade = self.llm
                _provider_name = "tier_fallback"  # default para Phase B
                _usage = _cascade._last_usage.get(_provider_name, {}) or {}
                _input_tokens = int(_usage.get("input_tokens", 0) or 0)
                _output_tokens = int(_usage.get("output_tokens", 0) or 0)
                from services.model_cascade import _estimate_cost_usd
                _cost_usd = _estimate_cost_usd(_provider_name, _input_tokens, _output_tokens)
                # Crear comment_metadata con costos
                comment_metadata = {
                    "input_tokens": _input_tokens,
                    "output_tokens": _output_tokens,
                    "total_cost_usd": _cost_usd
                }
                logger.info("Phase B: costos capturados - input=%s, output=%s, cost=$%.6f", _input_tokens, _output_tokens, _cost_usd)
            except Exception as e:
                logger.error(f"Phase B: LLM error for comment {comment_id} on post {post_id}: {e}")
                span.set("success", False)
                return None

            # ABSTAIN: salida legitima — no publicar, no cuenta como fallo.
            if (reply_text or "").upper().startswith("ABSTAIN"):
                logger.info("Phase B: own-post reply ABSTAIN (comment %s)", comment_id)
                span.set("success", False)
                return {"post_id": post_id, "comment_id": comment_id, "abstained": True}

            # Sintesis post-concesion sin insight unificador (CLOSE): no
            # publicar — el ultimo punto queda parado.
            if _synthesis_mode and (reply_text or "").strip().upper().startswith("CLOSE"):
                close_thread(post_id)
                logger.info("Phase B: thread close: let_stand (post %s, sin sintesis genuina)", post_id)
                span.set("success", False)
                return {"post_id": post_id, "comment_id": comment_id, "status": "closed_concession"}

            if not reply_text:
                span.set("success", False)
                return None

            reply_text = clean_llm_output(reply_text)

            reply_text = await self._check_and_prevent_duplicate(post_id, reply_text)
            if reply_text is None:
                span.set("success", False)
                return None

            if len(reply_text.strip()) < 30 or is_likely_truncated(reply_text):
                logger.info("Phase B: skip own reply — too short or truncated (len=%d)", len(reply_text.strip()))
                span.set("success", False)
                return None

            result = self._safe_publish_comment(
                post_id=post_id,
                parent_comment_id=comment_id,
                content=reply_text,
                skip_anti_dogpile=True,
                require_evidence=self._is_watchlist_author(author),
            )
            if result is None:
                span.set("success", False)
                return None

            success = result.get("success", False) if isinstance(result, dict) else getattr(result, "success", False)
            already_existed = result.get("already_existed", False) if isinstance(result, dict) else getattr(result, "already_existed", False)
            error = result.get("error") if isinstance(result, dict) else getattr(result, "error", None)
            own_comment_id = result.get("id")
            # Trackear en karma ROI tracker
            try:
                from services.karma_roi_tracker import track_action
                cost_usd = comment_metadata.get("total_cost_usd", 0.0) if 'comment_metadata' in locals() else 0.0
                input_tokens = comment_metadata.get("input_tokens", 0) if 'comment_metadata' in locals() else 0
                output_tokens = comment_metadata.get("output_tokens", 0) if 'comment_metadata' in locals() else 0
                track_action(
                    action_type="comment",
                    moltbook_id=comment_id,
                    phase="B",
                    cost_usd=cost_usd,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    model="deepseek-v4-pro",
                    thread_id=post_id if 'post_id' in locals() else None,
                    author=post_author if 'post_author' in locals() else None
                )
                logger.info("Karma ROI: Comment %s trackeado (costo: $%.6f)", comment_id[:8], cost_usd)
            except Exception as e:
                logger.warning("Karma ROI: Error trackeando comment %s: %s", comment_id[:8], e)

            if success and already_existed:
                logger.info(
                    "Phase B: reply to comment %s on post %s already existed (dedup), not counting.",
                    comment_id, post_id,
                )
                self.incr_comments_today()
                span.set("success", True)
                return {
                    "post_id": post_id,
                    "comment_id": comment_id,
                    "content": reply_text,
                    "success": True,
                    "already_existed": True,
                    "error": error,
                }

            if success:
                self._replied_comment_ids.add(dedup_key)
                self._dedup.mark_replied(dedup_key)
                reply_cap.mark_replied_to_comment(f"{post_id}:{comment_id}")
                # Sintesis post-concesion publicada: si el otro vuelve a
                # conceder, el hilo se cierra (no se sigue discutiendo).
                if _synthesis_mode:
                    self._concession_answered.add(post_id)
                # ── Ledger de retorno: registrar el comentario publicado con
                # su score de valor y el motivo de entrada para medir que
                # canal produce upvotes ──
                try:
                    from services.comment_votes import record_published_comment
                    record_published_comment(
                        post_id, str(own_comment_id or ""),
                        compute_dual_score(reply_text)["research_value_score"],
                        reason=self._comment_entry_reason(author),
                    )
                except Exception as e:
                    logger.debug("Phase B: comment_votes record failed: %s", e)
                # ── Ledger: respuesta (segundo registro del comentario) ──
                from services import interlocutors as _il
                _il.record_interaction(
                    author, on_our_post=True,
                )
                self.incr_comments_today()
                send_event("phase_b_reply_success", {
                    "post_id": post_id,
                    "comment_id": comment_id,
                })
                try:
                    update_today_metrics(comments_published=1)
                except Exception as e:
                    logger.warning(f"SelfEval: error registrando comments_published=1: {e}")

                own_post_text = f"Post ID: {post_id}"
                await self._classify_and_log_value(
                    {"id": post_id, "title": "", "content": own_post_text},
                    comment_text, reply_text, str(comment_id),
                    comment_author=author,
                )
                logger.info(
                    "Phase B: replied to comment %s on post %s",
                    comment_id, post_id,
                )
                if own_comment_id:
                    if post_id not in self._agent_comment_ids:
                        self._agent_comment_ids[post_id] = []
                    self._agent_comment_ids[post_id].append(str(own_comment_id))
                    self._dedup.sync_agent_comment_ids(self._agent_comment_ids)
                # ── Write long-term memory ─────────────────────────
                try:
                    summary = (
                        f"Usuario dijo: {comment_text[:150]} | "
                        f"Agente respondió: {reply_text[:150]}"
                    )
                    self._memory.update_memory(author, author, summary)
                except Exception:
                    pass
                span.set("success", True)
                return {
                    "post_id": post_id,
                    "comment_id": comment_id,
                    "content": reply_text,
                    "success": True,
                    "already_existed": False,
                    "error": error,
                }

            # HTTP 2xx but success=False (e.g. verification challenge not confirmed)
            # → the comment WAS created on the server.  Do NOT enqueue to outbox
            # (retry would create a duplicate).  Register the dedup key and return
            # a qualified-success result to prevent Phase B from re-replying later.
            status = result.get("status", 0) if isinstance(result, dict) else 0
            if 200 <= status < 300:
                self._replied_comment_ids.add(dedup_key)
                self._dedup.mark_replied(dedup_key)
                reply_cap.mark_replied_to_comment(f"{post_id}:{comment_id}")
                logger.warning(
                    "Phase B: reply to comment %s on post %s returned HTTP %s "
                    "with unverified state (id=%s); comment is on the server, "
                    "not retrying to avoid duplicate.",
                    comment_id, post_id, status, own_comment_id or "unknown",
                )
                span.set("success", True)
                return {
                    "post_id": post_id,
                    "comment_id": comment_id,
                    "content": reply_text,
                    "success": True,
                    "already_existed": False,
                    "error": error,
                }

            # 404 "Parent comment not found": el padre fue borrado y NUNCA va a
            # volver. Marcar el comentario como unrepliable (no vuelve a la cola,
            # no se regenera) y NO encolar al outbox: reintentar es quemar LLM.
            if is_parent_not_found_404(result):
                reply_cap.mark_unrepliable_comment(f"{post_id}:{comment_id}")
                logger.warning(
                    "Phase B: comment %s on post %s unrepliable (parent 404) — "
                    "marcado, sin outbox.",
                    comment_id, post_id,
                )
                span.set("success", False)
                return {
                    "post_id": post_id,
                    "comment_id": comment_id,
                    "content": reply_text,
                    "success": False,
                    "already_existed": False,
                    "error": error,
                    "unrepliable": True,
                }

            logger.warning(
                "Phase B: failed to reply to comment %s on post %s: %s",
                comment_id, post_id, error,
            )
            enqueue_outbox("comment", {"post_id": post_id, "content": reply_text, "parent_comment_id": comment_id})
            span.set("success", False)
            return {
                "post_id": post_id,
                "comment_id": comment_id,
                "content": reply_text,
                "success": False,
                "already_existed": False,
                "error": error,
            }

    @staticmethod
    def _get_author_name(comment: Dict[str, Any]) -> str:
        author = comment.get("author")
        if isinstance(author, dict):
            return author.get("name") or author.get("username") or ""
        if isinstance(author, str):
            return author
        return ""

    # ── Pre-filtro de cola (no generar respuestas que no se pueden publicar) ──

    _DELETED_CONTENT_MARKERS = (
        "[deleted]", "[removed]", "deleted comment", "comment removed",
        "message deleted", "this comment was deleted",
    )

    @classmethod
    def _comment_is_deleted(cls, comment: Any) -> bool:
        """True si el comentario fue borrado/removido (flag o marcador de texto)."""
        if not isinstance(comment, dict):
            return False
        for flag in ("deleted", "is_deleted", "removed", "is_removed"):
            if comment.get(flag) is True:
                return True
        text = (comment.get("content") or comment.get("text") or "").lower()
        return any(marker in text for marker in cls._DELETED_CONTENT_MARKERS)

    @staticmethod
    def _is_direct_question(text: str) -> bool:
        """Pregunta dirigida a COMET: mencion a @comet o pregunta ('?') en un
        post propio. Se usa para priorizar y para no cerrar hilos con
        preguntas pendientes."""
        if not text:
            return False
        low = text.lower()
        return "@comet" in low or "?" in low

    @staticmethod
    def _is_concession(text: str) -> bool:
        """True si el mensaje del otro concede (acepta la correccion)."""
        if not text:
            return False
        lower = text.lower()
        return any(marker in lower for marker in _CONCESSION_MARKERS) or bool(
            _CONCESSION_WORD_RE.search(lower)
        )

    @staticmethod
    def _is_promotional_content(text: str) -> bool:
        """True si el contenido es promocion comercial: comandos de instalacion
        (pip/npm/openclaw install, echo >> .env) — publicidad, no discusion."""
        if not text:
            return False
        return bool(_PROMO_INSTALL_RE.search(text) or _PROMO_ENV_APPEND_RE.search(text))

    @classmethod
    def _comment_queuable(cls, comment: Any, post_id: str = "",
                          post_cap: Optional[int] = None,
                          post_count: Optional[int] = None) -> tuple[bool, str]:
        """Pre-filtro de la cola: descarta comentarios que nunca se podran
        responder — sin id, sin contenido, borrados, ya respondidos /
        unrepliable (padre borrado), o en un post que agoto su cap propio
        (max_comments_per_post, mismo contador que el safety net).
        Devuelve (queuable, reason) para poder contar cuantos se filtran
        por ciclo y por motivo."""
        if not isinstance(comment, dict):
            return False, "not_dict"
        cid = comment.get("id") or comment.get("comment_id")
        if not cid:
            return False, "no_id"
        text = (comment.get("content") or comment.get("text") or "").strip()
        if not text:
            return False, "empty_content"
        if cls._comment_is_deleted(comment):
            return False, "deleted"
        if cls._is_promotional_content(text):
            return False, "promotional"
        if post_id:
            if post_cap is not None and post_count is not None and post_count >= post_cap:
                return False, "post_cap_reached"
            key = f"{post_id}:{cid}"
            if reply_cap.has_replied_to_comment(key):
                return False, "already_replied"
            if reply_cap.is_unrepliable_comment(key):
                return False, "unrepliable"
        return True, ""

    # ── Watchlist helpers ──────────────────────────────────────────

    @staticmethod
    def _load_watchlist_authors() -> Set[str]:
        try:
            import yaml
            strategy_file = BASE_DIR / "config/phase_b_strategy.yaml"
            if strategy_file.exists():
                strategy = yaml.safe_load(strategy_file.read_text(encoding="utf-8")) or {}
                authors = strategy.get("watchlist_authors") or []
                return {str(a).strip().lower() for a in authors if a}
        except Exception:
            pass
        return set()

    def _load_watchlist_count(self) -> None:
        try:
            if self._watchlist_count_path.exists():
                data = json.loads(self._watchlist_count_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    today = datetime.now(timezone.utc).date().isoformat()
                    if data.get("date") == today:
                        self._watchlist_author_count_today = data.get("counts", {})
        except Exception:
            self._watchlist_author_count_today = {}

    def _save_watchlist_count(self) -> None:
        try:
            self._watchlist_count_path.parent.mkdir(parents=True, exist_ok=True)
            today = datetime.now(timezone.utc).date().isoformat()
            self._watchlist_count_path.write_text(
                json.dumps({"date": today, "counts": self._watchlist_author_count_today}),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _watchlist_author_at_cap(self, author: str) -> bool:
        """Predicado puro: True si el autor watchlist ya está en el cap diario.

        Sin side effects (no incrementa). Usado por el filtro del pool de
        feed para excluir posts de watchlist capped ANTES del truncado a
        12 (fix anti-estrella 24/08/2026).
        """
        if not author:
            return False
        key = author.strip().lower()
        current = self._watchlist_author_count_today.get(key, 0)
        return current >= self._watchlist_max_per_author_day

    def _check_increment_watchlist_cap(self, author: str, is_own_post: bool = False) -> bool:
        """Return True if author can be replied to (under daily cap).
        Inbound en posts propios de watchlist tiene prioridad - no bloquear por cap."""
        author_key = author.strip().lower()
        current = self._watchlist_author_count_today.get(author_key, 0)
        # Inbound de watchlist en posts propios NO se bloquea por cap
        if is_own_post:
            return True
        if current >= self._watchlist_max_per_author_day:
            return False
        self._watchlist_author_count_today[author_key] = current + 1
        self._save_watchlist_count()
        return True

    def _comment_entry_reason(self, author: str) -> str:
        """Motivo por el que un comentario entro a la cola (para el ledger de
        retorno): watchlist / historial (>=3) / primera_interaccion / valor."""
        author_key = (author or "").strip().lower()
        if self._is_watchlist_author(author_key):
            return "watchlist"
        count = 0
        if author_key:
            try:
                from services.interlocutors import get_interaction_count
                count = get_interaction_count(author_key)
            except Exception:
                pass
        if count >= 3:
            return "historial"
        if count == 0:
            return "primera_interaccion"
        return "valor"

    def _should_critique(self, tier: str, author: str) -> bool:
        """Decide si un reply pasa por writer + critic.

        Regla data-driven (v5.9): la critica siempre para tier_quality
        (watchlist) y, ademas, para cualquier canal cuyo retorno real medido
        (upvotes/comentario del ledger) supere el umbral con muestra minima.
        Asi el override pasa de regla estatica a decision basada en datos.
        Cachea el ROI por ciclo (no relee el ledger por cada reply)."""
        if tier == "quality":
            return True
        try:
            reason = self._comment_entry_reason(author)
            if reason == "watchlist":
                return True
            from services.roi_auto_tune import channels_with_roi, CRITIQUE_CHANNEL_ROI_MIN
            if self._roi_channels_cache is None:
                self._roi_channels_cache = channels_with_roi()
            roi = self._roi_channels_cache.get(reason)
            if roi is not None and roi >= CRITIQUE_CHANNEL_ROI_MIN:
                return True
        except Exception:
            return False
        return False

    def _is_watchlist_author(self, author: str) -> bool:
        return author.strip().lower() in self._watchlist_authors

    # ── Inbound watchlist tracking (calibracion) ─────────────────
    # Cuenta cuantos autores de la watchlist comentan en POSTS DE COMET.
    # Objetivo: >0/dia (hoy solo ocurre con authors explicitamente). Es la
    # metrica de exito del post-pairing; si crece, el engagement reciproco
    # esta funcionando.
    def record_watchlist_inbound(self, author: str, comment_id: str = "") -> None:
        try:
            _path = BASE_DIR / "data" / "watchlist_inbound_today.json"
            today = datetime.now(timezone.utc).date().isoformat()
            if _path.exists():
                data = json.loads(_path.read_text(encoding="utf-8"))
            else:
                data = {}
            if data.get("date") != today:
                data = {"date": today, "counts": {}}
            key = author.strip().lower()
            # Dedup: un mismo comment_id NO cuenta dos veces aunque el post se
            # re-escanee en multiples ciclos (evita inflar el inbound por re-scan).
            seen = data.setdefault("_seen", [])
            if comment_id and comment_id in seen:
                return
            if comment_id:
                seen.append(comment_id)
                seen[:] = seen[-2000:]  # cota el historial diario
            data["counts"][key] = int(data["counts"].get(key, 0)) + 1
            _path.write_text(json.dumps(data), encoding="utf-8")
        except Exception as e:
            logger.debug("record_watchlist_inbound failed: %s", e)

    def get_watchlist_inbound_today(self) -> int:
        try:
            _path = BASE_DIR / "data" / "watchlist_inbound_today.json"
            if _path.exists():
                data = json.loads(_path.read_text(encoding="utf-8"))
                today = datetime.now(timezone.utc).date().isoformat()
                if data.get("date") == today:
                    counts = data.get("counts", {})
                    return sum(int(v) for v in counts.values())
        except Exception:
            pass
        return 0


    # ── Research agenda helpers ───────────────────────────────────

    def _add_topic_to_agenda(self, post: Dict[str, Any], post_body: str) -> None:
        from .value_log_utils import _add_topic_to_agenda
        _add_topic_to_agenda(self, post, post_body)

    def _build_thread_history(self, comment: Dict, all_comments: List[Dict]) -> str:
        from .value_log_utils import _build_thread_history
        return _build_thread_history(self, comment, all_comments)

    async def _generate_own_post_reply(self, author: str, comment_text: str, thread_history: str = "",
                                       tier: str = "flash", post_id: str = "",
                                       concession_synthesis: bool = False) -> str:
        with Span("llm_generation", type="own_post") as span:
            lang_instruction = (
                "Always respond in English. This is an English-speaking platform."
            )

            # ── Memory context ─────────────────────────────────────
            memory_note = ""
            try:
                mem = self._memory.get_memory(author)
                if mem:
                    memory_note = (
                        f"COGNITIVE CONTEXT: You have debated with @{mem['username']} before. "
                        f"Previous context: {mem['summary']}. "
                        f"Acknowledge this continuity naturally if relevant, without repeating your past arguments.\n\n"
                    )
            except Exception:
                pass

            # ── Claims Tracker context ────────────────────────────
            _claims_tracker = None
            _claims_cluster = "infrastructure"
            try:
                _claims_tracker = ClaimsTracker(Path.cwd())
                _claims_cluster = _detect_cluster(f"{comment_text} {thread_history}")
                # ── Energy-tech keyword override for ClaimsTracker ──
                _tech_keywords_map = {
                    "battery": "solid-state-battery", "batería": "solid-state-battery",
                    "hidrógeno": "green-hydrogen", "hydrogen": "green-hydrogen",
                    "solar": "perovskite-solar", "perovskite": "perovskite-solar",
                    "agrivoltaic": "agrivoltaics", "agripv": "agrivoltaics",
                    "sodium": "sodium-ion", "na-ion": "sodium-ion",
                    "electrólisis": "green-hydrogen", "electrolysis": "green-hydrogen",
                }
                _post_text = f"{comment_text} {thread_history}".lower()
                for _kw, _cluster in _tech_keywords_map.items():
                    if _kw in _post_text:
                        _claims_cluster = _cluster
                        break
                _claims_context = _claims_tracker.get_context_for_reply(_claims_cluster)
                _depth_directive = get_reply_depth_directive()
                # ── Communication mode (voice) ────────────────────
                _self_diag = getattr(self, "self_diagnosis", None)
                _mode_name = select_mode(_self_diag, {"topic_cluster": _claims_cluster})
                _mode_prompt = get_mode_prompt(_mode_name)
            except Exception:
                _claims_context = ""
                _depth_directive = ""
                _mode_prompt = ""

            # ── Deteccion de prompt injection (telemetria, no bloqueo) ──
            try:
                _inj_fragment = detect_prompt_injection(f"{comment_text} {thread_history}")
                if _inj_fragment:
                    logger.warning("prompt injection attempt from %s (post %s)", author, post_id)
                    log_injection_attempt(
                        author=author,
                        post_id=str(post_id or ""),
                        source="own_post_reply",
                        fragment=_inj_fragment,
                    )
            except Exception:
                pass

            if thread_history:
                user_prompt = memory_note + DEBATE_CONTINUATION_TEMPLATE.format(
                    thread_history=thread_history,
                    author=author,
                    comment_text=comment_text,
                    min=80,
                    max=400
                )
            else:
                user_prompt = memory_note + REPLY_TEMPLATE.format(
                    title="Own Post",
                    content=comment_text,
                    min=80,
                    max=400
                )

            injection_lines = []
            if _claims_context:
                injection_lines.append(_claims_context)
            if _mode_prompt:
                injection_lines.append(_mode_prompt)
            if _depth_directive:
                injection_lines.append(_depth_directive)
            # ── Active RAG — EIN context ──────────────────────────
            _ein_context = _get_ein_context(f"{comment_text} {thread_history}")
            if _ein_context:
                injection_lines.append(_ein_context)
                logger.info("Phase B: Injected EIN context into own-post reply prompt")
            if injection_lines:
                user_prompt = user_prompt + "\n\n" + "\n\n".join(injection_lines)

            # ── Sintesis post-concesion: el otro ya acepto, no corregir de nuevo.
            # Cierre solo si hay insight que unifica; si no, CLOSE (let_stand). ──
            if concession_synthesis:
                user_prompt = user_prompt + (
                    "\n\nThey agreed. Do not add another correction. Close only "
                    "if you can add a unifying insight neither side stated. "
                    "Otherwise output CLOSE."
                )

            system_prompt = (
                "You are a senior systems engineer. "
                "Reply concisely and helpfully. "
                "Do not use emojis, hashtags, or markdown.\n\n"
                "Prefer replies that anchor to a specific claim in the comment.\n"
                "Avoid generic normative phrasing such as 'A practical guardrail is' or 'The trade-off is'.\n"
                "Avoid exact numeric thresholds unless they are grounded in the comment or telemetry.\n"
                f"{lang_instruction}\n\n"
                f"{COMMENT_STYLE_INSTRUCTIONS}"
            )
            # ── Delimitador de contenido no confiable + derecho a abstenerse ──
            # HISTORICAL/DATA ya viven compactas en la base de sitio 1; aquí la
            # base es corta, se conservan las 2 restantes verbatim (tests).
            system_prompt = system_prompt + "\n\n" + UNTRUSTED_DIRECTIVE + "\n\n" + ABSTAIN_RULE
            system_prompt = system_prompt + "\n\n" + (
                "No unverifiable third-party incidents or named anecdotes you "
                "cannot source. AVOID specific years (1990, 2003, 2016, etc.) unless in source context. Use early 2000s or past decade instead. If they brought data or admitted limits: extend, "
                "contrast, or ask what their data opens — never restate their "
                "conclusion as yours."
            )
            try:
                reply = await self.llm.generate(
                    tier=tier,
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    max_tokens=180,
                    temperature=0.7,
                )
                reply = (reply or "").strip()
                span.set("length", len(reply) if reply else 0)

                # ── ABSTAIN: salida legitima, no inventar lo no fundamentado ──
                if reply.upper().startswith("ABSTAIN"):
                    self._stats["abstained"] = self._stats.get("abstained", 0) + 1
                    record_abstain(True)
                    logger.info("Phase B: own-post reply ABSTAIN (author=%s)", author)
                    return "ABSTAIN"
                record_abstain(False)

                # ── Gate de citas historicas: un año fuera del contexto (lo que
                # el interlocutor menciono / el paper / el incidente propio) es
                # un incidente de terceros con detalles no verificables ──
                # (mismo criterio que el feed: el claims_context es output
                # propio y NO auto-legitima citas pasadas)
                _hist_ctx = f"{comment_text} {thread_history}"
                try:
                    _hist_ctx += " " + str(_ein_context or "")
                except Exception:
                    pass
                _bad_year = text_has_unverifiable_historical_claim(reply, _hist_ctx, is_own_incident=True)
                if _bad_year:
                    logger.warning(
                        "Phase B: own-post reply REJECTED — unverifiable historical claim (año %s) author=%s",
                        _bad_year, author,
                    )
                    return ""

                # ── Borrador + revision (writer + critic): alta exposicion o canal
                # con ROI medido (data-driven) ──
                if self._should_critique(tier, author):
                    reply, _quality_log = await self._critique_quality_draft(
                        reply, f"{comment_text} {thread_history}"
                    )
                    logger.info("Phase B: quality reply: %s (author=%s)", _quality_log, author)

                # ── Historical examples gate: block if repeated example ──
                is_repeat, blocked_examples = is_example_recently_used(reply)
                if is_repeat:
                    logger.warning("Phase B: own-post reply BLOCKED — repeated historical examples: %s", ", ".join(blocked_examples))
                    return ""

                score, reasons = await self._score_reply_draft(reply, comment_text,
                                                         block_ungrounded=self._is_watchlist_author(author)
                                                         or text_exposes_figures(comment_text))
                if score < 10:
                    logger.warning(
                        "Phase B: own-post reply REJECTED — score=%d reasons=%s preview=%s",
                        score, ",".join(reasons) or "none", reply[:100],
                    )
                    return ""
                # ── Register claims from reply ─────────────────────
                try:
                    if reply and _claims_tracker is not None:
                        ct_result = _claims_tracker.register_claims(reply, _claims_cluster)
                        logger.info(">>> [WIRE CHECK] Escribiendo claims_tracker.json (own reply): %s", ct_result)
                except Exception:
                    pass

                try:
                    if reply:
                        log_dual_score(reply, phase="b", reply_count=0)
                        logger.info(">>> [WIRE CHECK] Escribiendo dual_scores.jsonl (own reply)")
                except Exception:
                    pass

                # --- HARD FILTER: Block LLM hallucinations ---
                for _phrase in FORBIDDEN_PHRASES:
                    if _phrase in reply.lower():
                        logger.warning("Phase B: BLOCKED own-post reply — forbidden phrase '%s'", _phrase)
                        span.set("length", 0)
                        return ""
                fingerprint = self._reply_theme_fingerprint(reply, comment_text)
                if fingerprint:
                    self._replied_topic_fingerprints.add(fingerprint)
                    self._dedup.sync_replied_topic_fingerprints(self._replied_topic_fingerprints)
                return _safe_truncate(reply, max_chars=500)
            except Exception as e:
                logger.warning(f"Phase B: error en generación de own post reply: {e}")
                span.set("length", 0)
                return ""

    # ── Topic / comment value classifiers ────────────────────────

    @staticmethod
    def _classify_topic_value(body: str, comments: Optional[List[Dict]] = None) -> str:
        from .value_log_utils import _classify_topic_value
        return _classify_topic_value(body, comments, tech_keywords=PhaseB._TECH_KEYWORDS)

    @staticmethod
    def _classify_comment_value(comment_text: str) -> str:
        from .value_log_utils import _classify_comment_value
        return _classify_comment_value(comment_text, tech_keywords=PhaseB._TECH_KEYWORDS)

    @staticmethod
    def _is_non_trivial_contribution(draft: str) -> bool:
        from .value_log_utils import _is_non_trivial_contribution
        return _is_non_trivial_contribution(draft)

    @staticmethod
    def _classify_debate_value(text: str) -> str:
        from .value_log_utils import _classify_debate_value
        return _classify_debate_value(text)

    # ── Strategic upvotes ─────────────────────────────────────────

    def _maybe_upvote(self, post_id: str, value_level: str) -> None:
        from .engagement import _maybe_upvote
        _maybe_upvote(self, post_id, value_level)

    # ── Strategic following ───────────────────────────────────────

    def _maybe_follow_author(self, author: str) -> None:
        from .engagement import _maybe_follow_author
        _maybe_follow_author(self, author)

    # ── Semantic search feed complement ────────────────────────────

    async def _fetch_semantic_search_posts(self) -> List[Dict[str, Any]]:
        with Span("semantic_search"):
            if not self._semantic_search_enabled:
                return []

            queries = self._derive_search_queries()
            if not queries:
                return []

            seen_ids: Set[str] = set()
            results: List[Dict[str, Any]] = []
            rehydrated_count = 0
            discarded_count = 0
            now = datetime.now(timezone.utc)
            max_age_days = 7

            for query in queries:
                try:
                    posts = self.api.semantic_search(query, limit=self._semantic_search_limit)
                except Exception as e:
                    logger.debug("Phase B: semantic search query %r failed: %s", query, e)
                    continue

                for post in posts:
                    pid = post.get("id") or post.get("post_id") or ""
                    if not pid or pid in seen_ids:
                        continue
                    seen_ids.add(pid)

                    # ── Spam/edad: mismo gate que el feed ──
                    # (el post vía semantic_search/rehidratación NO pasaba por
                    # _fetch_candidate_posts: por ahí entró el post spam de 96
                    # días. El gate se aplica también a los rehidratados abajo.)
                    if post.get("is_spam") or post.get("is_deleted") or post.get("is_locked"):
                        logger.info("Phase B: semantic post %s REJECTED (spam/deleted/locked)", pid)
                        continue
                    _ts_raw = post.get("created_at") or post.get("createdAt") or post.get("timestamp") or ""
                    if _ts_raw:
                        try:
                            _post_dt = datetime.fromisoformat(str(_ts_raw).replace("Z", "+00:00"))
                            if _post_dt.tzinfo is None:
                                _post_dt = _post_dt.replace(tzinfo=timezone.utc)
                            if (now - _post_dt).total_seconds() / 86400.0 > max_age_days:
                                logger.debug("Phase B: semantic post %s descartado: age > %d days", pid, max_age_days)
                                continue
                        except Exception:
                            pass

                    raw_sub = post.get("submolt") or post.get("community") or ""
                    from .candidate_scorer import _extract_submolt_name
                    sub_name = _extract_submolt_name(raw_sub) if raw_sub else ""
                    if sub_name in BLOCKED_SUBMOLTS:
                        continue

                    if pid in self._commented_post_ids:
                        continue

                    # ── Rehidratacion de fragmentos de busqueda ──
                    # semantic_search devuelve snippets resaltados (marcadores
                    # ⟦HL⟧...⟦/HL⟧, bodies de 119-286 chars): no son posts
                    # reales. Si el resultado trae marcadores, se recupera el
                    # post COMPLETO por id (get_post); si no se puede, se
                    # descarta — responder a un fragmento seria incoherente.
                    _body = str(post.get("content") or post.get("body") or post.get("text") or "")
                    if _HL_MARKER in _body:
                        try:
                            full = self.api.get_post(pid)
                        except Exception:
                            full = None
                        if full:
                            # El snippet no traía los campos del gate; el post
                            # rehidratado sí → aplicar spam/edad sobre `full`.
                            if full.get("is_spam") or full.get("is_deleted") or full.get("is_locked"):
                                logger.info("Phase B: snippet rehidratado %s REJECTED (spam/deleted/locked)", pid)
                                continue
                            _ts_raw2 = full.get("created_at") or full.get("createdAt") or full.get("timestamp") or ""
                            if _ts_raw2:
                                try:
                                    _post_dt2 = datetime.fromisoformat(str(_ts_raw2).replace("Z", "+00:00"))
                                    if _post_dt2.tzinfo is None:
                                        _post_dt2 = _post_dt2.replace(tzinfo=timezone.utc)
                                    if (now - _post_dt2).total_seconds() / 86400.0 > max_age_days:
                                        logger.debug("Phase B: snippet rehidratado %s descartado: age > %d days", pid, max_age_days)
                                        continue
                                except Exception:
                                    pass
                            full["_search_query"] = query
                            full["_rehydrated"] = True
                            results.append(full)
                            rehydrated_count += 1
                        else:
                            discarded_count += 1
                            logger.info(
                                "Phase B: snippet con marcador de busqueda descartado "
                                "(no se pudo rehidratar post %s)", pid,
                            )
                        continue

                    post["_search_query"] = query
                    results.append(post)

            if results or rehydrated_count or discarded_count:
                logger.info(
                    "Phase B: semantic search returned %d unique posts from %d queries "
                    "(rehidratados=%d, fragmentos descartados=%d)",
                    len(results), len(queries), rehydrated_count, discarded_count,
                )
            update_today_metrics(semantic_searches_today=1)
            return results

    @staticmethod
    def _derive_search_queries() -> List[str]:
        import os
        env_queries_raw = os.getenv("SEMANTIC_SEARCH_QUERIES", "")
        max_q = int(os.getenv("SEMANTIC_SEARCH_MAX_QUERIES", "2"))

        queries: List[str] = []

        try:
            agenda_path = BASE_DIR / "data/research_agenda.json"
            if agenda_path.exists():
                data = json.loads(agenda_path.read_text(encoding="utf-8"))
                topics = data.get("pending_topics") or []
                for t in topics:
                    raw = t.get("topic") or t.get("title") or ""
                    raw = raw.strip()
                    if raw and len(raw) <= 80:
                        queries.append(raw)
                    elif raw:
                        queries.append(raw[:77] + "...")
                    if len(queries) >= max_q:
                        break
        except Exception:
            pass

        if not queries:
            try:
                roadmap_path = BASE_DIR / "data/topic_roadmap.json"
                if roadmap_path.exists():
                    data = json.loads(roadmap_path.read_text(encoding="utf-8"))
                    for series in data.get("series") or []:
                        for t in series.get("topics") or []:
                            raw = t.strip()
                            if raw and len(raw) <= 80:
                                queries.append(raw)
                            elif raw:
                                queries.append(raw[:77] + "...")
                            if len(queries) >= max_q:
                                break
                        if len(queries) >= max_q:
                            break
            except Exception:
                pass

        if not queries and env_queries_raw:
            queries = [q.strip() for q in env_queries_raw.split(",") if q.strip()][:max_q]

        return queries





