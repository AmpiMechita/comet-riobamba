"""
Source readers.

Each reader yields :class:`SourceItem` objects representing one piece of
content the agent has produced. The repurposer then turns each item into
6 platform-specific derivatives.

Readers are intentionally tolerant: if a file is missing or malformed we
skip it instead of crashing, so the pipeline keeps working when only
some sources exist.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional


SLUG_MAX = 60
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = SLUG_MAX) -> str:
    """URL-safe slug for use in folder names."""
    text = (text or "").lower().strip()
    text = _SLUG_RE.sub("-", text).strip("-")
    if not text:
        text = "untitled"
    return text[:max_len]


# Heuristics: a body is "truncated" if its last non-whitespace line does
# not end with sentence-ending punctuation AND exhibits one of these signs:
#   (a) ends with a connector word (ensuring, with, that, where, to, ...)
#   (b) ends with a comma, em-dash, semicolon, or colon
#   (c) ends with an article or quantifier introducing a noun phrase
#       ("a se", "the variance", "this thin", ...)
#   (d) ends with a preposition followed by a single short word
# We err on the side of detecting truncation because the agent's strict
# char limit frequently causes it.
_TRUNC_ENDINGS = re.compile(r"[.!?\"'\)\]]+\s*$")

# Connector / subordinator words that almost always introduce MORE text.
_TRUNC_TAILWORDS = {
    # English subordinators / connectors
    "ensuring", "ensured", "ensures", "ensuring that", "so that", "such that",
    "and", "or", "but", "because", "while", "when", "after", "before",
    "which", "that", "where", "with", "without", "to", "for", "in",
    "of", "by", "as", "than", "until", "once", "since", "if",
    "measured", "measured by", "measured as", "expressed",
    "followed", "followed by", "given", "given that",
    "via", "using", "based", "based on",
    "this", "these", "those", "the", "a", "an",
    "any", "each", "every", "all", "some",
    # Spanish equivalents
    "y", "o", "pero", "porque", "mientras", "cuando", "después",
    "antes", "asegurando", "para", "donde", "sin", "con", "por",
    "el", "la", "los", "las", "un", "una", "este", "esta", "estos",
    "estas", "eso", "esa", "esto",
}

# Single-letter or short tails like "a se", "to a", "the var"
_SHORT_TAIL_RE = re.compile(r"\b(\w{1,4})\s+(\w{1,4})\s*$")


def looks_truncated(body: str) -> bool:
    """Heuristic: returns True if ``body`` appears to end mid-sentence."""
    if not body or not body.strip():
        return False
    last_line = body.strip().splitlines()[-1].strip()
    if not last_line:
        return False

    # (0) Ends with proper sentence punctuation -> not truncated.
    if _TRUNC_ENDINGS.search(last_line):
        return False

    # (1) Ends with a comma, em-dash, semicolon, or colon -> truncated.
    if last_line.endswith((",", "—", "-", ";", ":")):
        return True

    # Tokenize the last 4 words (lowercased) for tail-word matching.
    tokens = last_line.lower().split()
    if not tokens:
        return False

    # (2) Last word is a connector/subordinator -> truncated.
    if tokens[-1] in _TRUNC_TAILWORDS:
        return True

    # (3) Last two words are "connector + short_word" pattern -> truncated.
    #     e.g. "ensuring", "the variance", "a se", "this thin", "measured by"
    if len(tokens) >= 2:
        last_two = " ".join(tokens[-2:])
        if last_two in _TRUNC_TAILWORDS:
            return True
        # Also check "connector + any word" pattern:
        # e.g. "ensuring the", "with a", "to a", "by the"
        if tokens[-2] in _TRUNC_TAILWORDS:
            return True

    # (4) Last three words form a "quantifier + article + noun" style tail
    #     that typically introduces more: "a 5-second TTL", "a shared ledger"
    #     Hard to enumerate; rely on (3) for those.

    return False


@dataclass
class SourceItem:
    """One piece of agent-produced content to be repurposed."""

    source_kind: str       # 'published_post' | 'social_content' | 'ebook' | 'research_topic'
    source_id: str         # stable id (post_id, file stem, topic hash)
    title: str             # short label
    body: str              # the actual content to adapt
    language: str = "en"
    created_at: Optional[str] = None  # ISO 8601
    tags: List[str] = field(default_factory=list)
    source_path: Optional[str] = None
    truncated: bool = False  # True if body appears cut mid-sentence

    @property
    def slug(self) -> str:
        return slugify(self.title or self.source_id)

    @property
    def closing_hint(self) -> str:
        """A short hint appended to the prompt when truncated is True."""
        if not self.truncated:
            return ""
        return (
            "\n\nNOTE: The source content above appears truncated (ends mid-sentence). "
            "Apply the truncation-handling rules from the system prompt."
        )


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def iter_published_posts(project_root: Path) -> Iterator[SourceItem]:
    """Read ``data/published_posts.json``.

    The file is a JSON array of objects with at least ``post_id`` and
    ``topic``. Optionally also ``published_at`` and ``content``.
    """
    path = project_root / "data" / "published_posts.json"
    if not path.exists():
        return
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(items, list):
        return
    for entry in items:
        if not isinstance(entry, dict):
            continue
        post_id = str(entry.get("post_id") or entry.get("id") or "").strip()
        topic = str(entry.get("topic") or entry.get("title") or "").strip()
        if not post_id or not topic:
            continue
        body = str(entry.get("content") or entry.get("body") or topic)
        yield SourceItem(
            source_kind="published_post",
            source_id=post_id,
            title=topic,
            body=body,
            language="en",
            created_at=entry.get("published_at") or entry.get("created_at"),
            tags=list(entry.get("tags") or []),
            source_path=str(path),
            truncated=looks_truncated(body),
        )


def iter_social_content(project_root: Path) -> Iterator[SourceItem]:
    """Read ``exports/social_content/*.md``.

    Each markdown file already contains a Twitter thread and LinkedIn post
    produced by Phase C. We treat the whole file as one source item so
    the repurposer can re-shape it for the other platforms.
    """
    folder = project_root / "exports" / "social_content"
    if not folder.exists():
        return
    for path in sorted(folder.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Title heuristic: first non-empty markdown heading, else file stem.
        title = path.stem
        m = re.search(r"^#{1,3}\s+(.+)$", text, flags=re.MULTILINE)
        if m:
            title = m.group(1).strip()
        yield SourceItem(
            source_kind="social_content",
            source_id=path.stem,
            title=title,
            body=text,
            language="en",
            created_at=_try_parse_date_from_filename(path.stem),
            source_path=str(path),
            truncated=looks_truncated(text),
        )


def iter_ebooks(project_root: Path) -> Iterator[SourceItem]:
    """Read ``exports/ebook_*.md`` as a single large source each."""
    folder = project_root / "exports"
    if not folder.exists():
        return
    for path in sorted(folder.glob("ebook_*.md")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        title = path.stem
        m = re.search(r"^#{1,3}\s+(.+)$", text, flags=re.MULTILINE)
        if m:
            title = m.group(1).strip()
        yield SourceItem(
            source_kind="ebook",
            source_id=path.stem,
            title=title,
            body=text,
            language="en",
            created_at=_try_parse_date_from_filename(path.stem),
            source_path=str(path),
            truncated=looks_truncated(text),
        )


def iter_research_agenda(project_root: Path) -> Iterator[SourceItem]:
    """Read ``data/research_agenda.json`` and emit one item per pending topic."""
    path = project_root / "data" / "research_agenda.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    pending = data.get("pending_topics") or []
    for entry in pending:
        if not isinstance(entry, dict):
            continue
        topic = str(entry.get("topic") or "").strip()
        if not topic:
            continue
        yield SourceItem(
            source_kind="research_topic",
            source_id=slugify(topic),
            title=topic,
            body=topic + "\n\n" + "\n".join(f"- {t}" for t in (entry.get("tags") or [])),
            language="en",
            tags=list(entry.get("tags") or []),
            source_path=str(path),
        )


def iter_all_sources(project_root: Path) -> Iterator[SourceItem]:
    """Yield from every reader in priority order.

    Order matters for the ``--limit`` flag: most actionable first.
    1. social_content (already polished, ready to extend)
    2. published_posts (raw Moltbook posts)
    3. research_agenda (fresh topics not yet covered)
    4. ebooks (rich material, but heavy)
    """
    yield from iter_social_content(project_root)
    yield from iter_published_posts(project_root)
    yield from iter_research_agenda(project_root)
    yield from iter_ebooks(project_root)


def iter_latest(project_root: Path, n: int = 5) -> Iterator[SourceItem]:
    """Return the ``n`` most recent items across all sources."""
    items = list(iter_all_sources(project_root))

    def _key(item: SourceItem) -> str:
        return item.created_at or ""

    items.sort(key=_key, reverse=True)
    for item in items[:n]:
        yield item


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _try_parse_date_from_filename(stem: str) -> Optional[str]:
    m = _DATE_PREFIX_RE.match(stem)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None
