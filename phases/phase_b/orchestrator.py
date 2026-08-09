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
  max_comments_per_day        = 12  — presupuesto diario total (propios + feed)
  max_comment_replies_per_cycle = 4  — por ciclo (~8 h)
  max_comments_per_post        = 6   — replies máximos del agente en un post propio
  max_feed_comments_per_post   = 3   — replies máximos del agente en un post ajeno
  max_feed_replies_per_day     = 3   — tope diario solo para feed replies
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
from .scoring import RelevanceDecision, _get_feed_min_score, text_has_fabricated_measurement, _triage_comment_value
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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Set

from config.agent_policy import POLICY
from config import BASE_DIR
from core.observability import send_event
from core.tracer import Span
from core.value_log import log_value_event
from phases.deps import PhaseBDeps
from prompts.value_classifier import build_classifier_prompt
from prompts.prompt_templates import REPLY_TEMPLATE, DEBATE_CONTINUATION_TEMPLATE, OLLAMA_FALLBACK_REPLY, get_reply_depth_directive
from core.claims_tracker import ClaimsTracker
from personality.modes import select_mode, get_mode_prompt
from services.dual_scoring import log_dual_score
from services.energy_knowledge_base import EnergyKnowledgeBase
from services.moltbook_api_client import APIResponse
from services.dedup_store import DedupStore
from services import reply_cap
from services.persistence import enqueue_outbox
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
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from utils.phase_utils import phase_error_boundary, validate_phase_deps

logger = logging.getLogger("phases.phase_b")


def _quality_bestof_enabled() -> bool:
    """A/B flag AGENT_QUALITY_BESTOF=1 activa best-of-2 selectivo en replies."""
    return os.getenv("AGENT_QUALITY_BESTOF", "0") == "1"


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
            "ANALYZE the post above in light of these verified claims.",
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
        now = datetime.now()

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

        self.max_comments_per_post = behavior.get("max_comments_per_post", 2)
        self.max_comments_per_day = behavior.get("max_comments_per_day", 15)
        self.max_replies_per_cycle = behavior.get("max_comment_replies_per_cycle", 2)
        self.max_feed_comments_per_post = behavior.get("max_feed_comments_per_post", 1)
        self.max_own_posts_per_cycle = behavior.get("phase_b_max_own_posts_per_cycle", 6)
        self.delay_between_comments = behavior.get("delay_between_comments", 8)
        # ── Anti-dogpile: hard per-post reply cap (env-only, NOT auto-optimizable) ──
        self.max_replies_per_post = reply_cap.get_cap()
        self._replies_per_post_path: Path = reply_cap._REPLIES_PER_POST_PATH
        # ── Threaded follow-ups: per-post cap independiente del anti-dogpile ──
        self.max_followups_per_post = reply_cap.get_followups_cap()
        self._followups_per_post_path: Path = reply_cap._FOLLOWUPS_PER_POST_PATH
        self._last_comment_per_thread: Dict[str, str] = {}
        self._dedup = DedupStore()
        self._dedup.cleanup(older_than_hours=24)
        self._dedup.cleanup(older_than_hours=720)  # v5.0: 30-day deep cleanup
        self._replied_comment_ids: Set[str] = self._dedup.get_replied_comment_ids()
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
    ) -> RelevanceDecision:
        from .scoring import _decide_reply
        return _decide_reply(PhaseB, comment, limit_ok, is_own_post_reply, tech_keywords=PhaseB._TECH_KEYWORDS)

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
    def _passes_quality_gate(text: str) -> bool:
        """v5.1 quality gate: length + banned openers only. Score decides upstream.

        The abstraction constraint (no company names / calendar years) and the
        math constraints are enforced structurally in the prompt, not via
        brittle regex here.
        """

        if not text or not text.strip():
            return False
        text_stripped = text.strip()
        text_len = len(text_stripped)

        # ── Length gate (50-500 characters) ──
        if text_len < 50 or text_len > 500:
            logger.debug("Phase B: quality gate failed — length=%d (expected 50-500)", text_len)
            return False

        # ── Banned openers ──
        text_lower = text_stripped.lower()
        banned_openers = _load_banned_openers()
        for opener in banned_openers:
            if text_lower.startswith(opener.lower()):
                logger.debug("Phase B: quality gate failed — banned opener '%s'", opener)
                return False

        # ── Evidence/framework/metric signals: logged for diagnostics only, no longer block ──
        has_evidence = any(s in text_lower for s in [
            "measured", "observed", "in production", "data shows",
            "we deployed", "we saw", "we hit", "the result was",
        ])
        has_framework = any(s in text_lower for s in [
            "propose", "pattern", "framework", "architecture",
            "design", "principle", "the approach", "strategy",
        ])
        has_metric = any(c.isdigit() for c in text)
        logger.info("Phase B: quality gate signal check len=%d evidence=%s framework=%s metric=%s",
                    text_len, has_evidence, has_framework, has_metric)
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
        text_check = text[:500]
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
                              is_followup: bool = False) -> Optional[Dict]:
        """Publish a comment with safety checks. Returns result dict or None if blocked.

        is_followup=True marca una respuesta enhebrada dentro de una conversación
        viva (respuesta a una respuesta a NUESTRO comentario). Estos NO cuentan
        para el contador anti-dogpile por post (que existe para frenar el apilado
        de comentarios top-level), ni son bloqueados por su cap: sostener una
        conversación no es un dogpile. Su límite propio es
        AGENT_MAX_FOLLOWUPS_PER_POST, controlado por el caller."""
        # v5.1: Quality gate — length (50-500) + banned openers only
        if not self._passes_quality_gate(content):
            text_len = len(content.strip())
            logger.warning("Phase B: quality gate REJECTED (length or banned opener). len=%d. Preview: %s",
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
            if current_count >= self.max_comments_per_post:
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

            # ── Anti-dogpile: monotonic per-post cap (feed + own-post) ──
            # Hard guardrail (env AGENT_MAX_REPLIES_PER_POST, default 3),
            # independent of feed payload. Only for UUID post IDs.
            # Follow-ups enhebrados están exentos: conversar no es apilar.
            if len(post_id) > 10 and not is_followup:
                current_count = self._get_replies_per_post(post_id)
                if current_count >= self.max_replies_per_post:
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

                # ── Anti-dogpile: count published replies (2xx, not spam) ──
                # Follow-ups enhebrados no consumen este contador (tienen el suyo).
                if len(post_id) > 10 and 200 <= status < 300 and not is_followup:
                    new_count = self._increment_replies_per_post(post_id)
                    logger.info(
                        "anti-dogpile: post %s now at %d/%d",
                        post_id, new_count, self.max_replies_per_post,
                    )

            return result
        except Exception as e:
            logger.error("Phase B: create_comment error for post %s: %s", post_id, e)
            return None

    def _score_reply_draft(self, reply_text: str, source_text: str, log_context: Optional[Dict[str, Any]] = None) -> tuple[int, List[str]]:
        # v5.1: Permissive scoring mode — base 50, all penalties zeroed for testing
        score = 50
        reasons: List[str] = []

        # ── Shadow quality logging (non-blocking, diagnostics only) ──
        # Runs the three disabled guardrail functions purely for observability.
        # If ANY would have flagged the reply, a JSONL record is appended to
        # data/shadow_quality_checks.jsonl so we can calibrate the penalties
        # against real data before deciding to reactivate them in the gate.
        # Wrapped in try/except — a shadow-log I/O failure must never affect
        # the actual publication flow.
        if log_context is not None:
            try:
                shadow_hits = []
                if self._reply_has_guardrail_template(reply_text):
                    shadow_hits.append("guardrail_template")
                if self._reply_has_ungrounded_numeric_specificity(reply_text, source_text):
                    shadow_hits.append("ungrounded_numeric_specificity")
                if not self._reply_mentions_source_terms(reply_text, source_text):
                    shadow_hits.append("weak_source_anchor")
                if shadow_hits:
                    # No polucionar el shadow log con entradas de dry-run/test
                    # (post-1, p-test, o IDs que parecen simulados) — las 1584
                    # entradas de prueba enmascaraban las 76 reales.
                    _pid = str(log_context.get("post_id") or "")
                    if not _pid or _pid.startswith("p-test") or _pid.startswith("post-1") \
                            or "test" in _pid.lower() or _pid.endswith("-simulated"):
                        pass  # skip synthetic records
                    else:
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
                        try:
                            _sh = getattr(self, "_shadow_quality_log_path", None) or Path("data") / "shadow_quality_checks.jsonl"
                            _sh.parent.mkdir(parents=True, exist_ok=True)
                            with open(str(_sh), "a", encoding="utf-8") as _fh:
                                _fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                        except Exception:
                            pass  # never fail the real flow
            except Exception:
                pass

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
        with Span("phase_b_cycle") as span:
            feed_results: List[Dict[str, Any]] = []
            own_results: List[Dict[str, Any]] = []

            # ── Feed budget reservation ─────────────────────────────
            feed_budget_pct = int(self.deps.behavior_cfg.get("feed_budget_pct", 40))
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
            remaining_cycle = max(0, self.max_replies_per_cycle - own_count)

            # Restore full cap for feed replies
            self.max_comments_per_day = _orig_max
            feed_available = max(0, self.max_comments_per_day - self.get_comments_today())

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
                if self.get_comments_today() < self.max_comments_per_day and remaining_cycle > 0:
                    followup_results = await self._execute_thread_followups(
                        remaining_cycle_slots=remaining_cycle,
                    )

            followup_count = len(followup_results)
            remaining_cycle = max(0, remaining_cycle - followup_count)

            # Feed replies with reserved budget (lo que quede tras follow-ups)
            if self.deps.behavior_cfg.get("phase_b_feed_replies", True):
                if self.get_comments_today() < self.max_comments_per_day and remaining_cycle > 0:
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
            logger.info(
                "Phase B: cycle summary — own-post replies=%s, thread follow-ups=%s, "
                "feed replies=%s, upvotes=%s, follows=%s, semantic_candidates=%s, "
                "claim-check failures=%s, total=%s",
                own_count, followup_count, feed_count, self._upvotes_this_cycle,
                self._follows_this_cycle, semantic_count, self._stats.get("claim_check_failed", 0), total,
            )
            span.set("feed_replies", feed_count)
            span.set("own_replies", own_count)
            span.set("thread_followups", followup_count)
            return {
                "success": total > 0,
                "replies_published": total,
                "debate_continuations": 0,
                "thread_followups": followup_count,
                "claim_check_failures": self._stats.get("claim_check_failed", 0),
                "upvotes": self._upvotes_this_cycle,
                "follows": self._follows_this_cycle,
                "semantic_candidates": semantic_count,
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
            if is_semantic_duplicate_reply(reply_text, prior, threshold=0.80):
                logger.info(
                    "Phase B: semantic duplicate (%.2f) against prior in thread %s (attempt %s)",
                    0.80, post_id, attempt,
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
                        is_semantic_duplicate_reply(new_reply, p, threshold=0.80)
                        for p in all_prior
                    )
                    if still_dup:
                        logger.info("Phase B: re-generated reply still semantic duplicate in thread %s", post_id)
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

            effective_cycle_limit = (
                remaining_cycle_slots if remaining_cycle_slots is not None
                else self.max_replies_per_cycle
            )
            cycle_count = 0

            # ── Solo posts ajenos comentados en las últimas 48 h ──
            cutoff = datetime.now() - timedelta(hours=48)
            recent_post_ids: List[str] = []
            for pid, ts in self._commented_post_ids.items():
                if not isinstance(pid, str):
                    continue
                try:
                    ts_dt = datetime.fromisoformat(ts) if isinstance(ts, str) else None
                except (ValueError, TypeError):
                    ts_dt = None
                if ts_dt is not None and ts_dt >= cutoff:
                    recent_post_ids.append(pid)

            if not recent_post_ids:
                logger.info("Phase B: sin posts revisitables para follow-ups (ninguno en 48 h).")
                span.set("posted", 0)
                return []

            from services import interlocutors

            for post_id in recent_post_ids:
                if self.get_comments_today() >= self.max_comments_per_day:
                    logger.info(
                        "Phase B: skip follow-ups — daily limit (%s/%s).",
                        self.get_comments_today(), self.max_comments_per_day,
                    )
                    break
                if cycle_count >= effective_cycle_limit:
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
                if followups_done >= self.max_followups_per_post:
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

                our_id_set = {str(cid) for cid in our_comment_ids}
                # Respuestas A NUESTROS comentarios (parent_id apunta a uno nuestro),
                # excluyendo las nuestras propias.
                replies_to_us = [
                    c for c in comments
                    if isinstance(c, dict)
                    and str(c.get("parent_id") or "") in our_id_set
                    and not self._is_own_author(self._get_author_name(c))
                ]
                if not replies_to_us:
                    continue

                post_touched = False
                for reply_comment in replies_to_us:
                    if self.get_comments_today() >= self.max_comments_per_day:
                        break
                    if cycle_count >= effective_cycle_limit:
                        break
                    if followups_done >= self.max_followups_per_post:
                        logger.info(
                            "Phase B: post %s alcanzó cap de follow-ups (%d/%d).",
                            post_id, followups_done, self.max_followups_per_post,
                        )
                        break

                    reply_id = reply_comment.get("id") or reply_comment.get("comment_id")
                    if not reply_id:
                        continue
                    reply_text = (reply_comment.get("content") or reply_comment.get("text") or "").strip()
                    if not reply_text:
                        continue
                    reply_author = self._get_author_name(reply_comment) or "usuario"

                    # ── Dedup durable: nunca responder dos veces el mismo comentario ──
                    if reply_cap.has_replied_to_comment(f"{post_id}:{reply_id}"):
                        logger.info(
                            "Phase B: skip follow-up a comentario %s en post %s (durable dedup).",
                            reply_id, post_id,
                        )
                        continue

                    # ── Guard de profundidad: no seguir más allá de MAX_CONVERSATION_DEPTH ──
                    depth = self._compute_thread_depth(reply_comment, comments)
                    if depth >= MAX_CONVERSATION_DEPTH:
                        logger.info(
                            "Phase B: skip follow-up — profundidad %s >= max %s (post %s, comment %s).",
                            depth, MAX_CONVERSATION_DEPTH, post_id, reply_id,
                        )
                        continue

                    # ── Triage de calidad + bonus de interlocutor ──
                    skip_triage, triage_reason = _triage_comment_value(
                        reply_text,
                        tech_keywords=self._TECH_KEYWORDS,
                        author=reply_comment.get("author"),
                    )
                    if skip_triage:
                        logger.info(
                            "Phase B: skip follow-up a comentario %s (triage: %s).",
                            reply_id, triage_reason,
                        )
                        continue

                    # ── Ledger: observación de la respuesta a nuestro comentario ──
                    interlocutors.record_interaction(
                        reply_comment.get("author"), on_our_post=False,
                    )

                    # ── Generar respuesta enhebrada (con historial del hilo) ──
                    thread_history = self._build_thread_history(reply_comment, comments)
                    try:
                        followup_text = await self._generate_own_post_reply(
                            reply_author, reply_text, thread_history,
                        )
                    except Exception as e:
                        logger.warning("Phase B: error generando follow-up: %s", e)
                        continue

                    followup_text = (followup_text or "").strip()
                    if not followup_text:
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

                    # ── Publicar ENHEBRADO: parent = comentario que nos respondió ──
                    resp = self._safe_publish_comment(
                        post_id=str(post_id),
                        content=followup_text,
                        parent_comment_id=str(reply_id),
                        is_followup=True,
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
                        "Phase B: thread follow-up publicado post_id=%s parent=%s (%d/%d).",
                        post_id, reply_id, followups_done, self.max_followups_per_post,
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
            if daily_comment_count >= self.max_comments_per_day:
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
            logger.info(
                "Phase B: feed replies — comments_today=%s/%s, remaining_feed_daily=%s/%s, cycle_budget=%s",
                daily_comment_count, self.max_comments_per_day, remaining_daily, max_feed, effective_cycle_limit,
            )

            # Load roadmap for topic alignment
            roadmap = load_roadmap()
            roadmap_topics_lower = set(t.lower() for t in roadmap.all_topics())

            candidate_posts = self._fetch_candidate_posts(limit=50)
            candidate_posts = candidate_posts[:15]  # slightly larger pool for stricter selection

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

            # ── Feed-specific limits: daily global, feed-daily, and remaining cycle budget ──
            for score, post in scored_posts:
                daily_comment_count = self.get_comments_today()
                if daily_comment_count >= self.max_comments_per_day:
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
                effective_cycle_limit = remaining_cycle_slots if remaining_cycle_slots is not None else self.max_replies_per_cycle
                if cycle_comment_count >= effective_cycle_limit:
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
                         if c.get("parent_id") in agent_post_ids),
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
                    _feed_cap = int(self.deps.behavior_cfg.get("max_feed_comments_per_post", 3))
                    _feed_count = self._get_agent_reply_count_in_post(str(post_id))
                    if _feed_count >= _feed_cap:
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
                # ── Ledger: observación del feed post ──
                from services import interlocutors
                interlocutors.record_interaction(
                    post.get("author"), on_our_post=False,
                )

                try:
                    bestof = (_quality_bestof_enabled()
                              and post_decision.score >= POLICY.min_comment_relevance_score + 20)
                    reply_text = await self._generate_reply_for_post(post, bestof=bestof)
                except Exception as e:
                    logger.warning(f"Phase B: error generando respuesta: {e}")
                    continue

                reply_text = (reply_text or "").strip()
                if not reply_text:
                    logger.warning("Phase B: respuesta vacía generada.")
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
                    continue

                # ── Top-level dedup: one comment per post in feed ──
                if post_id in self._commented_post_ids:
                    logger.info(
                        "Phase B: skip feed post %s — already top-level commented.",
                        post_id,
                    )
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
                        continue
                except Exception:
                    pass
                    continue

                reply_text = clean_llm_output(reply_text)

                reply_text = await self._check_and_prevent_duplicate(post_id, reply_text)
                if reply_text is None:
                    continue

                if len(reply_text.strip()) < 40 or is_likely_truncated(reply_text):
                    logger.info("Phase B: skip feed reply — too short or truncated (len=%d)", len(reply_text.strip()))
                    continue

                resp = self._safe_publish_comment(post_id=str(post_id), content=reply_text)
                if resp is None:
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
                        "Phase B: comentario publicado en post_id=%s title=%s...",
                        post_id,
                        str(post.get("title") or "")[:40],
                    )
                    interlocutors.record_interaction(
                        post.get("author"), on_our_post=False,
                    )
                    feed_comment_count += 1
                    cycle_comment_count += 1
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

                    self._commented_post_ids[post_id] = datetime.now().isoformat()
                    self._dedup.set_commented_post(post_id)
                    self._post_history_guard[post_id] = datetime.now().isoformat()
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
            now = datetime.now(timezone.utc)
            max_age_days = 7
            for p in posts:
                if not isinstance(p, dict):
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
                "Phase B: %s posts candidatos (total_feed=%s, blocked=%s, allowlist_rejected=%s, stale=%s).",
                len(filtered), len(posts), blocked_count, allowlist_blocked_count, stale_count,
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

            return my_count < self.max_feed_comments_per_post

        except Exception as e:
            logger.warning(f"Phase B: error en _can_comment_in_thread: {e}")
            return True

    @staticmethod
    def _compute_thread_depth(comment: Dict, all_comments: List[Dict]) -> int:
        """How many levels deep this comment is in the thread.

        Depth 0 = no parent_id (top-level).
        Depth 1 = parent is a top-level comment.
        Depth 2 = grandparent is a top-level comment, etc.
        """
        depth = 0
        parent_id = comment.get("parent_id")
        if not parent_id:
            return 0
        cmap = {c.get("id"): c for c in all_comments if c.get("id")}
        while parent_id and parent_id in cmap:
            depth += 1
            parent_id = cmap[parent_id].get("parent_id")
        return depth

    async def _generate_reply_bestof(self, user_prompt: str, system_prompt: str,
                                     title: str, body: str) -> str:
        """Best-of-2: genera 2 borradores y conserva el de mayor _score_reply_draft.
        Degradación elegante: si el 2º falla o sale vacío se usa el 1º; nunca
        devuelve un resultado peor/inválido que un reply único."""
        source_text = f"{title}\n{body}".strip()
        candidate_a = ""
        candidate_b = ""
        try:
            raw_a = await self.llm.generate(
                tier="flash",
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
                tier="flash",
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
        score_a, _ = self._score_reply_draft(candidate_a, source_text)
        score_b, _ = self._score_reply_draft(candidate_b, source_text)
        chosen = candidate_a if score_a >= score_b else candidate_b
        logger.info("Phase B: best-of-2 reply — A=%d B=%d chosen=%s",
                    score_a, score_b, "A" if chosen == candidate_a else "B")
        return chosen

    async def _generate_reply_for_post(self, post: Dict[str, Any], bestof: bool = False) -> str:
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
                "You are a senior systems engineer who reasons about distributed systems and agent architectures.\n"
                "You have NO production deployment and run NO experiments.\n"
                "NEVER write 'we measured', 'in our tests', 'in production we saw', "
                "or any first-person measurement claim.\n"
                "Reason about mechanisms, invariants, thresholds, and design patterns instead.\n\n"
                "RESPONSE FORMAT (mandatory structure):\n"
                "1. ANCHOR: Quote or reference one specific claim from the post (1 sentence).\n"
                "2. ANALYSIS: Analyze the underlying mechanism, system property, or architectural principle "
                "(1-2 sentences). Use reasoning from systems theory, distributed systems, or software architecture.\n"
                "3. FRAMEWORK: Propose a pattern, architecture change, or design principle (1-2 sentences).\n"
                "   Use phrases like: 'The pattern that works is...', 'A framework for this is...', "
                "'The architecture should...'\n"
                "4. EDGE CASE (optional): Name one failure mode or counter-example (1 sentence).\n\n"
                "HARD CONSTRAINTS:\n"
                "- Do NOT use emojis, hashtags, links, or markdown.\n"
                "- Do NOT be promotional or agreeable. Add friction, not praise.\n"
                "- Do NOT start with 'Great point' or 'I agree'. Start with the mechanism.\n"
                "- Every reply MUST contain at least one concrete threshold, failure mode, or design pattern.\n"
                "- Every reply MUST propose or name a pattern/framework/architecture explicitly.\n"
                "- DO NOT fabricate measurements. You have NO production data.\n"
                "- Maximum 4 sentences. Density over length.\n\n"
                f"{lang_instruction}\n\n"
                f"{COMMENT_STYLE_INSTRUCTIONS}"
            )

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
                        f"NOTA DE MEMORIA: Ya has interactuado con @{mem['username']} antes. "
                        f"Contexto previo: {mem['summary']}\n\n"
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
                        return ""
            except Exception:
                pass

            user_prompt = memory_note + REPLY_TEMPLATE.format(
                title=title,
                content=body[:1200],
                min=80,
                max=400
            )

            if not self.llm:
                span.set("length", 0)
                return ""

            # ── Step A: Extract claim ──────────────────────────────────────
            claim = None
            post_text = f"{title}\n{body}".strip()
            try:
                claim = await extract_claim(
                    post_text, post_text, self.llm,
                    tier=getattr(self, "_claim_checker_tier", "fallback"),
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
                        user_prompt, system_prompt, title, body
                    )
                else:
                    reply = await self.llm.generate(
                        tier="flash",
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        max_tokens=180,
                        temperature=0.7,
                    )
                    reply = (reply or "").strip()
                span.set("length", len(reply) if reply else 0)

                # ── Historical examples gate: block if repeated example ──
                is_repeat, blocked_examples = is_example_recently_used(reply)
                if is_repeat:
                    logger.warning("Phase B: feed reply BLOCKED — repeated historical examples: %s", ", ".join(blocked_examples))
                    return ""

                score, reasons = self._score_reply_draft(reply, f"{title}\n{body}",
                                                            log_context={"post_id": post.get("id")})
                if score < 10:
                    logger.warning(
                        "Phase B: feed reply REJECTED — score=%d reasons=%s preview=%s",
                        score, ",".join(reasons) or "none", reply[:100],
                    )
                    return ""

                # ── Step C: Check claim ────────────────────────────────────
                if claim and reply:
                    try:
                        check_result = await check_claim(
                            claim, reply, self.llm,
                            tier=getattr(self, "_claim_checker_tier", "fallback"),
                        )
                    except Exception:
                        check_result = {
                            "on_topic": True, "score": 1.0,
                            "reason": "check skipped (LLM error)",
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
                        return ""

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
                        return ""
                fingerprint = self._reply_theme_fingerprint(reply, f"{title}\n{body}")
                if fingerprint:
                    self._replied_topic_fingerprints.add(fingerprint)
                    self._dedup.sync_replied_topic_fingerprints(self._replied_topic_fingerprints)

                # ── Quality gate: ensure reply has framework/evidence signals ──
                if not self._passes_quality_gate(reply):
                    logger.info("Phase B: reply failed quality gate, attempting retry...")
                    try:
                        retry_prompt = (
                            f"Your previous response was too generic. Rewrite to include:\n"
                            f"1. A specific metric or measurement (with a number)\n"
                            f"2. A named pattern or framework\n"
                            f"Original: {reply}\n\nRewrite (max 4 sentences):"
                        )
                        retry_text = await self.llm.generate(
                            prompt=retry_prompt,
                            system_prompt="You are a senior systems engineer. Be specific and concrete.",
                            max_tokens=1024,
                            temperature=0.7,
                            tier="flash",
                            caller="phase_b_quality_retry",
                        )
                        if retry_text and retry_text.strip() and self._passes_quality_gate(retry_text.strip()):
                            reply = retry_text.strip()
                            logger.info("Phase B: quality gate retry succeeded")
                    except Exception:
                        pass  # Use original reply if retry fails

                return _safe_truncate(reply, max_chars=500)
            except Exception as e:
                logger.warning(f"Phase B: error en generación de reply: {e}")
                span.set("length", 0)
                return ""

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
            posts = sorted(
                posts,
                key=lambda p: int(p.get("comment_count") or p.get("comments_count") or 0),
                reverse=True,
            )[:_OWN_POST_REPLY_SCORE_LIMIT]

            # Score own posts by unreplied comment count; prioritize threads with pending discussion
            scored_own_posts: List[tuple] = []
            for idx, post in enumerate(posts):
                post_id = post.get("id") or post.get("post_id")
                if not post_id:
                    logger.warning(f"Phase B: skipping post without id during scoring: {post}")
                    continue
                try:
                    post_comments = self.api.fetch_post_comments(post_id)
                except Exception as e:
                    logger.warning(f"Phase B: error fetching comments for scoring post {post_id}: {e}")
                    continue
                unreplied = 0
                for c in post_comments:
                    author = self._get_author_name(c)
                    if self._is_own_author(author):
                        continue
                    cid = c.get("id") or c.get("comment_id")
                    if not cid:
                        continue
                    dedup_key = f"{post_id}:{cid}"
                    if dedup_key in self._replied_comment_ids:
                        continue
                    if not (c.get("content") or c.get("text") or "").strip():
                        continue
                    unreplied += 1
                logger.info(f"Phase B: own post {post_id} has {unreplied} unreplied comments")
                scored_own_posts.append((unreplied, idx, post))
            # Sort: most unreplied comments first; tiebreak by engagement rank
            # (lower idx = higher comment count in the sorted pool).
            scored_own_posts.sort(key=lambda x: (-x[0], x[1]))
            # Límite de posts por ciclo configurable (phase_b_max_own_posts_per_cycle,
            # default 6). Antes era 3 fijo: los top-3 absorbían todo el presupuesto
            # diario y los posts con menos comentarios quedaban desatendidos
            # indefinidamente (~218 pendientes en los posts fuera del top-3).
            candidate_posts = [p for _, _, p in scored_own_posts[:self.max_own_posts_per_cycle]]
            logger.info(f"Phase B: processing up to {len(candidate_posts)} own posts")

            results: List[Dict[str, Any]] = []

            for post in candidate_posts:
                post_id = post.get("id") or post.get("post_id")
                if not post_id:
                    logger.warning(f"Phase B: skipping post without id: {post}")
                    continue

                logger.info(f"Phase B: processing own post_id={post_id}")
                post_results = await self._process_own_post(post_id)
                results.extend(post_results)

            if not results:
                logger.info("Phase B: no se respondió a ningún comentario en posts propios.")

            span.set("results", len(results))
            return results

    def _fetch_own_posts_for_replies(
        self,
        ranked_limit: int = 50,
        fresh_limit: int = 10,
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
        if daily_comment_count >= self.max_comments_per_day:
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
            if current_count >= self.max_comments_per_post:
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

        for comment in comments:
            # ── Per-post limit (propios): máx. max_comments_per_post replies del agente en este post ──
            if replied_count >= self.max_comments_per_post:
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

            comment_id = comment.get("id") or comment.get("comment_id")
            comment_text = comment.get("content") or comment.get("text") or ""
            author = self._get_author_name(comment) or "usuario"

            if not comment_id:
                logger.warning(f"Phase B: comment without id on post {post_id}, skipping")
                continue
            # Fix 3: ignorar los propios replies del agente en el hilo
            _own = self._get_author_name(comment)
            if self._is_own_author(_own):
                logger.debug("Phase B: skip own comment %s on post %s", comment_id, post_id)
                continue

            # ── Thread depth guard ─────────────────────────────────
            parent_id = comment.get("parent_id")
            if parent_id and parent_id in self._agent_comment_ids.get(post_id, []):
                depth = self._compute_thread_depth(comment, comments)
                if depth >= MAX_CONVERSATION_DEPTH:
                    logger.info(
                        "Profundidad máxima alcanzada, salteando hilo "
                        "(post_id=%s, comment_id=%s, profundidad=%s, max=%s)",
                        post_id, comment_id, depth, MAX_CONVERSATION_DEPTH,
                    )
                    continue

            dedup_key = f"{post_id}:{comment_id}"
            if dedup_key in self._replied_comment_ids:
                logger.info("Phase B: skip comment %s on post %s (already replied).", comment_id, post_id)
                continue
            if not comment_text.strip():
                logger.info(f"Phase B: empty comment {comment_id} on post {post_id}, skipping")
                continue
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
                limit_ok=replied_count < self.max_comments_per_post,
                is_own_post_reply=is_own_post_reply,
            )
            if not decision.should_reply:
                send_event("phase_b_reply_skip", {
                    "post_id": post_id,
                    "comment_id": comment_id,
                    "reason": decision.reason,
                    "score": decision.score,
                    "snippet": comment_text[:60],
                })
                continue

            _value_cls = self._classify_comment_value(comment_text)
            self._stats["passed_value"] += 1

            # ── Build thread history for conversational context ──
            thread_history = ""
            if parent_id:
                thread_history = self._build_thread_history(comment, comments)

            result = await self._post_own_reply(post_id, comment_id, author, comment_text, thread_history)
            if result is None:
                continue

            # ── Strategic follow: follow agents who engage in genuine debate on our posts ──
            if author and not self._is_own_author(author) and _value_cls not in ("general",):
                self._maybe_follow_author(author)

            # ── Re-check daily/cycle budget after each own-post reply (feed may still have margin) ──
            daily_comment_count = self.get_comments_today()
            if daily_comment_count >= self.max_comments_per_day:
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
            if replied_count >= self.max_replies_per_cycle:
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
            if replied_count < self.max_comments_per_post and replied_count < self.max_replies_per_cycle:
                latest_other = None
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
                        elif self.get_comments_today() < self.max_comments_per_day:
                            # VERIFICACIÓN SEMÁNTICA: Buscar si el agente ya respondió algo muy parecido en este hilo
                            agent_replies_in_thread = [
                                c.get("content") or c.get("text") or "" 
                                for c in comments 
                                if self._is_own_author(self._get_author_name(c))
                            ]
                            proposed_reply = await self._generate_own_post_reply(other_author, other_text, self._build_thread_history(latest_other, comments))
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
            if any(kw in comment_lower for kw in concession_keywords):
                logger.info("Phase B: Cierre de hilo detectado con %s. No se requiere respuesta.", author)
                close_thread(post_id)
                return {"post_id": post_id, "comment_id": comment_id, "status": "closed_concession"}

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
                reply_text = await self._generate_own_post_reply(author, comment_text, thread_history)
            except Exception as e:
                logger.error(f"Phase B: LLM error for comment {comment_id} on post {post_id}: {e}")
                span.set("success", False)
                return None

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
            )
            if result is None:
                span.set("success", False)
                return None

            success = result.get("success", False) if isinstance(result, dict) else getattr(result, "success", False)
            already_existed = result.get("already_existed", False) if isinstance(result, dict) else getattr(result, "already_existed", False)
            error = result.get("error") if isinstance(result, dict) else getattr(result, "error", None)
            own_comment_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)

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


    # ── Research agenda helpers ───────────────────────────────────

    def _add_topic_to_agenda(self, post: Dict[str, Any], post_body: str) -> None:
        from .value_log_utils import _add_topic_to_agenda
        _add_topic_to_agenda(self, post, post_body)

    def _build_thread_history(self, comment: Dict, all_comments: List[Dict]) -> str:
        from .value_log_utils import _build_thread_history
        return _build_thread_history(self, comment, all_comments)

    async def _generate_own_post_reply(self, author: str, comment_text: str, thread_history: str = "") -> str:
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
            try:
                reply = await self.llm.generate(
                    tier="flash",
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    max_tokens=180,
                    temperature=0.7,
                )
                reply = (reply or "").strip()
                span.set("length", len(reply) if reply else 0)

                # ── Historical examples gate: block if repeated example ──
                is_repeat, blocked_examples = is_example_recently_used(reply)
                if is_repeat:
                    logger.warning("Phase B: own-post reply BLOCKED — repeated historical examples: %s", ", ".join(blocked_examples))
                    return ""

                score, reasons = self._score_reply_draft(reply, comment_text)
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

                    raw_sub = post.get("submolt") or post.get("community") or ""
                    from .candidate_scorer import _extract_submolt_name
                    sub_name = _extract_submolt_name(raw_sub) if raw_sub else ""
                    if sub_name in BLOCKED_SUBMOLTS:
                        continue

                    if pid in self._commented_post_ids:
                        continue

                    post["_search_query"] = query
                    results.append(post)

            if results:
                logger.info(
                    "Phase B: semantic search returned %d unique posts from %d queries",
                    len(results), len(queries),
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
