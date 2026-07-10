# -*- coding: utf-8 -*-
"""Track historical examples used in posts/comments to prevent repetition."""
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("services.used_examples_tracker")

_EXAMPLES_FILE = Path("data/used_historical_examples.json")
_MAX_USES_PER_DAY = 1

# ── Permanent blacklist — examples that are overused and must never appear ──
_PERMANENT_BLACKLIST: set = frozenset({
    "netflix",
    "netflix's",
    "conductor",
    "netflix conductor",
    "netflix deployed conductor",
    "netflix's conductor",
    "zfs",
})

_EXAMPLE_PATTERNS = [
    r'\b[Nn]etflix\b',
    r'\b[Cc]onductor\b',
    r'\b[Dd]oor[Dd]ash\b',
    r'\b[Gg]oogle\b',
    r'\b[Aa]mazon\b',
    r'\b[Mm]eta\b',
    r'\b[Kk]night\s+[Cc]apital\b',
    r'\b[Mm]ars\s+[Cc]limate\s+[Oo]rbiter\b',
    r'\bAWS\b',
    r'\b[Dd]ynamoDB\b',
    r'\b[Gg]it[Ll]ab\b',
    r'\b[Cc]loud[fF]lare\b',
    r'\b[Kk]ong\b',
    r'\b[Kk]afka\b',
    r'\b[Nn]ortheast\s+[Bb]lackout\b',
    r'\b[Tt]witter\b',
    r'\b[Uu]ber\b',
    r'\b[Gg]itHub\b',
    r'\b[Ss]potify\b',
    r'\b[Ll]inked[Ii]n\b',
    r'\b[Mm]icrosoft\b',
    r'\b[Rr]edis\b',
    r'\b[Pp]ostgreSQL\b',
]


def _load_examples() -> dict:
    if not _EXAMPLES_FILE.exists():
        return {"used": {}}
    try:
        return json.loads(_EXAMPLES_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"used": {}}


def _save_examples(data: dict) -> None:
    _EXAMPLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _EXAMPLES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _extract_examples(text: str) -> set:
    """Extract company/incident names from text using regex patterns."""
    found = set()
    text_normalized = f" {text} "
    for pattern in _EXAMPLE_PATTERNS:
        matches = re.findall(pattern, text_normalized)
        for m in matches:
            found.add(m.lower().strip())
    return found


def _cleanup_expired(data: dict) -> dict:
    """Remove entries older than 24h."""
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=1)).isoformat()
    used = data.get("used", {})
    cleaned = {}
    for example, ts in used.items():
        if ts > cutoff:
            cleaned[example] = ts
    if len(cleaned) != len(used):
        data["used"] = cleaned
        _save_examples(data)
    return data


def is_example_recently_used(text: str) -> tuple[bool, set]:
    """Check if any historical example in the text has been used in the last 24h,
    or is in the permanent blacklist."""
    # Check permanent blacklist first
    text_lower = text.lower()
    perm_blocked = set()
    for banned in _PERMANENT_BLACKLIST:
        if banned.replace(" ", "") in text_lower.replace(" ", ""):
            perm_blocked.add(banned)
    if perm_blocked:
        logger.info("HistoricalExamples: BLOCKED — example in permanent blacklist: %s", ", ".join(sorted(perm_blocked)))
        return True, perm_blocked

    data = _cleanup_expired(_load_examples())
    extracted = _extract_examples(text)
    if not extracted:
        return False, set()
    used = data.get("used", {})
    blocked = set()
    for example in extracted:
        if example in used:
            blocked.add(example)
    if blocked:
        logger.info("HistoricalExamples: BLOCKED — examples already used today: %s", ", ".join(sorted(blocked)))
        return True, blocked
    return False, set()


def mark_examples_used(text: str) -> None:
    """Record examples found in text as used for today."""
    data = _cleanup_expired(_load_examples())
    extracted = _extract_examples(text)
    now = datetime.now(timezone.utc).isoformat()
    for example in extracted:
        data["used"][example] = now
    _save_examples(data)
    logger.info("HistoricalExamples: marked %d examples as used", len(extracted))
