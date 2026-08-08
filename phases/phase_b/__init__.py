# -*- coding: utf-8 -*-
"""Phase B — Community Replies (package)."""

from .constants import (
    FORBIDDEN_PHRASES,
    COMMENT_STYLE_INSTRUCTIONS,
    MAX_CONVERSATION_DEPTH,
)
from .scoring import RelevanceDecision, _get_feed_min_score

# Re-export public names from orchestrator for backward compat
from .orchestrator import *  # noqa: F401,F403

# Candidate scorer
from .candidate_scorer import score_comment, rank_candidates

# Explicitly re-export private names used by tests (not captured by *)
from .orchestrator import (  # noqa: F811
    PhaseB,
    logger,
    _load_replied_comment_ids,
    _save_replied_comment_ids,
    _load_commented_post_ids,
    _save_commented_post_ids,
    _load_agent_comment_ids,
    _save_agent_comment_ids,
    _load_upvoted_post_ids,
    _save_upvoted_post_ids,
    _load_followed_agent_names,
    _save_followed_agent_names,
    _load_post_history_guard,
    _save_post_history_guard,
    _safe_truncate,
    _REPLIED_IDS_PATH,
    _COMMENTED_POSTS_PATH,
    _AGENT_COMMENT_IDS_PATH,
    _UPVOTED_POST_IDS_PATH,
    _FOLLOWED_AGENTS_PATH,
    _is_semantic_dupe_against_history,
    _append_to_reply_history,
    _load_reply_history,
    _save_reply_history,
)

__all__ = [
    "PhaseB",
    "FORBIDDEN_PHRASES",
    "COMMENT_STYLE_INSTRUCTIONS",
    "RelevanceDecision",
    "MAX_CONVERSATION_DEPTH",
    "logger",
]
