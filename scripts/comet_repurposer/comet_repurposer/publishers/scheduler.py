"""
Optimal-time scheduler.

Per-platform best posting windows (UTC) based on industry benchmarks
(LinkedIn: business hours East Coast US; X: lunch + evening).

These are defaults — override via .env:
  LINKEDIN_OPTIMAL_SLOTS=09:00,12:00,17:00
  TWITTER_OPTIMAL_SLOTS=08:00,12:00,18:00,21:00
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional


# Default optimal slots in UTC.
DEFAULT_OPTIMAL_SLOTS = {
    "linkedin": ["09:00", "12:00", "17:00"],
    "twitter": ["08:00", "12:00", "18:00", "21:00"],
}


@dataclass
class OptimalScheduler:
    """Pick the next optimal slot for a platform, given 'now'."""

    slots_by_platform: dict
    min_gap_hours: int = 2          # don't schedule two posts too close
    timezone_offset_hours: int = 0  # treat slots as local-time, convert to UTC

    def next_slot(self, platform: str, now: Optional[datetime] = None,
                  skip_until: Optional[datetime] = None) -> datetime:
        """Return the next datetime >= now that matches a slot for platform.

        If ``skip_until`` is provided, returns the next slot after that time.
        """
        now = now or datetime.now(timezone.utc)
        if skip_until and skip_until > now:
            now = skip_until

        slots = self.slots_by_platform.get(platform, ["09:00"])
        candidates: List[datetime] = []
        for day_offset in range(0, 8):
            for slot in slots:
                hh, mm = slot.split(":")
                dt = (now + timedelta(days=day_offset)).replace(
                    hour=int(hh), minute=int(mm), second=0, microsecond=0,
                    tzinfo=timezone.utc,
                )
                # adjust for local offset if non-zero
                if self.timezone_offset_hours:
                    dt = dt - timedelta(hours=self.timezone_offset_hours)
                if dt >= now:
                    candidates.append(dt)
        candidates.sort()
        return candidates[0] if candidates else now

    def enforce_min_gap(self, last_posted_at: Optional[datetime],
                        platform: str, now: Optional[datetime] = None) -> datetime:
        """If last_posted_at is too recent, push to next slot past min_gap."""
        now = now or datetime.now(timezone.utc)
        if not last_posted_at:
            return self.next_slot(platform, now)
        earliest = last_posted_at + timedelta(hours=self.min_gap_hours)
        if earliest > now:
            return self.next_slot(platform, now, skip_until=earliest)
        return self.next_slot(platform, now)
