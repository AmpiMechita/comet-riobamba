# -*- coding: utf-8 -*-
"""
Abstract Platform Client — interface for social platform interactions.

All platform-specific clients (Moltbook, Reddit, HN, etc.) must implement
this interface. The agent code depends ONLY on this interface, never on
concrete implementations directly.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PlatformPost:
    """Normalized post representation across platforms."""
    id: str
    title: str
    body: str
    author: str
    created_at: str
    upvotes: int = 0
    comment_count: int = 0
    url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class PlatformComment:
    """Normalized comment representation across platforms."""
    id: str
    post_id: str
    author: str
    content: str
    created_at: str
    parent_comment_id: Optional[str] = None
    upvotes: int = 0
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class PublishResult:
    """Result of a write operation."""
    success: bool
    id: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None
    requires_verification: bool = False
    verification_code: Optional[str] = None


class PlatformClient(ABC):
    """Abstract interface for platform interactions.

    Implementations must handle their own rate limiting, authentication,
    and error recovery internally.
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform identifier (e.g., 'moltbook', 'reddit')."""
        ...

    # ── Write operations ─────────────────────────────────────

    @abstractmethod
    def publish_post(self, title: str, body: str, metadata: Optional[Dict] = None) -> PublishResult:
        """Publish a new post/submission to the platform."""
        ...

    @abstractmethod
    def publish_comment(self, post_id: str, content: str, parent_comment_id: Optional[str] = None) -> PublishResult:
        """Publish a comment/reply on a post."""
        ...

    @abstractmethod
    def upvote(self, post_id: str) -> bool:
        """Upvote/like a post. Returns True on success."""
        ...

    # ── Read operations ──────────────────────────────────────

    @abstractmethod
    def get_own_posts(self, limit: int = 10) -> List[PlatformPost]:
        """Fetch the agent's own posts."""
        ...

    @abstractmethod
    def get_feed_posts(self, limit: int = 20, sort: str = "hot") -> List[PlatformPost]:
        """Fetch the platform feed/frontpage."""
        ...

    @abstractmethod
    def get_comments_normalized(self, post_id: str) -> List[PlatformComment]:
        """Fetch comments on a specific post (normalized format)."""
        ...

    # ── Optional operations (default no-op) ──────────────────

    def follow_user(self, username: str) -> bool:
        """Follow a user. Optional — returns False if not supported."""
        return False

    def search(self, query: str, limit: int = 20) -> List[PlatformPost]:
        """Search the platform. Optional — returns empty list if not supported."""
        return []

    def get_dashboard(self) -> Dict[str, Any]:
        """Get agent's dashboard/stats. Optional."""
        return {}

    def submit_verification(self, code: str, answer: str) -> bool:
        """Submit a verification/CAPTCHA answer. Optional."""
        return False
