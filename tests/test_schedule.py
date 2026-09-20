# -*- coding: utf-8 -*-
"""Tests para config/schedule.py."""

from datetime import datetime, timezone
import pytest

from config import behavior_cfg
from config.schedule import (
    get_quiet_hours, get_post_hours, get_comment_hours,
    get_max_posts_per_day, get_max_comments_per_day,
)

TUESDAY  = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
SATURDAY = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
SUNDAY   = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _snapshot():
    orig = dict(behavior_cfg)
    yield
    behavior_cfg.clear()
    behavior_cfg.update(orig)


def test_weekday_uses_weekday_list():
    behavior_cfg["quiet_hours"] = [1, 2, 3]
    behavior_cfg["quiet_hours_weekend"] = [22, 23]
    assert get_quiet_hours(now=TUESDAY) == [1, 2, 3]


def test_saturday_uses_weekend_list():
    behavior_cfg["quiet_hours"] = [1, 2, 3]
    behavior_cfg["quiet_hours_weekend"] = [22, 23]
    assert get_quiet_hours(now=SATURDAY) == [22, 23]


def test_sunday_uses_weekend_list():
    behavior_cfg["quiet_hours"] = [1, 2, 3]
    behavior_cfg["quiet_hours_weekend"] = [22, 23]
    assert get_quiet_hours(now=SUNDAY) == [22, 23]


def test_weekend_falls_back_when_key_missing():
    behavior_cfg["quiet_hours"] = [1, 2, 3]
    behavior_cfg.pop("quiet_hours_weekend", None)
    assert get_quiet_hours(now=SATURDAY) == [1, 2, 3]


def test_runtime_mutation_reflected():
    behavior_cfg["quiet_hours"] = [1]
    behavior_cfg["quiet_hours_weekend"] = [2]
    assert get_quiet_hours(now=SATURDAY) == [2]
    behavior_cfg["quiet_hours_weekend"] = [9, 10]
    assert get_quiet_hours(now=SATURDAY) == [9, 10]


def test_post_hours_weekend():
    behavior_cfg["post_hours"] = [11, 12]
    behavior_cfg["post_hours_weekend"] = [10, 11, 12, 17]
    assert get_post_hours(now=SATURDAY) == [10, 11, 12, 17]
    assert get_post_hours(now=TUESDAY) == [11, 12]


def test_comment_hours_weekend():
    behavior_cfg["comment_hours"] = [11]
    behavior_cfg["comment_hours_weekend"] = [9, 10, 11]
    assert get_comment_hours(now=SATURDAY) == [9, 10, 11]


def test_max_posts_weekend():
    behavior_cfg["max_posts_per_day"] = 2
    behavior_cfg["max_posts_per_day_weekend"] = 4
    assert get_max_posts_per_day(now=SATURDAY, default=None) == 4
    assert get_max_posts_per_day(now=TUESDAY, default=None) == 2


def test_max_comments_weekend():
    behavior_cfg["max_comments_per_day"] = 30
    behavior_cfg["max_comments_per_day_weekend"] = 40
    assert get_max_comments_per_day(now=SATURDAY, default=None) == 40
    assert get_max_comments_per_day(now=TUESDAY, default=None) == 30


def test_now_none_falls_back_to_realtime():
    behavior_cfg["quiet_hours"] = [1, 2, 3]
    behavior_cfg["quiet_hours_weekend"] = [22, 23]
    assert isinstance(get_quiet_hours(), list)
