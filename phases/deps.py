from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from config.agent_policy import POLICY


@dataclass
class PhaseADeps:
    model_cascade: Any
    moltbook_client: Any
    behavior_cfg: Dict
    posts_today: int = 0
    get_posts_today: Optional[Callable[[], int]] = None
    self_diagnosis: Optional[Dict] = None


@dataclass
class PhaseBDeps:
    model_cascade: Any
    moltbook_client: Any
    behavior_cfg: Dict
    agent_name: str = "COMET-RIOBAMBA"
    posts_today: int = 0
    get_posts_today: Optional[Callable[[], int]] = None
    get_comments_today: Optional[Callable[[], int]] = None
    increment_comments_today: Optional[Callable[[], int]] = None
    pending_home_post_ids: Optional[set] = None


@dataclass
class PhaseCDeps:
    model_cascade: Any
    moltbook_client: Any
    write_policy: Any
    telegram_client: Optional[Any] = None
    behavior_cfg: Optional[Dict] = None
    content_cfg: Optional[Dict] = None
    cycle_count: int = 0
    agent_name: str = "COMET-RIOBAMBA"
    max_phase_c_replies_per_day: int = POLICY.max_phase_c_replies_per_day
    max_phase_c_replies_per_cycle: int = POLICY.max_phase_c_replies_per_cycle
    should_track_phase_c_thread: Optional[Callable] = None
    get_comments_today: Optional[Callable[[], int]] = None
    increment_comments_today: Optional[Callable[[], int]] = None
