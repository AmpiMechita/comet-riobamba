# -*- coding: utf-8 -*-
"""Phase B scoring - relevance decisions, feed thresholds, and reply quality helpers.

Expanded from the original scoring.py with methods extracted from
orchestrator.py as part of the incremental refactor (Phase 3).
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from config.agent_policy import POLICY
from .constants import (
    _COLD_START_MIN_SCORE,
    _COLD_START_THRESHOLD,
    _cold_start_lock,
)
from . import constants as _constants_mod
from services import reply_cap as _reply_cap

logger = logging.getLogger("phases.phase_b")

# ── Anti-fabrication guard ──────────────────────────────────────
# Rejects text that combines first-person measurement claims with
# numbers — the agent has NO production systems and runs NO experiments.
# Ampliado (v5.4): cubre verbos de observación/medición coloquiales
# (pulled, saw, found, hit, logged, counted, watched, caught, shipped)
# que el patrón original no veía ("We pulled 1,035 comments").
_FABRICATION_PATTERN = re.compile(
    r"\b(we|i)\s+(measured|benchmarked|ran|tested|observed|deployed|tracked"
    r"|pulled|saw|found|hit|logged|counted|watched|caught|shipped)\b"
    r"|\bin (our|my) (tests?|runs?|production|deployment|experience)\b"
    r"|\bin production we\b",
    re.IGNORECASE,
)
_HAS_DIGIT = re.compile(r"\b\d+[%]?\b")

# Cifras/métricas explícitas (número + unidad/%): el interlocutor expone
# datos medidos. Si el comentario las trae, la respuesta del agente debe
# estar 100% anclada (block_ungrounded) antes de publicarse.
_NUMERIC_UNIT_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|percent|ms|msec|s|sec|secs|seconds?|mins?|minutes?|"
    r"hours?|days?|times?|counts?|replies?|posts?|upvotes?|karma|kg|m|km|meters?|"
    r"watts?|nm|gb|tb|request|requests|qps|rps|users?)(?!\w)",
    re.IGNORECASE,
)


def text_exposes_figures(text: str) -> bool:
    """True si el texto contiene cifras concretas (números con unidades/%).
    Se usa para activar el block_ungrounded: si el interlocutor expone cifras,
    la respuesta del agente no puede publicarse con números sin ancla."""
    if not text:
        return False
    return bool(_NUMERIC_UNIT_RE.search(text))


# ── Gate temático: solo comentarios con referencia al post ──────
# Política vigente: solo se atienden comentarios que se refieren al tema
# del post en cuestión y aportan información (verificable). Comentarios
# off-topic (sin solapamiento temático con el post) se ignoran incluso en
# posts propios: la relación compra prioridad, no relevancia.

_TOPIC_BRIDGE_WORDS = frozenset({
    "this", "that", "these", "those", "it", "its", "here", "then",
    "point", "points", "idea", "idea", "question", "elaborate", "explain",
    "clarify", "example", "examples", "agree", "disagree", "correct",
    "wrong", "true", "false", "yes", "no", "really",
})


def comment_off_topic(comment_text: str, post_text: str) -> bool:
    """True si el comentario NO se refiere al tema del post.

    Regla: intersección de términos significativos (≥5 chars, sin stopwords)
    entre el comentario y el post. Palabras puente ("this", "point",
    "elaborate") no cuentan como referencia temática: un comentario que solo
    dice "can you elaborate?" sin anclar al tema del post es off-topic.

    post_text vacío → None se devuelve False (fail-open: sin texto del post
    no se puede medir tema, no se filtra)."""
    if not post_text or not comment_text:
        return False
    comment_terms = _extract_source_terms(comment_text)
    if not comment_terms:
        return True
    post_terms = _extract_source_terms(post_text)
    if not post_terms:
        return False
    overlap = comment_terms & post_terms
    return not bool(overlap)


def text_has_fabricated_measurement(text: str, is_own_incident: bool = False) -> bool:
    """Return True if text claims a first-person measurement and contains a number.

    is_own_incident=True exime del guard: el modo own_incident de Phase A
    escribe sobre incidentes REALES del propio sistema con numeros verificados
    del store (data/incidents.jsonl); su primera persona esta respaldada. Todo
    lo demas (rotacion, arxiv, watchlist_pairing, EIN) mantiene el guard activo."""
    if is_own_incident:
        return False
    if not text or not _HAS_DIGIT.search(text):
        return False
    return bool(_FABRICATION_PATTERN.search(text))


# ── Gate de citas historicas ────────────────────────────────────
# COMET solo puede invocar un hecho fechado (año 19xx/20xx) si esta GROUNDED
# en el contexto provisto: incidentes propios, paper/fuente del prompt, o algo
# que el interlocutor menciono. Un año sin fuente en el contexto es un
# incidente historico de terceros con detalles no verificables.
_HISTORICAL_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def extract_historical_years(text: str) -> Set[str]:
    """Años 19xx/20xx presentes en el texto."""
    if not text:
        return set()
    return set(_HISTORICAL_YEAR_RE.findall(text))


def text_has_unverifiable_historical_claim(text: str, context: str,
                                           is_own_incident: bool = False) -> Optional[str]:
    """Devuelve el primer año del texto que NO esta en el contexto, o None.

      Gate estricto para feed y own-posts: cualquier año no en contexto = rechazado.
      is_own_incident NO exime de citar incidentes de terceros sin ground.
    Para feed posts, mantiene gate estricto (any year not in context)."""
    if not text:
        return None
    
    years = extract_historical_years(text)
    if not years:
        return None
    
      # Gate estricto: cualquier año no en contexto = rechazado
      # is_own_incident NO exime de citar incidentes de terceros sin ground
    context_years = extract_historical_years(context or "")
    missing = years - context_years
    return sorted(missing)[0] if missing else None


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
    if not text or len(text.strip()) < 40:
        return False
    text_lower = text.lower()
    low_value_count = sum(1 for s in LOW_VALUE_SIGNALS if s in text_lower)
    if low_value_count >= 2:
        return False
    science_count = sum(1 for s in SCIENCE_SIGNALS if s in text_lower)
    if len(text.strip()) < 200:
        return science_count >= 2
    else:
        return science_count >= 1


# ── Comment-level relevance scoring (extracted from orchestrator) ──

def _compute_relevance_score(
    comment: Dict[str, Any],
    *,
    tech_keywords: frozenset = frozenset(),
) -> int:
    text = (comment.get("content") or comment.get("text") or "").strip()
    text_lower = text.lower()
    score = 0

    if "?" in text_lower:
        score += POLICY.relevance_boost_question

    mentions = {"@comet", "comet-riobamba", "comet_riobamba", "comet riobamba", "riobamba"}
    if any(m in text_lower for m in mentions):
        score += POLICY.relevance_boost_mention

    tech_count = sum(1 for kw in (tech_keywords or frozenset()) if kw in text_lower)
    if tech_count >= 2:
        score += POLICY.relevance_boost_tech_keyword

    if len(text) < 10:
        score -= POLICY.relevance_penalty_short
    elif len(text) < 25:
        score -= POLICY.relevance_penalty_short // 2

    if any(k in text_lower for k in ("gracias", "thanks", "jaja", "lol", "\U0001f44d", "\u2764\ufe0f")):
        score -= 15

    if len(text) > 150:
        score += 5

    return max(0, min(score, 100))


def _triage_comment_value(
    comment_text: str,
    *,
    tech_keywords: frozenset = frozenset(),
    author=None,
):
    """Pre-filter: descarta comentarios que NO merecen respuesta,
    independientemente de si el agente podría reencuadrarlos.
    Solo bloquea cuando TODAS las señales son negativas:
    demasiado corto, sin pregunta ni crítica, Y off-niche.
    Excepción: interlocutores recurrentes (count >= 3) NO son
    descartados por longitud — la relación compra esfuerzo pero
    NO compra un pase a off-niche.
    Returns (skip: bool, reason: str)."""
    if not comment_text or not isinstance(comment_text, str):
        return True, "empty_or_invalid"
    text = comment_text.strip()
    text_lower = text.lower()

    too_short = len(text) < 80

    has_question = "?" in text_lower
    has_critique = any(k in text_lower for k in (
        "error", "fallo", "fail", "bug", "break", "broke", "wrong",
        "incorrect", "should not", "how", "why", "what", "can you",
        "does not work", "problem", "issue",
    ))
    no_signal = not has_question and not has_critique

    tech_count = sum(1 for kw in (tech_keywords or frozenset()) if kw in text_lower)
    off_niche = tech_count == 0

    # ── Bypass: interlocutor recurrente no se descarta por longitud ──
    # (la relación compra esfuerzo, no relevancia temática)
    if author is not None and too_short:
        try:
            from services import interlocutors as _interlocutors
            count = _interlocutors.get_interaction_count(author)
        except Exception:
            count = 0
        if count >= 3:
            # Si además es on-niche, no se descarta.
            # Si es off-niche, sí (la relación no compra off-niche).
            if not off_niche:
                return False, ""
            # off_niche: cae al check normal

    if too_short and no_signal and off_niche:
        return True, "low_value_triage"

    return False, ""


# ── Watchlist authors (loaded from phase_b_strategy.yaml) ─────────
_WATCHLIST_AUTHORS: Set[str] = set()


def set_watchlist_authors(authors: Set[str]) -> None:
    global _WATCHLIST_AUTHORS
    _WATCHLIST_AUTHORS = authors


def _extract_author_name(post: Dict[str, Any]) -> str:
    author_value = post.get("author") if isinstance(post, dict) else None
    if isinstance(author_value, dict):
        return str(author_value.get("name") or "").strip().lower()
    return str(author_value or "").strip().lower()


def _compute_visibility_bonus(post: Optional[Dict[str, Any]], author: Optional[str] = None) -> int:
    """Bonus por velocidad de engagement + penalizacion por saturacion.

    - Detecta la edad del post via 'created_at', 'published_at', 'createdAt',
      'timestamp' (ISO 8601). Si no hay fecha → bonus 0 (fail-safe).
    - velocity = comment_count / max(age_minutes, 1)
    - Bonus: +15 si velocity >= 1.0, +10 si >= 0.3, +5 si >= 0.1
    - Early-bird: +5 adicional si age_minutes <= 30
    - Penalizacion por saturacion:
        -10 si comment_count > 150
        -20 si comment_count > 400
    - Watchlist: +25 si autor en watchlist y age_minutes <= 30,
      +10 si autor en watchlist y post mas viejo.
    - El total se clamp a >= 0 para no romper el umbral de relevancia.
    - Se aplica SOLO tras pasar el umbral on-niche (el caller lo garantiza).
    """
    if not isinstance(post, dict):
        return 0

    comment_count = _extract_comment_count(post)

    age_minutes = _extract_age_minutes(post)
    if author is None:
        author = _extract_author_name(post)

    bonus = 0

    # ── Watchlist bonus (first: newborn posts from top authors) ──
    is_watchlist = author and author in _WATCHLIST_AUTHORS
    if is_watchlist and age_minutes is not None:
        if age_minutes <= 30:
            bonus += 25
        else:
            bonus += 10
    elif is_watchlist:
        bonus += 10

    if age_minutes is None:
        return max(0, bonus)

    velocity = comment_count / max(age_minutes, 1)
    if velocity >= 1.0:
        bonus += 15
    elif velocity >= 0.3:
        bonus += 10
    elif velocity >= 0.1:
        bonus += 5

    if age_minutes <= 30:
        bonus += 5

    if comment_count > 400:
        bonus -= 20
    elif comment_count > 150:
        bonus -= 10

    return max(0, bonus)


def _extract_comment_count(post: Dict[str, Any]) -> int:
    for k in ("comment_count", "comments_count"):
        v = post.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    if isinstance(post.get("comments"), list):
        return len(post["comments"])
    if isinstance(post.get("commentCount"), (int, float)):
        return int(post["commentCount"])
    return 0


def _extract_age_minutes(post: Dict[str, Any]) -> Optional[float]:
    from datetime import datetime, timezone
    ts_raw = None
    for key in ("created_at", "published_at", "createdAt", "timestamp"):
        ts_raw = post.get(key)
        if ts_raw:
            break
    if not ts_raw:
        return None
    try:
        ts_str = str(ts_raw).replace("Z", "+00:00")
        post_dt = datetime.fromisoformat(ts_str)
        if post_dt.tzinfo is None:
            post_dt = post_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0.0, (now - post_dt).total_seconds() / 60.0)
    except Exception:
        return None


def _compute_relationship_bonus(author) -> int:
    """Bonus escalonado por historial de interlocutor (cross-session).

    +5 si count >= 3, +10 si count >= 10.
    Aplica SOLO después del umbral de relevancia (nunca rescata
    off-niche: la relación compra prioridad, no relevancia).
    Fail-open (count=0 si hay error)."""
    if not author:
        return 0
    try:
        from services import interlocutors as _interlocutors
        count = _interlocutors.get_interaction_count(author)
    except Exception:
        return 0
    if count >= 10:
        return 10
    if count >= 3:
        return 5
    return 0


def _decide_reply(
    pb,
    comment: Dict[str, Any],
    limit_ok: bool = True,
    is_own_post_reply: bool = False,
    *,
    tech_keywords: frozenset = frozenset(),
    post_text: str = "",
):
    if not limit_ok:
        return RelevanceDecision(False, 0, "reply_skipped_limit_reached")

    text = (comment.get("content") or comment.get("text") or "").strip()
    text_lower = text.lower()
    if not text_lower:
        return RelevanceDecision(False, 0, "reply_skipped_low_relevance")

    # ── Gate temático (política vigente): SOLO comentarios con referencia
    # al tema del post en cuestión. Off-topic se ignora incluso en posts
    # propios — la relación compra prioridad, no relevancia. Aplica también
    # a preguntas: una pregunta sin referencia al tema principal no se atiende.
    if post_text and comment_off_topic(text, post_text):
        logger.info("Phase B: comentario de %s off-topic (sin referencia al tema del post), ignorando.",
                    pb._get_author_name(comment))
        return RelevanceDecision(False, 0, "reply_skipped_off_topic")

    is_question = "?" in text_lower
    is_mention = any(m in text_lower for m in {
        "@comet", "comet-riobamba", "comet_riobamba", "comet riobamba", "riobamba"
    })

    high_density = pb._passes_density_gate(text_lower)
    if not (is_question or is_mention or is_own_post_reply):
        if not high_density:
            author = pb._get_author_name(comment)
            # Regla de alto valor (b): un comentario de un autor watchlist o con
            # historial de interacción real se RESPONDE aunque la densidad sea
            # baja — es un interlocutor con capital de relación, no ruido.
            comment_author = comment.get("author") if isinstance(comment, dict) else None
            is_high_value = False
            try:
                if author and author in _WATCHLIST_AUTHORS:
                    is_high_value = True
            except Exception:
                pass
            if not is_high_value and comment_author is not None:
                try:
                    if _compute_relationship_bonus(comment_author) >= 5:
                        is_high_value = True
                except Exception:
                    pass
            if not is_high_value:
                logger.info("Phase B: Ignorando comentario de %s por baja densidad semantica (sin metricas/estructuras).", author)
                return RelevanceDecision(False, 0, "reply_skipped_low_density")
            logger.info("Phase B: Comentario de %s (alto valor) responde pese a baja densidad.", author)

    score = _compute_relevance_score(comment, tech_keywords=tech_keywords)

    bypass_applied = False
    if is_own_post_reply:
        score = max(score, 60)
        bypass_applied = True
    elif high_density:
        score = max(score, 30)
        bypass_applied = True

    # ── Hard-filter de ruido puro (aplica incluso con bypass own-post) ──
    # Regla (c) refinada: un comentario de calidad menor al post no se responde,
    # ni siquiera en post propio. Spam, saludos, y 'me gusta' vacíos son ruido.
    muy_corto = len(text_lower) < 10
    solo_saludo = text_lower.strip() in {"hola", "hello", "hey", "hi", "buenas", "\U0001f44d"}
    # v5.6+: spam solo si el comentario es CORTO y con intención promocional
    # explícita. "check out"/"visit" aislados en una discusión técnica larga
    # son contenido legítimo (falso positivo real: post 6d55a569, score=60).
    _spam_intent = ("gana dinero", "sigue a", "sorteo", "promocion", "compra",
                    "venta", "visita mi", "check out my", "visit my", "check out this")
    spam_like = len(text_lower) < 100 and any(k in text_lower for k in _spam_intent)
    if (muy_corto or solo_saludo or spam_like) and bypass_applied:
        logger.info("Phase B: ruido puro ignorado pese a own-post/high-density (len=%d).", len(text_lower))
        return RelevanceDecision(False, score, "reply_skipped_low_relevance")

    if bypass_applied:
        author_name = pb._get_author_name(comment)
        logger.info("Phase B: Bypass de relevancia aplicado a %s por alta densidad tecnica / own-post reply.", author_name)
        if score >= 30:
            # ── Relationship bonus: prioriza ranking entre los que ya califican ──
            comment_author = comment.get("author") if isinstance(comment, dict) else None
            if comment_author is not None:
                rel = _compute_relationship_bonus(comment_author)
                if rel:
                    score = min(score + rel, 100)
            return RelevanceDecision(True, score, "reply_sent")

    # ── Relationship bonus: solo si el score base ya pasa el umbral ──
    # mismo patrón que visibility: nunca rescata off-niche.
    comment_author = comment.get("author") if isinstance(comment, dict) else None
    if score >= POLICY.min_comment_relevance_score and comment_author is not None:
        rel = _compute_relationship_bonus(comment_author)
        if rel:
            score = min(score + rel, 100)

    if score >= POLICY.min_comment_relevance_score + 20:
        return RelevanceDecision(True, score, "reply_sent")

    if score >= POLICY.min_comment_relevance_score:
        mentions = {"@comet", "comet-riobamba", "comet_riobamba", "comet riobamba", "riobamba"}
        if any(m in text_lower for m in mentions) or "?" in text_lower:
            return RelevanceDecision(True, score, "reply_sent")
        if any(k in text_lower for k in ("error", "fallo", "problema", "como", "solucion")):
            return RelevanceDecision(True, score, "reply_sent")

    muy_corto = len(text_lower) < 10
    solo_saludo = text_lower.strip() in {"hola", "hello", "hey", "hi", "buenas", "\U0001f44d"}
    _spam_intent = ("gana dinero", "sigue a", "sorteo", "promocion", "compra",
                    "venta", "visita mi", "check out my", "visit my", "check out this")
    spam_like = len(text_lower) < 100 and any(k in text_lower for k in _spam_intent)

    if muy_corto or solo_saludo or spam_like:
        return RelevanceDecision(False, score, "reply_skipped_low_relevance")

    if score >= POLICY.min_comment_relevance_score:
        return RelevanceDecision(True, score, "reply_sent")
    return RelevanceDecision(False, score, "reply_skipped_low_relevance")


def _decide_reply_from_post(
    post_body: str,
    comments: Optional[List[Dict]] = None,
    *,
    tech_keywords: frozenset = frozenset(),
    post: Optional[Dict[str, Any]] = None,
):
    if not post_body or len(post_body.strip()) < 20:
        return RelevanceDecision(False, 0, "reply_skipped_low_relevance")

    logger.info("Phase B: _decide_reply_from_post body_len=%s body_preview=%s", len(post_body), post_body[:80])
    text_lower = post_body.lower()
    score = 0

    if "?" in text_lower:
        score += POLICY.relevance_boost_question

    tech_count = sum(1 for kw in (tech_keywords or frozenset()) if kw in text_lower)
    score += min(tech_count * 10, 40)

    if len(post_body) > 100:
        score += 10
    if any(k in text_lower for k in ("error", "fallo", "problema", "como solucionar", "tutorial", "guia")):
        score += 20
    if any(k in text_lower for k in ("gana dinero", "sorteo", "promocion", "compra", "venta")):
        score -= 30

    if tech_count >= 2 and comments:
        all_comment_text = " ".join(
            (c.get("content") or c.get("text") or "").lower()
            for c in comments if isinstance(c, dict)
        )
        frontier_keywords = ["metric", "guardrail", "failure mode", "threshold",
                            "fallback", "observability", "rate limit"]
        frontier_mentioned = sum(1 for kw in frontier_keywords if kw in all_comment_text)
        if frontier_mentioned == 0:
            score += 20
        elif frontier_mentioned <= 2:
            score += 10

    # Visibility bonus (upvotes + comment_count): desempate y priorizacion
    # para que los posts activos consuman el presupuesto primero.
    # NUNCA rescata posts off-niche (el post YA debe pasar el umbral base).
    should = score >= 2
    if should and post:
        author = _extract_author_name(post)
        bonus = _compute_visibility_bonus(post, author=author)
        if bonus:
            score += bonus
        # Relationship bonus (autor recurrente): prioriza interlocutores
        # conocidos. También aplicado tras el umbral base, mismo patrón.
        rel = _compute_relationship_bonus(post.get("author"))
        if rel:
            score += rel

    reason = "reply_sent" if should else "reply_skipped_low_relevance"
    return RelevanceDecision(should, score, reason)


def _has_explicit_addressing(text: str) -> bool:
    text_lower = (text or "").lower()
    return any(k in text_lower for k in (
        "@comet", "@comet-riobamba", "comet riobamba", "comet-riobamba",
        "riobamba",
    ))


def _extract_source_terms(text: str) -> Set[str]:
    words = {
        w.lower()
        for w in re.findall(r"[a-zA-Z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\u00fc]{5,}", text or "")
    }
    return {
        w for w in words
        if w not in {
            "therefore", "because", "should", "could", "would", "about",
            "their", "there", "these", "those", "which", "while", "where",
            "reply", "comment", "post", "guardrail", "failure", "metric",
        }
    }


def _reply_mentions_source_terms(reply_text: str, source_text: str) -> bool:
    reply_lower = (reply_text or "").lower()
    source_terms = _extract_source_terms(source_text)
    if not source_terms:
        return True
    return any(term in reply_lower for term in list(source_terms)[:10])


def _reply_has_ungrounded_numeric_specificity(reply_text: str, source_text: str) -> bool:
    text = (reply_text or "").lower()
    source = (source_text or "").lower()
    numeric_pattern = re.compile(
        r"\b\d+(?:\.\d+)?\s*(?:ms|msec|s|sec|secs|seconds?|mins?|minutes?|%|percent|"
        r"times?|count|counts|replies?|posts?|days?|hours?)(?:\b|(?=\s|[.,;!?]|$))"
    )
    if not numeric_pattern.search(text):
        return False
    grounding_tokens = (
        "telemetry", "metric", "metrics", "benchmark", "benchmarks",
        "p95", "p99", "count", "counts", "sample", "samples",
    )
    grounding_token_patterns = [
        re.compile(rf"\b{re.escape(tok)}\b") for tok in grounding_tokens
    ]
    # Grounding literal: si el numero (con su unidad) del reply aparece en la
    # fuente, el reply lo cita del post y NO es fabricacion.
    if any(
        token.lower() in source
        for token in (m.group(0) for m in numeric_pattern.finditer(text))
    ):
        return False
    return not any(
        gt.search(source) for gt in grounding_token_patterns
    ) and not any(
        gt.search(text) for gt in grounding_token_patterns
    )


def _reply_has_guardrail_template(reply_text: str) -> bool:
    text = (reply_text or "").lower()
    guardrail_patterns = [
        r"a\s+practical\s+guardrail",
        r"a\s+concrete\s+guardrail",
        r"guardrail\s+is\s+to\s+keep",
        r"guardrail\s+to\s+prevent",
        r"guardrail\s+for\s+this",
        r"a\s+simple\s+check\s+is",
        r"one\s+simple\s+rule\s+is",
    ]
    return any(re.search(p, text) for p in guardrail_patterns)


# ── Gate de integridad #3 (Fase 2 — SHADOW ONLY) ────────────────
# Detectores de fabricacion de 3ra persona y atribucion causal de segunda
# mano. NO bloquean: loguean en shadow_quality_checks.jsonl via
# _score_reply_draft para calibrar antes de activar como penalty.
# Calibrados con los ejemplos del audit (16/8/2026):
#   A "Project Mercury at AMD"           -> ungrounded_named_entity
#   B "echoes ... early genetic programming ... inadvertently reward"
#                                       -> secondhand_causal_attribution
#   C mecanismo concreto / D analogia estructural -> limpias.

# Multiword capitalized: evita el falso positivo del inicio de frase
# ("The", "This", "Version-aware") que no forman par propio-capitalizado.
_ENTITY_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")

# Marcadores de relato de segunda mano (campo historico / experiencias de
# terceros sin evidencia propia).
_ATTRIBUTION_CONTEXT_RE = re.compile(
    r"\b(echoes|reminiscent\s+of|harkens?\s+back|challenges\s+faced|"
    r"in\s+(?:the\s+)?early|back\s+in\s+the)\b",
    re.IGNORECASE,
)
# Marcadores de causalidad no intencional: solo flaggean si ademas hay una
# entidad propia sin grounding (un "inadvertently" sin sujeto especifico
# es coloquial, no fabricacion).
_ATTRIBUTION_UNINTENTIONAL_RE = re.compile(
    r"\b(inadvertently|unintentionally|accidentally)\b",
    re.IGNORECASE,
)


def _extract_named_entities(text: str) -> set:
    """Entidades multiword capitalizadas, normalizadas a lowercase.

    Solo pares de >= 2 palabras capitalizadas (evita inicios de frase y
    sustantivos comunes)."""
    if not text:
        return set()
    return {
        " ".join(m.split()).lower()
        for m in _ENTITY_RE.findall(text)
    }


def _reply_has_ungrounded_named_entity(reply_text: str, source_text: str) -> bool:
    """True si el reply menciona una entidad propia (proyecto/empresa/
    producto) que NO aparece en la fuente — fabricacion de 3ra persona."""
    entities = _extract_named_entities(reply_text or "")
    if not entities:
        return False
    source_norm = re.sub(r"\s+", " ", (source_text or "").lower())
    return any(e not in source_norm for e in entities)


def _reply_has_secondhand_causal_attribution(reply_text: str) -> bool:
    """True si el reply relata experiencias/causalidad de terceros como
    hecho (relato de segunda mano sin evidencia propia)."""
    text = reply_text or ""
    if _ATTRIBUTION_CONTEXT_RE.search(text):
        return True
    if _ATTRIBUTION_UNINTENTIONAL_RE.search(text):
        return bool(_extract_named_entities(text))
    return False
