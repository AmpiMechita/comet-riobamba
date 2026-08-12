from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentPolicy:
    max_posts_per_day: int = 6
    value_review_interval_days: int = 7

    max_own_posts_to_scan_per_cycle: int = 3
    phase_a_max_attempts: int = 3
    phase_a_mode: str = "research"
    # ── Activity Budget (per day) ──────────────────────────────────
    max_comments_per_day: int = 150      # v5.2: libre albedrío — la comunidad decide
    max_feed_initiations_per_day: int = 10     # First comment in a new feed post
    max_feed_replies_per_day: int = 60         # Total feed replies

    # ── Per-cycle limits ───────────────────────────────────────────
    max_comment_replies_per_cycle: int = 30
    phase_b_max_own_comments_per_cycle: int = 10   # v5.2+: cap de trabajo por post por ciclo
                                                  # (un post de 300+ comentarios ya no puede
                                                  # monopolizar el ciclo completo)

    # ── Per-post limits ────────────────────────────────────────────
    max_comments_per_post: int = 30            # Responses in own post (free-will)
    max_feed_comments_per_post: int = 10        # Replies per feed post

    # ── Thread engagement ──────────────────────────────────────────
    max_thread_depth: int = 10
    disengage_after_no_value_replies: int = 2

    min_comment_relevance_score: int = 4

    max_phase_c_replies_per_cycle: int = 3
    max_phase_c_replies_per_day: int = 10

    cycle_interval_seconds: int = 15
    phase_b_interval_seconds: int = 3600
    scan_interval_minutes: int = 15

    max_consecutive_post_failures: int = 3
    max_outbox_posts_for_phase_a: int = 3

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
