"""Two-call pipeline for on-topic reply verification.

Call 1 — extract_claim(): given post text + comment text, extracts the
    post's central claim and what a valid reply must address.
Call 2 — check_claim(): given the claim dict + generated reply draft,
    verifies the reply actually engages with the required topic.

Both use a fast/cheap LLM tier (haiku by default) because they are
short classification calls (< 200 tokens input, < 100 tokens output).
"""

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


EXTRACT_CLAIM_SYSTEM = (
    "You are a precise text analyst. "
    "Read the post and the comment being replied to. "
    'Output ONLY valid JSON with two fields:\n'
    '  "central_claim": one sentence summarizing the post\'s core argument\n'
    '  "reply_must_address": one sentence describing what a valid reply\n'
    "                         must engage with to stay on-topic\n"
    "No preamble, no explanation."
)

CHECK_CLAIM_SYSTEM = (
    "You are a relevance checker for a technical forum. "
    "Given the post's central claim and a reply draft, determine if the reply "
    "meaningfully engages with the topic. "
    'Output ONLY valid JSON with three fields:\n'
    '  "on_topic": true or false\n'
    '  "reason": one sentence explaining your verdict\n'
    '  "score": a float from 0.0 (completely off-topic) to 1.0 (perfectly on-topic)\n'
    "Guidelines for scoring:\n"
    "- A reply that directly addresses the core claim scores 0.8-1.0.\n"
    "- A reply that uses a technical analogy or related concept to illuminate "
    "the core claim scores 0.6-0.8 (this is ON-TOPIC).\n"
    "- A reply that connects an adjacent technical domain to the claim's "
    "implications scores 0.5-0.7 (this is ON-TOPIC).\n"
    "- A reply that completely ignores the claim and discusses something "
    "unrelated scores < 0.3 and on_topic=false.\n"
    "Be generous: technical discussions often build bridges between domains. "
    "Only mark on_topic=false if the reply has NO meaningful connection to the post.\n"
    "No preamble, no explanation."
)


async def extract_claim(
    post_text: str,
    comment_text: str,
    llm: Any,
    tier: str = "flash",
) -> Optional[Dict[str, str]]:
    """Extract the central claim of a post and what a reply must address.

    Returns {"central_claim": str, "reply_must_address": str} on success,
    or None on LLM failure / malformed JSON.
    """
    prompt = (
        f"POST:\n{post_text[:1500]}\n\n"
        f"COMMENT:\n{comment_text[:500]}"
    )
    try:
        raw = await llm.generate(
            tier=tier,
            prompt=prompt,
            system_prompt=EXTRACT_CLAIM_SYSTEM,
            max_tokens=400,
            temperature=0.1,
        )
        if not raw or not raw.strip():
            logger.warning("Claim extraction: empty response")
            return None
        cleaned = _strip_code_fences(raw)
        if not cleaned.endswith("}") and not cleaned.endswith("]"):
            logger.warning("Claim extraction: truncated JSON from LLM (len=%d), failing open", len(raw))
            return None
        result = json.loads(cleaned)
        if not isinstance(result, dict) or "central_claim" not in result or "reply_must_address" not in result:
            logger.warning("Claim extraction: missing required fields in %s", result)
            return None
        return {
            "central_claim": str(result["central_claim"]),
            "reply_must_address": str(result["reply_must_address"]),
        }
    except json.JSONDecodeError:
        if raw and not raw.strip().rstrip().endswith("}") and not raw.strip().rstrip().endswith("]"):
            logger.warning("Claim extraction: truncated JSON from LLM (len=%d), failing open", len(raw))
        else:
            logger.warning("Claim extraction: invalid JSON from LLM: %.200s", raw)
        return None
    except Exception as e:
        logger.warning("Claim extraction LLM call failed: %s", e)
        return None


async def check_claim(
    claim: Dict[str, str],
    reply_draft: str,
    llm: Any,
    tier: str = "flash",
) -> Dict[str, Any]:
    """Check whether a reply draft addresses the post's central claim.

    Returns {"on_topic": bool, "reason": str, "score": float}.
    On LLM failure: returns {"on_topic": True, "score": 1.0, "reason": "check skipped"}
    – fail-open to avoid silent over-blocking.
    """
    prompt = (
        f"CENTRAL CLAIM:\n{claim.get('central_claim', '')}\n\n"
        f"REPLY MUST ADDRESS:\n{claim.get('reply_must_address', '')}\n\n"
        f"REPLY DRAFT:\n{reply_draft[:800]}"
    )
    try:
        raw = await llm.generate(
            tier=tier,
            prompt=prompt,
            system_prompt=CHECK_CLAIM_SYSTEM,
            max_tokens=400,
            temperature=0.1,
        )
        if not raw or not raw.strip():
            logger.warning("Claim check: empty response, fail-open")
            return {"on_topic": True, "score": 1.0, "reason": "check skipped (empty response)"}
        cleaned = _strip_code_fences(raw)
        result = json.loads(cleaned)
        if not isinstance(result, dict):
            logger.warning("Claim check: non-dict response %s, fail-open", result)
            return {"on_topic": True, "score": 1.0, "reason": "check skipped (non-dict)"}
        return {
            "on_topic": bool(result.get("on_topic", True)),
            "reason": str(result.get("reason", "")),
            "score": float(result.get("score", 1.0)),
        }
    except json.JSONDecodeError:
        logger.warning("Claim check: invalid JSON from LLM: %.200s, fail-open", raw)
        return {"on_topic": True, "score": 1.0, "reason": "check skipped (invalid JSON)"}
    except Exception as e:
        logger.warning("Claim check LLM call failed: %s, fail-open", e)
        return {"on_topic": True, "score": 1.0, "reason": f"check skipped ({e})"}
