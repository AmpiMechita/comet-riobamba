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

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Set

from config.agent_policy import POLICY
from core.observability import send_event
from core.value_log import log_value_event
from phases.deps import PhaseBDeps
from prompts.value_classifier import build_classifier_prompt
from services.moltbook_api_client import APIResponse
from services.persistence import enqueue_outbox
from services.self_eval import update_today_metrics
from services.conversation_state import (
    can_continue_thread, register_agent_reply, update_open_questions,
    close_thread, is_thread_closed, get_or_create_thread,
)
from services.roadmap import load_roadmap
from utils.phase_utils import phase_error_boundary, validate_phase_deps

logger = logging.getLogger(__name__)

# ── Cold-start mode ──────────────────────────────────────────
_COLD_START_THRESHOLD = int(os.getenv("COLD_START_POST_THRESHOLD", "10"))
_COLD_START_MIN_SCORE = int(os.getenv("COLD_START_MIN_SCORE", "4"))
_cold_start_logged = False
_cold_start_lock = Lock()


def _get_feed_min_score(posts_today: int) -> int:
    global _cold_start_logged
    if posts_today < _COLD_START_THRESHOLD:
        if not _cold_start_logged:
            with _cold_start_lock:
                if not _cold_start_logged:
                    _cold_start_logged = True
                    logger.info(
                        "Cold start activo: posts_today=%s < threshold=%s, "
                        "usando min_score=%s en lugar de %s",
                        posts_today, _COLD_START_THRESHOLD,
                        _COLD_START_MIN_SCORE,
                        POLICY.min_comment_relevance_score + 10,
                    )
        return _COLD_START_MIN_SCORE
    return POLICY.min_comment_relevance_score + 10


@dataclass
class RelevanceDecision:
    should_reply: bool
    score: int
    reason: str

ALLOWED_SUBMOLTS = {
    "agents", "m/agents",
    "general", "m/general",
    "ai", "m/ai",
    "security", "m/security",
    "aisafety", "m/aisafety",
    "technology", "m/technology",
    "infrastructure", "m/infrastructure",
    "tooling", "m/tooling",
    "memory", "m/memory",
    "builds", "m/builds",
    "buildlogs", "m/buildlogs",
    "todayilearned", "m/todayilearned",
    "aithoughts", "m/aithoughts",
    "agentskills", "m/agentskills",
    "trading", "m/trading",
    "crypto", "m/crypto",
    "agentfinance", "m/agentfinance",
    "agenteconomy", "m/agenteconomy",
}

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

# ── Comment style policy (Spanish, inyectado en prompts de Fase B) ──

COMMENT_STYLE_INSTRUCTIONS = """
POLÍTICA DE ESTILO PARA RESPUESTAS:

1. Máximo 1 comentario por hilo, salvo que el otro agente te responda directamente con una pregunta explícita.
2. Nunca reescribas el comentario del otro agente casi completo. Prohibido copiar o parafrasear más de 1 frase seguida del otro comentario.
3. Estructura recomendada de respuesta:
   - 1 frase breve de reconocimiento/conexión.
   - 2-3 frases de aporte nuevo: ejemplo concreto, métrica, patrón de diseño o matiz técnico.
   - 1 frase opcional con una pregunta de seguimiento o experimento práctico.
4. Prioriza la precisión técnica y la claridad por encima de la longitud; si dudas, prefiere una respuesta corta pero útil.
5. Escribe con tus propias palabras. No repitas el texto del post ni los comentarios anteriores.
""".strip()


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


_REPLIED_IDS_PATH = Path("data/replied_comment_ids.json")
_COMMENTED_POSTS_PATH = Path("data/commented_post_ids.json")


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


def _save_commented_post_ids(ids: Dict[str, str]) -> None:
    """Save commented_post_ids dict, preserving existing timestamps for known entries."""
    try:
        _COMMENTED_POSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _COMMENTED_POSTS_PATH.write_text(
            json.dumps(ids, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("No se pudo guardar commented_post_ids: %s", e)


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
        self.max_comments_per_day = behavior.get("max_comments_per_day", 6)
        self.max_replies_per_cycle = behavior.get("max_comment_replies_per_cycle", 2)
        self.max_feed_comments_per_post = behavior.get("max_feed_comments_per_post", 1)
        self.delay_between_comments = behavior.get("delay_between_comments", 8)
        self._last_comment_per_thread: Dict[str, str] = {}
        self._replied_comment_ids: Set[str] = _load_replied_comment_ids()
        self._commented_post_ids: Dict[str, str] = _load_commented_post_ids()

    # ── Relevance layer ───────────────────────────────────────────

    _TECH_KEYWORDS = frozenset({
        "modelo", "llm", "agente", "pipeline", "latencia", "tokens", "api",
        "moltbook", "riobamba", "error", "fallo", "problema", "cómo", "como ",
        "funciona", "solución", "config", "implementar", "código", "debug",
        "monitoreo", "métrica", "rendimiento", "seguridad", "despliegue",
    })

    @staticmethod
    def _compute_relevance_score(comment: Dict[str, Any]) -> int:
        text = (comment.get("content") or comment.get("text") or "").strip()
        text_lower = text.lower()
        score = 0

        if "?" in text_lower:
            score += POLICY.relevance_boost_question

        mentions = {"@comet", "comet-riobamba", "comet_riobamba", "comet riobamba", "riobamba"}
        if any(m in text_lower for m in mentions):
            score += POLICY.relevance_boost_mention

        tech_count = sum(1 for kw in PhaseB._TECH_KEYWORDS if kw in text_lower)
        if tech_count >= 2:
            score += POLICY.relevance_boost_tech_keyword

        if len(text) < 10:
            score -= POLICY.relevance_penalty_short
        elif len(text) < 25:
            score -= POLICY.relevance_penalty_short // 2

        if any(k in text_lower for k in ("gracias", "thanks", "jaja", "lol", "👍", "❤️")):
            score -= 15

        if len(text) > 150:
            score += 5

        return max(0, min(score, 100))

    @staticmethod
    def _decide_reply(comment: Dict[str, Any], limit_ok: bool = True) -> RelevanceDecision:
        if not limit_ok:
            return RelevanceDecision(False, 0, "reply_skipped_limit_reached")

        text = (comment.get("content") or comment.get("text") or "").strip()
        text_lower = text.lower()
        if not text_lower:
            return RelevanceDecision(False, 0, "reply_skipped_low_relevance")

        score = PhaseB._compute_relevance_score(comment)

        if score >= POLICY.min_comment_relevance_score + 20:
            return RelevanceDecision(True, score, "reply_sent")

        if score >= POLICY.min_comment_relevance_score:
            mentions = {"@comet", "comet-riobamba", "comet_riobamba", "comet riobamba", "riobamba"}
            if any(m in text_lower for m in mentions) or "?" in text_lower:
                return RelevanceDecision(True, score, "reply_sent")

            if any(k in text_lower for k in ("error", "fallo", "problema", "cómo", "solución")):
                return RelevanceDecision(True, score, "reply_sent")

        # Check if this looks like an already-answered pattern
        muy_corto = len(text_lower) < 10
        solo_saludo = text_lower.strip() in {"hola", "hello", "hey", "hi", "buenas", "👍"}
        spam_like = any(k in text_lower for k in ("gana dinero", "sigue a", "visit", "check out"))

        if muy_corto or solo_saludo or spam_like:
            return RelevanceDecision(False, score, "reply_skipped_low_relevance")

        if score >= POLICY.min_comment_relevance_score:
            return RelevanceDecision(True, score, "reply_sent")
        return RelevanceDecision(False, score, "reply_skipped_low_relevance")

    @staticmethod
    def _decide_reply_from_post(post_body: str, comments: Optional[List[Dict]] = None) -> RelevanceDecision:
        if not post_body or len(post_body.strip()) < 20:
            return RelevanceDecision(False, 0, "reply_skipped_low_relevance")

        text_lower = post_body.lower()
        score = 0

        if "?" in text_lower:
            score += POLICY.relevance_boost_question

        tech_count = sum(1 for kw in PhaseB._TECH_KEYWORDS if kw in text_lower)
        score += min(tech_count * 10, 40)

        if len(post_body) > 100:
            score += 10
        if any(k in text_lower for k in ("error", "fallo", "problema", "cómo solucionar", "tutorial", "guía")):
            score += 20
        if any(k in text_lower for k in ("gana dinero", "sorteo", "promoción", "compra", "venta")):
            score -= 30

        # ── Frontier potential boost ─────────────────────────────
        # A post has high frontier potential if:
        #   - It is about a topic close to agent focus (tech keywords present)
        #   - It has substantive discussion (comments exist)
        #   - It lacks coverage of metrics/guardrails/failure modes
        if tech_count >= 2 and comments:
            all_comment_text = " ".join(
                (c.get("content") or c.get("text") or "").lower()
                for c in comments if isinstance(c, dict)
            )
            frontier_keywords = ["metric", "guardrail", "failure mode", "threshold",
                                "fallback", "observability", "rate limit"]
            frontier_mentioned = sum(1 for kw in frontier_keywords if kw in all_comment_text)
            if frontier_mentioned == 0:
                score += 20  # high frontier: no one has covered these angles yet
                reason_prefix = "frontier_opportunity"
            elif frontier_mentioned <= 2:
                score += 10  # moderate frontier: partially covered
                reason_prefix = "frontier_partial"
            else:
                reason_prefix = ""  # well-covered, no boost

        should = score >= POLICY.min_comment_relevance_score
        reason = "reply_sent" if should else "reply_skipped_low_relevance"
        return RelevanceDecision(should, score, reason)

    # ── Entrypoint ────────────────────────────────────────────────

    @phase_error_boundary(logger, "phase_b", fallback_return={"success": False, "replies_published": 0, "feed_replies": [], "own_post_replies": []})
    async def execute(self) -> Dict[str, Any]:
        feed_results: List[Dict[str, Any]] = []
        own_results: List[Dict[str, Any]] = []

        # Own-post replies first: consume the daily/cycle budget preferentially
        if self.deps.behavior_cfg.get("phase_b_own_post_replies", True):
            own_results = await self._execute_own_post_replies()

        own_count = len(own_results)
        remaining_cycle = max(0, self.max_replies_per_cycle - own_count)

        # Feed replies only with remaining budget
        if self.deps.behavior_cfg.get("phase_b_feed_replies", True):
            if self.get_comments_today() < self.max_comments_per_day and remaining_cycle > 0:
                feed_results = await self._execute_feed_replies(remaining_cycle_slots=remaining_cycle)
            else:
                logger.info(
                    "Phase B: skip feed replies — budget consumed by own-post replies "
                    "(daily=%s/%s, remaining_cycle=%s).",
                    self.get_comments_today(), self.max_comments_per_day, remaining_cycle,
                )

        feed_count = len(feed_results)
        total = own_count + feed_count
        logger.info(
            "Phase B: cycle summary — own-post replies=%s, feed replies=%s, total=%s",
            own_count, feed_count, total,
        )
        return {
            "success": total > 0,
            "replies_published": total,
            "feed_replies": feed_results,
            "own_post_replies": own_results,
        }

    # ── Anti-duplicate guard ────────────────────────────────────

    async def _check_and_prevent_duplicate(
        self, post_id: str, reply_text: str, attempt: int = 1
    ) -> Optional[str]:
        """Check if reply is near-duplicate of our last comment in this thread.
        If duplicate and attempt == 1, try one regeneration with stricter instruction.
        If duplicate and attempt >= 2, skip (return None)."""
        previous = self._last_comment_per_thread.get(post_id)
        if previous is None:
            self._last_comment_per_thread[post_id] = reply_text
            return reply_text

        if not is_near_duplicate_reply(reply_text, previous):
            self._last_comment_per_thread[post_id] = reply_text
            return reply_text

        logger.info(
            "Phase B: near-duplicate reply detected in thread %s (attempt %s)",
            post_id, attempt,
        )

        if attempt >= 2:
            logger.info("Phase B: skipping near-duplicate reply in thread %s", post_id)
            send_event("phase_b_duplicate_skip", {
                "post_id": post_id,
                "reason": "near_duplicate_after_regeneration",
            })
            return None

        # One re-generation with stricter instruction
        stricter = (
            "IMPORTANTE: El texto anterior es muy similar a tu comentario previo en este hilo. "
            "Reescribe desde cero: sé más breve, aporta algo nuevo y no repitas ideas ya expresadas."
        )
        try:
            new_reply = await self.llm.generate(
                tier="openrouter",
                prompt=f"{stricter}\n\nTexto original:\n{reply_text}",
                system_prompt=(
                    "You are a senior systems engineer. Do not repeat yourself. "
                    "Be concise and add new value. "
                    "Always respond in English. This is an English-speaking platform."
                ),
                max_tokens=120,
                temperature=0.8,
            )
            new_reply = (new_reply or "").strip()
            if not new_reply or is_near_duplicate_reply(new_reply, previous):
                logger.info("Phase B: re-generated reply also near-duplicate, skipping thread %s", post_id)
                send_event("phase_b_duplicate_skip", {
                    "post_id": post_id,
                    "reason": "near_duplicate_after_regeneration",
                })
                return None
            self._last_comment_per_thread[post_id] = new_reply
            return _safe_truncate(new_reply, max_chars=500)
        except Exception as e:
            logger.warning("Phase B: error re-generating to avoid duplicate: %s", e)
            return None

    # ── Feed replies (antes phase_b_replies.py) ───────────────────

    async def _execute_feed_replies(self, remaining_cycle_slots: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.llm:
            logger.warning("Phase B: model_cascade no disponible; se omiten feed replies.")
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
            return []

        max_feed = self.deps.behavior_cfg.get("max_feed_replies_per_day", POLICY.max_feed_replies_per_day)
        effective_cycle_limit = remaining_cycle_slots if remaining_cycle_slots is not None else self.max_replies_per_cycle
        logger.info(
            "Phase B: feed replies — remaining daily budget=%s/%s, cycle budget=%s, max_feed=%s",
            daily_comment_count, self.max_comments_per_day, effective_cycle_limit, max_feed,
        )
        # Track feed-specific counter separately from global daily count
        feed_comment_count = 0

        # Load roadmap for topic alignment
        roadmap = load_roadmap()
        roadmap_topics_lower = set(t.lower() for t in roadmap.all_topics())

        candidate_posts = self._fetch_candidate_posts(limit=50)
        candidate_posts = candidate_posts[:5]  # slightly larger pool for stricter selection

        if not candidate_posts:
            logger.info("Phase B: no se encontraron posts candidatos en el feed.")
            return []

        filtered_posts: List[Dict[str, Any]] = [
            p for p in candidate_posts if self._can_comment_in_thread(p)
        ]

        if not filtered_posts:
            logger.info("Phase B: todos los hilos candidatos ya tienen suficientes comentarios del agente.")
            return []

        # Score and rank by roadmap alignment
        scored_posts: List[tuple] = []
        for post in filtered_posts:
            post_body = (post.get("content") or post.get("body") or post.get("title") or "").strip()
            post_comments = post.get("comments") or []
            post_decision = self._decide_reply_from_post(post_body, comments=post_comments)
            if not post_decision.should_reply:
                continue
            # Roadmap alignment boost
            post_text_lower = post_body.lower()
            if any(rt in post_text_lower for rt in roadmap_topics_lower):
                post_decision = RelevanceDecision(
                    should_reply=True,
                    score=min(post_decision.score + 15, 100),
                    reason=post_decision.reason,
                )
            # Stricter threshold for feed replies: require score >= min + 10
            # (reduced during cold start when posts_today < COLD_START_POST_THRESHOLD)
            if post_decision.score < _get_feed_min_score(getattr(self.deps, 'posts_today', 0)):
                continue
            scored_posts.append((post_decision.score, post))

        scored_posts.sort(key=lambda x: -x[0])  # highest score first

        if not scored_posts:
            logger.info("Phase B: ningún post del feed superó el umbral de relevancia estratégica.")
            return []

        logger.info("Phase B: %s posts seleccionados de %s candidatos por relevancia y roadmap.",
                     len(scored_posts), len(filtered_posts))

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
            if post_id in self._commented_post_ids:
                logger.info("Phase B: post %s ya comentado en ciclo anterior, saltando", post_id)
                continue

            post_body = (post.get("content") or post.get("body") or post.get("title") or "").strip()
            post_comments = post.get("comments") or []
            post_decision = self._decide_reply_from_post(post_body, comments=post_comments)
            if not post_decision.should_reply:
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

            try:
                reply_text = await self._generate_reply_for_post(post)
            except Exception as e:
                logger.warning(f"Phase B: error generando respuesta: {e}")
                continue

            reply_text = (reply_text or "").strip()
            if not reply_text:
                continue

            reply_text = await self._check_and_prevent_duplicate(post_id, reply_text)
            if reply_text is None:
                continue

            try:
                resp = self.api.create_comment(post_id=str(post_id), content=reply_text)
            except Exception as e:
                logger.error(f"Phase B: error posting feed reply to post {post_id}: {e}")
                enqueue_outbox("comment", {"post_id": post_id, "content": reply_text, "parent_comment_id": None})
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
                    await self._classify_and_log_value(post, post_body, reply_text, str(comment_id))

                # Add topic to research agenda if frontier potential detected
                if post_decision.score >= POLICY.min_comment_relevance_score + 20:
                    self._add_topic_to_agenda(post, post_body)

                self._commented_post_ids[post_id] = datetime.now().isoformat()
                _save_commented_post_ids(self._commented_post_ids)

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
        try:
            resp: APIResponse = self.api.get_feed(limit=limit, sort="hot")
            if not getattr(resp, "success", False):
                logger.warning(
                    "Phase B: get_feed falló status=%s error=%s",
                    getattr(resp, "status", None) or getattr(resp, "status_code", None),
                    getattr(resp, "error", None),
                )
                return []

            data = getattr(resp, "data", None)
            if isinstance(data, dict):
                posts = data.get("posts", [])
            elif isinstance(data, list):
                posts = data
            else:
                posts = []

            if not isinstance(posts, list):
                logger.warning("Phase B: estructura inesperada en get_feed.")
                return []

            filtered: List[Dict[str, Any]] = []
            for p in posts:
                if not isinstance(p, dict):
                    continue
                raw_sub = p.get("submolt") or p.get("community") or ""
                sub = str(raw_sub).strip().lower()
                if sub in BLOCKED_SUBMOLTS:
                    logger.debug("Phase B: post %s descartado: submolt bloqueado '%s'", p.get("id"), sub)
                    continue
                filtered.append(p)

            logger.info(
                "Phase B: %s posts candidatos (total_feed=%s).",
                len(filtered),
                len(posts),
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

    async def _generate_reply_for_post(self, post: Dict[str, Any]) -> str:
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
            "You are a senior systems engineer. "
            "Do not be promotional. Do not use emojis, hashtags, links, or markdown. "
            "You MUST add concrete value. Do NOT repeat what was already said.\n\n"
            "Your comment MUST contribute at least ONE of:\n"
            "  - A distinct metric or threshold\n"
            "  - A concrete guardrail or validation pattern\n"
            "  - A real failure mode not yet discussed\n"
            "  - A clear research question\n\n"
            f"{lang_instruction}\n\n"
            f"{COMMENT_STYLE_INSTRUCTIONS}"
        )

        user_prompt = f"""
Reply to the following post with one concise technical comment.

Author: {author}
Title: {title}
Post:
{body[:1200]}

Requirements:
- 40 to 90 words.
- Sound like an engineer, not a marketer.
- Add one concrete technical observation, trade-off, or failure mode.
- Do not repeat the post.
- Do not mention Moltbook, prompts, or models.
- End with a complete statement, not a question.
- Write original wording to avoid repeating previous comments verbatim.
""".strip()

        if not self.llm:
            return ""
        try:
            reply = await self.llm.generate(
                tier="openrouter",
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=180,
                temperature=0.7,
            )
            reply = (reply or "").strip()
            return _safe_truncate(reply, max_chars=500)
        except Exception as e:
            logger.warning(f"Phase B: error en generación de reply: {e}")
            return ""

    # ── Value classification ──────────────────────────────────────

    async def _classify_and_log_value(
        self,
        post: Dict[str, Any],
        comment_text: str,
        reply_text: str,
        comment_id: str,
        follow_up: str = "",
    ) -> None:
        if not self.llm:
            return
        post_text = f"{post.get('title', '')}\n{post.get('content', '') or post.get('body', '')}"
        try:
            system_prompt, user_prompt = build_classifier_prompt(
                post=post_text, comment=comment_text, reply=reply_text, follow_up=follow_up,
            )
            raw = await self.llm.generate(
                tier="openrouter",
                prompt=user_prompt,
                system_prompt=(
                    "Always respond in English. This is an English-speaking platform.\n\n"
                    f"{system_prompt}"
                ),
                max_tokens=300,
                temperature=0.3,
            )
            raw = (raw or "").strip()
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.lower().startswith("json"):
                    raw = raw[4:].strip()
            data = json.loads(raw)
            classification = data.get("clasificacion_valor", "baja_relevancia")
            if classification not in ("resolvio_problema", "aporte_util"):
                return
            from datetime import datetime
            ts = datetime.now().isoformat()
            post_id = str(post.get("id") or "")
            event = {
                "id": f"{ts}-{post_id}-{comment_id}",
                "timestamp": ts,
                "post_id": post_id,
                "comment_id": comment_id,
                "user_id": str(post.get("author") or post.get("username", "")),
                "tema": data.get("tema", ""),
                "tipo_problema": data.get("tipo_problema", ""),
                "clasificacion_valor": classification,
                "senales_usuario": data.get("senales_usuario", []),
                "resumen_problema": data.get("resumen_problema", ""),
                "resumen_solucion": data.get("resumen_solucion", ""),
            }
            log_value_event(event)
        except Exception as e:
            logger.debug("ValueLog: error clasificando valor en post %s: %s", post.get("id"), e)

    # ── Own post replies (antes phase_b_responses.py) ─────────────

    async def _execute_own_post_replies(self) -> List[Dict[str, Any]]:
        if not self.llm:
            logger.warning("Phase B: model_cascade no disponible; se omiten own post replies.")
            return []

        try:
            posts = self.api.fetch_my_posts()
        except Exception as e:
            logger.error(f"Phase B: error fetching my posts: {e}")
            return []

        if not posts:
            logger.info("Phase B: no published posts found")
            return []

        candidate_posts = list(posts)[:3]
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

        return results

    async def _process_own_post(self, post_id: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        if is_thread_closed(post_id):
            logger.info("Phase B: thread %s cerrado, saltando.", post_id)
            return []

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

        try:
            comments = self.api.fetch_post_comments(post_id)
        except Exception as e:
            logger.error(f"Phase B: error fetching comments for post {post_id}: {e}")
            return []

        if not comments:
            logger.info(f"Phase B: no comments on post {post_id}")
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

        replied_count = 0

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
            dedup_key = f"{post_id}:{comment_id}"
            if dedup_key in self._replied_comment_ids:
                logger.info("Phase B: skip comment %s on post %s (already replied).", comment_id, post_id)
                continue
            if not comment_text.strip():
                logger.info(f"Phase B: empty comment {comment_id} on post {post_id}, skipping")
                continue
            decision = self._decide_reply(comment, limit_ok=replied_count < self.max_comments_per_post)
            if not decision.should_reply:
                send_event("phase_b_reply_skip", {
                    "post_id": post_id,
                    "comment_id": comment_id,
                    "reason": decision.reason,
                    "score": decision.score,
                    "snippet": comment_text[:60],
                })
                continue

            result = await self._post_own_reply(post_id, comment_id, author, comment_text)
            if result is None:
                continue

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
                        if dedup_key in self._replied_comment_ids:
                            logger.info("Phase B: debate continuation: comment %s on post %s already replied, skipping.", other_id, post_id)
                        elif self.get_comments_today() < self.max_comments_per_day:
                            result = await self._post_own_reply(post_id, other_id, other_author, other_text)
                            if result:
                                replied_count += 1
                                register_agent_reply(post_id)
                                results.append(result)

        if not results:
            logger.info("Phase B: no se respondió a ningún comentario en posts propios.")

        return results

    async def _post_own_reply(self, post_id: str, comment_id: str, author: str,
                              comment_text: str) -> Optional[Dict[str, Any]]:
        """Generate and post a reply to a comment on our own post. Returns result dict or None on failure."""
        dedup_key = f"{post_id}:{comment_id}"
        if dedup_key in self._replied_comment_ids:
            logger.info("Phase B: skip reply to comment %s on post %s (already replied, dedup).", comment_id, post_id)
            send_event("phase_b_duplicate_skip", {
                "post_id": post_id,
                "comment_id": comment_id,
                "reason": "already_replied_comment_id",
            })
            return None

        try:
            reply_text = await self._generate_own_post_reply(author, comment_text)
        except Exception as e:
            logger.error(f"Phase B: LLM error for comment {comment_id} on post {post_id}: {e}")
            return None

        if not reply_text:
            return None

        reply_text = await self._check_and_prevent_duplicate(post_id, reply_text)
        if reply_text is None:
            return None

        try:
            result = self.api.create_comment(
                post_id=post_id,
                parent_comment_id=comment_id,
                content=reply_text,
            )
        except Exception as e:
            logger.error(f"Phase B: error posting reply to comment {comment_id}: {e}")
            enqueue_outbox("comment", {"post_id": post_id, "content": reply_text, "parent_comment_id": comment_id})
            return None

        success = result.get("success", False) if isinstance(result, dict) else getattr(result, "success", False)
        already_existed = result.get("already_existed", False) if isinstance(result, dict) else getattr(result, "already_existed", False)
        error = result.get("error") if isinstance(result, dict) else getattr(result, "error", None)

        if success and already_existed:
            logger.info(
                "Phase B: reply to comment %s on post %s already existed (dedup), not counting.",
                comment_id, post_id,
            )
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
            _save_replied_comment_ids(self._replied_comment_ids)
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
            )
            logger.info(
                "Phase B: replied to comment %s on post %s",
                comment_id, post_id,
            )
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

    def _should_reply_to_comment(self, comment: dict) -> bool:
        text = (comment.get("content") or comment.get("text") or "").lower()
        if not text:
            return False

        mention_keywords = [
            "@comet",
            "@comet-riobamba",
            "comet riobamba",
            "comet-riobamba",
        ]
        if any(k in text for k in mention_keywords):
            return True

        if "?" in text:
            return True

        tech_keywords = [
            "modelo",
            "llm",
            "agente",
            "pipeline",
            "latencia",
            "tokens",
            "api",
            "moltbook",
            "riobamba",
        ]
        if any(k in text for k in tech_keywords):
            return True

        return False

    # ── Research agenda helpers ───────────────────────────────────

    def _add_topic_to_agenda(self, post: Dict[str, Any], post_body: str) -> None:
        """Register a high-relevance thread's topic in the research agenda
        so Phase A can write a dedicated post about it later."""
        try:
            from services.research_agenda import load_agenda, save_agenda
            agenda = load_agenda()
            title = str(post.get("title") or post_body[:80] or "Untitled")
            tags = []
            text_lower = (title + " " + post_body).lower()
            if any(kw in text_lower for kw in ("agent", "tool", "loop", "orquest")):
                tags.append("agents")
            if any(kw in text_lower for kw in ("metric", "eval", "score", "benchmark")):
                tags.append("metrics")
            if any(kw in text_lower for kw in ("fail", "error", "crash", "bug", "break")):
                tags.append("failure_modes")
            if any(kw in text_lower for kw in ("security", "safety", "guardrail", "permission")):
                tags.append("safety")
            agenda.add_topic(title, source=f"phase_b_feed:{post.get('id', 'unknown')}", tags=tags)
            save_agenda(agenda)
            logger.debug("Phase B: added topic '%s' to research agenda.", title[:60])
        except Exception as e:
            logger.debug("Phase B: could not update research agenda: %s", e)

    async def _generate_own_post_reply(self, author: str, comment_text: str) -> str:
        lang_instruction = (
            "Always respond in English. This is an English-speaking platform."
        )
        user_prompt = (
            f"Reply briefly and helpfully to the following comment by @{author}: "
            f"\"{comment_text}\""
        )

        system_prompt = (
            "You are a senior systems engineer. "
            "Reply concisely and helpfully. "
            "Do not use emojis, hashtags, or markdown.\n\n"
            f"{lang_instruction}\n\n"
            f"{COMMENT_STYLE_INSTRUCTIONS}"
        )
        try:
            reply = await self.llm.generate(
                tier="openrouter",
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=180,
                temperature=0.7,
            )
            reply = (reply or "").strip()
            return _safe_truncate(reply, max_chars=500)
        except Exception as e:
            logger.warning(f"Phase B: error en generación de own post reply: {e}")
            return ""
