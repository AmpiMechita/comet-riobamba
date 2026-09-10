from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentPolicy:
    max_posts_per_day: int = None   # ✅ SIN LÍMITE — agente decide cuántos publicar por día
    value_review_interval_days: int = 7

    max_own_posts_to_scan_per_cycle: int = 3
    phase_a_max_attempts: int = 3
    phase_a_mode: str = "research"
    # ── Activity Budget (per day) ──────────────────────────────────
    # None = sin límite diario; la comunidad decide a través del engagement
    max_comments_per_day: int = None   # ✅ SIN LÍMITE — la comunidad decide
    max_feed_initiations_per_day: int = 10     # First comment in a new feed post
    max_feed_replies_per_day: int = 60         # Total feed replies

    # ── Per-cycle limits ───────────────────────────────────────────
    # None = sin límite por ciclo; el agente gestiona su propio trabajo
    max_comment_replies_per_cycle: int = None
    phase_b_max_own_comments_per_cycle: int = None   # ✅ Sin cap de trabajo por post
    phase_b_own_queue_per_cycle: int = None          # ✅ Cola sin restricciones

    # ── Per-post limits ────────────────────────────────────────────
    # None = sin límite por post; el agente decide la longitud
    max_comments_per_post: int = None            # ✅ Sin límite de respuesta por post
    max_feed_comments_per_post: int = None        # ✅ Sin límite de replies por post

    # ── Thread engagement ──────────────────────────────────────────
    max_thread_depth: int = None   # ✅ Sin límite de profundidad de hilo
    disengage_after_no_value_replies: int = None     # ✅ Sin auto-desenganche

    min_comment_relevance_score: int = 4

    # None = sin límite de fase C
    max_phase_c_replies_per_cycle: int = None
    max_phase_c_replies_per_day: int = None

    cycle_interval_seconds: int = 15
    phase_b_interval_seconds: int = 3600
    scan_interval_minutes: int = 15

    max_consecutive_post_failures: int = 3
    max_outbox_posts_for_phase_a: int = 200

    outbox_min_backoff_seconds: int = 60
    outbox_max_backoff_seconds: int = 3600

    min_post_length_chars: int = 300
    max_post_length_chars: int = 900
    target_post_length_chars: int = 600

    relevance_boost_question: int = 30
    relevance_boost_mention: int = 40
    relevance_penalty_short: int = 20
    relevance_boost_tech_keyword: int = 25


POLICY = AgentPolicy()
