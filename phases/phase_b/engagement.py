# -*- coding: utf-8 -*-
"""Phase B engagement actions: strategic upvotes and agent follows.

Extracted from orchestrator.py to reduce the monolithic class size.
These functions receive the PhaseB instance as their first parameter
to minimise disruption — the call sites in orchestrator.py use thin
delegation methods with the same signatures as before.
"""

import logging
from pathlib import Path

from core.observability import send_event
from core.tracer import Span
from services.self_eval import update_today_metrics

logger = logging.getLogger("phases.phase_b")


def _maybe_upvote(pb, post_id: str, value_level: str) -> None:
    with Span("engagement_upvote", post_id=str(post_id)):
        if not pb._upvotes_enabled:
            return
        if not post_id:
            return
        if post_id in pb._upvoted_post_ids:
            logger.debug("Phase B: skip upvote (reason=already_upvoted, post_id=%s)", post_id)
            return
        if value_level.upper() == "TRIVIAL":
            logger.debug("Phase B: skip upvote (reason=trivial, post_id=%s)", post_id)
            return
        if pb._upvotes_this_cycle >= pb._max_upvotes_per_cycle:
            logger.debug("Phase B: skip upvote (reason=cycle_limit, post_id=%s)", post_id)
            return

        try:
            _dry_flag = getattr(pb, "_dry_run_flag", None) or Path("data/phase_b_dry_run.flag")
            if _dry_flag.exists():
                logger.warning("🧪 DRY-RUN: upvote simulado para post_id=%s", post_id)
                ok = True  # simulate success
            else:
                ok = pb.api.upvote_post(post_id)
            if ok:
                pb._upvoted_post_ids.add(post_id)
                pb._upvotes_this_cycle += 1
                pb._dedup.mark_upvoted(post_id)
                logger.info("Phase B: upvoted post (post_id=%s, value=%s)", post_id, value_level.upper())
                update_today_metrics(upvotes_today=1)
                send_event("phase_b_upvote", {"post_id": str(post_id), "cycle_count": pb._upvotes_this_cycle})
            else:
                logger.warning("Phase B: upvote failed for post %s", post_id)
        except Exception as e:
            logger.warning("Phase B: upvote error for post %s: %s", post_id, e)


def _maybe_follow_author(pb, author: str) -> None:
    with Span("engagement_follow", author=str(author)):
        if not pb._following_enabled:
            return
        if not author or not author.strip():
            return
        name = author.strip().lower()
        if pb._is_own_author(name):
            return
        if name in pb._followed_agent_names:
            logger.debug("Phase B: skip follow (reason=already_following, agent=%s)", name)
            return
        if pb._follows_this_cycle >= pb._max_follows_per_cycle:
            logger.debug("Phase B: skip follow (reason=cycle_limit, agent=%s)", name)
            return

        try:
            _dry_flag = getattr(pb, "_dry_run_flag", None) or Path("data/phase_b_dry_run.flag")
            if _dry_flag.exists():
                logger.warning("🧪 DRY-RUN: follow simulado para agent=%s", name)
                ok = True  # simulate success
            else:
                ok = pb.api.follow_agent(name)
            if ok:
                pb._followed_agent_names.add(name)
                pb._follows_this_cycle += 1
                pb._dedup.mark_followed(name)
                logger.info("Phase B: followed agent (agent=%s, reason=high_value_debate)", name)
                update_today_metrics(follows_today=1)
                send_event("phase_b_follow", {"author": str(author), "cycle_count": pb._follows_this_cycle})
            else:
                logger.debug("Phase B: follow failed for agent %s", name)
        except Exception as e:
            logger.warning("Phase B: follow error for agent %s: %s", name, e)
