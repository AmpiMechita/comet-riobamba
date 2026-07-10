"""
Publishers package — auto-posting to social platforms.

Currently supported:
  - LinkedIn  (text posts via LinkedIn Marketing/Share API)
  - X/Twitter (single tweets + threads via API v2)

Design:
  - All publishers share a common interface (BasePublisher).
  - A single SQLite queue at data/publish_queue.db holds pending posts
    across all platforms. Approval-gated: nothing publishes until the
    user runs `comet_repurposer approve <id>`.
  - Kill switch: if data/KILL_SWITCH exists, no publish command runs.
  - Dry-run mode: every publish call can be previewed with --dry-run.
"""

from .base import (
    BasePublisher,
    PublishJob,
    PublishStatus,
    QueueStore,
    RateLimitError,
    AuthError,
    PublishError,
)
from .linkedin import LinkedInPublisher
from .twitter import TwitterPublisher
from .scheduler import OptimalScheduler, DEFAULT_OPTIMAL_SLOTS

__all__ = [
    "BasePublisher",
    "PublishJob",
    "PublishStatus",
    "QueueStore",
    "RateLimitError",
    "AuthError",
    "PublishError",
    "LinkedInPublisher",
    "TwitterPublisher",
    "OptimalScheduler",
    "DEFAULT_OPTIMAL_SLOTS",
]

# Default optimal slots use 'x' as the platform key (matches PLATFORMS dict).
DEFAULT_OPTIMAL_SLOTS["x"] = DEFAULT_OPTIMAL_SLOTS.pop("twitter", ["08:00", "12:00", "18:00", "21:00"])
