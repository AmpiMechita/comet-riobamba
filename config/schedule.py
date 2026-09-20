# -*- coding: utf-8 -*-
"""Helpers de scheduling day-aware (weekday vs weekend).

Los helpers aceptan `now` explicito para no romper los mocks de
`datetime` en tests (test_hours.py parchea
`phases.phase_a_content.datetime`). Fallback transparente a
valores weekday si la variante weekend no esta definida.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from config.config import behavior_cfg

_DEFAULT_TZ = "America/Guayaquil"


def _now(tz_name: Optional[str] = None) -> datetime:
    tz = ZoneInfo(tz_name or behavior_cfg.get("timezone", _DEFAULT_TZ))
    return datetime.now(tz)


def _is_weekend(now: datetime) -> bool:
    return now.weekday() >= 5


def _resolve(key_weekday: str, key_weekend: str, now: datetime, default):
    if _is_weekend(now):
        v = behavior_cfg.get(key_weekend)
        if v is not None:
            return v
    v = behavior_cfg.get(key_weekday)
    return v if v is not None else default


def get_quiet_hours(now: Optional[datetime] = None) -> List[int]:
    return _resolve("quiet_hours", "quiet_hours_weekend", now or _now(), []) or []


def get_post_hours(now: Optional[datetime] = None) -> List[int]:
    return _resolve("post_hours", "post_hours_weekend", now or _now(), []) or []


def get_comment_hours(now: Optional[datetime] = None) -> List[int]:
    return _resolve("comment_hours", "comment_hours_weekend", now or _now(), []) or []


def get_max_posts_per_day(now: Optional[datetime] = None, default=None):
    return _resolve("max_posts_per_day", "max_posts_per_day_weekend", now or _now(), default)


def get_max_comments_per_day(now: Optional[datetime] = None, default=None):
    return _resolve("max_comments_per_day", "max_comments_per_day_weekend", now or _now(), default)
