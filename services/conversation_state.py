"""Per-thread conversation state for debate handling in own-post comments."""

import json
import logging
from pathlib import Path
from typing import Dict, Optional

from services.own_post_store import is_valid_post_id

logger = logging.getLogger(__name__)

CONVERSATIONS_PATH = Path("data/conversations.json")
MAX_TURNS_PER_THREAD = 4


def _load_conversations() -> Dict:
    if not CONVERSATIONS_PATH.exists():
        return {}
    try:
        data = json.loads(CONVERSATIONS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            result = {}
            for k, v in data.items():
                if is_valid_post_id(k):
                    result[k] = v
                else:
                    logger.debug("conversation_state: skipping non-UUID post_id=%r on load", k)
            return result
        return data
    except Exception as e:
        logger.warning("Conversations: error loading %s: %s", CONVERSATIONS_PATH, e)
        return {}


def _save_conversations(data: Dict) -> None:
    CONVERSATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        CONVERSATIONS_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("Conversations: error saving %s: %s", CONVERSATIONS_PATH, e)


def get_or_create_thread(post_id: str) -> Dict:
    if not is_valid_post_id(post_id):
        logger.warning("conversation_state: rejected non-UUID post_id=%r, skipping", post_id)
        return {"turns_in_thread": 0, "open_questions": False, "closed": False}
    conv = _load_conversations()
    if post_id not in conv:
        conv[post_id] = {
            "turns_in_thread": 0,
            "open_questions": False,
            "closed": False,
        }
        _save_conversations(conv)
    return conv[post_id]


def _save_thread(post_id: str, thread: Dict) -> None:
    if not is_valid_post_id(post_id):
        logger.warning("conversation_state: rejected non-UUID post_id=%r in _save_thread, skipping", post_id)
        return
    conv = _load_conversations()
    conv[post_id] = thread
    _save_conversations(conv)


def is_thread_closed(post_id: str) -> bool:
    thread = get_or_create_thread(post_id)
    return thread.get("closed", False)


def can_continue_thread(post_id: str) -> bool:
    thread = get_or_create_thread(post_id)
    if thread.get("closed", False):
        return False
    if thread.get("turns_in_thread", 0) >= MAX_TURNS_PER_THREAD:
        return False
    return thread.get("open_questions", False)


def register_agent_reply(post_id: str) -> None:
    thread = get_or_create_thread(post_id)
    thread["turns_in_thread"] = thread.get("turns_in_thread", 0) + 1
    if thread["turns_in_thread"] >= MAX_TURNS_PER_THREAD:
        thread["closed"] = True
    _save_thread(post_id, thread)


def update_open_questions(post_id: str, other_comment_text: str) -> None:
    thread = get_or_create_thread(post_id)
    text_lower = other_comment_text.lower()
    has_question = "?" in text_lower
    is_closing = any(k in text_lower for k in
                     ("gracias", "thanks", "thank you", "entendido", "claro", "👍",
                      "that's all", "no more questions", "that helps", "good point"))
    # Question takes priority over closing words (a "thanks, but how..." is still a question)
    thread["open_questions"] = has_question
    if not has_question and is_closing:
        thread["closed"] = True
    _save_thread(post_id, thread)


def close_thread(post_id: str) -> None:
    thread = get_or_create_thread(post_id)
    thread["closed"] = True
    _save_thread(post_id, thread)
