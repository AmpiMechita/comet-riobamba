# -*- coding: utf-8 -*-
"""Phase B value classification and research agenda utilities.

Extracted from orchestrator.py to reduce the monolithic class size.
Functions that need PhaseB instance attributes receive `pb` as their
first parameter (same pattern as engagement.py).

Static methods that referenced PhaseB._TECH_KEYWORDS now receive it
as an explicit parameter via the delegation methods.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from core.value_log import log_value_event
from prompts.value_classifier import build_classifier_prompt

logger = logging.getLogger("phases.phase_b")


async def _classify_and_log_value(
    pb,
    post: Dict[str, Any],
    comment_text: str,
    reply_text: str,
    comment_id: str,
    follow_up: str = "",
comment_author: str = "",
) -> None:
    if not pb.llm:
        return
    post_text = f"{post.get('title', '')}\n{post.get('content', '') or post.get('body', '')}"
    try:
        system_prompt, user_prompt = build_classifier_prompt(
            post=post_text, comment=comment_text, reply=reply_text, follow_up=follow_up,
        )
        raw = await pb.llm.generate(
            tier="classify",
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
        user_id = comment_author or str(post.get("author") or post.get("username", ""))
        event = {
            "id": f"{ts}-{post_id}-{comment_id}",
            "timestamp": ts,
            "post_id": post_id,
            "comment_id": comment_id,
            "user_id": user_id,
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


def _add_topic_to_agenda(pb, post: Dict[str, Any], post_body: str) -> None:
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


def _build_thread_history(pb, comment: Dict, all_comments: List[Dict]) -> str:
    parent_id = comment.get("parent_id")
    if not parent_id:
        return ""
    cmap = {c.get("id"): c for c in all_comments if c.get("id")}
    chain: list[tuple[str, str]] = []
    seen: set[str] = set()
    while parent_id and parent_id in cmap and parent_id not in seen:
        seen.add(parent_id)
        parent = cmap[parent_id]
        author_raw = parent.get("author")
        if isinstance(author_raw, dict):
            author_name = str(author_raw.get("name") or author_raw.get("username") or "")
        else:
            author_name = str(author_raw or "")
        text = (parent.get("content") or parent.get("text") or "").strip()
        if not text:
            parent_id = parent.get("parent_id")
            continue
        label = "Agente" if pb._is_own_author(author_name) else (author_name or "Usuario")
        chain.append((label, text))
        parent_id = parent.get("parent_id")
    if not chain:
        return ""
    chain.reverse()
    parts = ["--- HISTORIAL DEL HILO ---"]
    for label, text in chain:
        preview = text[:200] + "..." if len(text) > 200 else text
        parts.append(f"[{label}]: {preview}")
    parts.append("--- FIN DEL HISTORIAL ---")
    return "\n".join(parts)


def _classify_topic_value(
    body: str,
    comments: Optional[List[Dict]] = None,
    *,
    tech_keywords: frozenset = frozenset(),
) -> str:
    if not body or len(body.strip()) < 30:
        return "TRIVIAL"
    body_lower = body.lower()

    if any(k in body_lower for k in ("gana dinero", "sorteo", "promocion", "compra", "venta",
                                     "check out", "visit my", "sign up", "click here")):
        return "TRIVIAL"

    if len(body.strip()) < 50:
        return "TRIVIAL"

    hv_keywords = ["metrica", "guardrail", "failure mode", "observability",
                   "rate limit", "circuit breaker", "trade-off", "orchestrat",
                   "multi-agent", "coordination", "architecture",
                   "pipeline", "degradation", "graceful", "experiment",
                   "comparison", "analysis", "measure"]
    hv_count = sum(1 for kw in hv_keywords if kw in body_lower)
    if hv_count >= 1:
        return "HIGH_VALUE"

    tech_count = sum(1 for kw in (tech_keywords or frozenset()) if kw in body_lower)
    if "?" in body_lower or tech_count >= 2:
        return "STANDARD"

    return "STANDARD"


def _classify_comment_value(
    comment_text: str,
    *,
    tech_keywords: frozenset = frozenset(),
) -> str:
    if not comment_text or len(comment_text.strip()) < 10:
        return "general"
    text_lower = comment_text.lower()
    if "?" in text_lower:
        return "high_value"
    tech_count = sum(1 for kw in (tech_keywords or frozenset()) if kw in text_lower)
    if tech_count >= 2:
        return "high_value"
    return "standard"


def _is_non_trivial_contribution(draft: str) -> bool:
    if not draft or len(draft.strip()) < 30:
        return False
    d = draft.lower()
    non_trivial_keywords = [
        "metric", "guardrail", "failure mode", "threshold",
        "fallback", "observability", "rate limit", "circuit breaker",
        "retry", "backoff", "latency", "throughput", "p99",
        "pipeline", "orchestrat", "degradation", "graceful",
        "migration", "feature flag", "canary", "deployment",
        "progressive", "rollback", "monitor", "alert",
        "instrumentation", "tracing", "telemetry", "health check",
    ]
    return sum(1 for kw in non_trivial_keywords if kw in d) >= 1


def _classify_debate_value(text: str) -> str:
    if not text or len(text.strip()) < 15:
        return "acknowledgment"
    t = text.lower()
    ack_phrases = {"thanks", "thank you", "that makes sense", "good point",
                   "i see", "got it", "helps", "appreciate"}
    if any(p in t for p in ack_phrases) and "?" not in t:
        return "acknowledgment"
    return "debate_continuation"
