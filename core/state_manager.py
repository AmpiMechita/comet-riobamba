from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from core.observability import send_event
from services.own_post_store import _load_published_log
from services.persistence import load_agent_state, save_agent_state

logger = logging.getLogger("core.state_manager")

PACING_MIN_HOURS = 0  # v5.3: sin limite artificial (agente decide autonomamente)


class AgentState:
    def __init__(self):
        self.cycle_count: int = 0
        self.posts_today: int = 0
        self.comments_today: int = 0
        self.last_post_date: Optional[str] = None
        self.last_post_timestamp: Optional[str] = None  # v5.0: pacing
        self.last_value_review: Optional[str] = None
        self.consecutive_failures: int = 0
        self._load()

    def _load(self) -> None:
        try:
            db_state = load_agent_state()
            self.cycle_count = int(db_state.get("cycle", 0))
            self.posts_today = int(db_state.get("posts_today", 0))
            self.comments_today = int(db_state.get("comments_today", 0))
            self.last_post_date = db_state.get("last_post_date")
            self.last_post_timestamp = db_state.get("last_post_timestamp")  # v5.0: pacing
            self.last_value_review = db_state.get("last_value_review")
            self.consecutive_failures = int(db_state.get("consecutive_failures", 0))

            logger.info("Estado cargado: cycle=%s, posts_today=%s, comments_today=%s, consecutive_failures=%s",
                        self.cycle_count, self.posts_today, self.comments_today, self.consecutive_failures)
        except Exception as e:
            logger.warning("Error cargando estado: %s. Iniciando desde cero.", e)
            self._reset_all()

        self._check_daily_reset()
        self._reconcile_from_persisted()

    def _reconcile_from_persisted(self) -> None:
        today = datetime.now().date().isoformat()
        try:
            # 
            published = _load_published_log()  # DISABLED: cuenta posts de published_posts.json
    # actual = sum(1 for p in published if p.get("published_at", "").startswith(today))  # DISABLED
            # 
            if actual > self.posts_today:  # DISABLED
    # logger.info("StateManager: cold-start reconciliation posts_today: %s -> %s", self.posts_today, actual)  # DISABLED
                # 
                self.posts_today = actual  # DISABLED
        except Exception as e:
            logger.debug("StateManager: could not reconcile posts_today: %s", e)
        try:
            import json
            from pathlib import Path
            path = Path("data/agent_comment_ids.json")
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    actual = sum(1 for v in data.values() if isinstance(v, dict) and v.get("timestamp", "").startswith(today))
                    if actual > self.comments_today:
                        logger.info("StateManager: cold-start reconciliation comments_today: %s -> %s", self.comments_today, actual)
                        self.comments_today = actual
        except Exception as e:
            logger.debug("StateManager: could not reconcile comments_today: %s", e)

    def _check_daily_reset(self) -> None:
        today = datetime.now().date().isoformat()
        if self.last_post_date != today:
            if self.posts_today > 0 or self.comments_today > 0:
                logger.info("Nuevo día (%s): reseteando posts_today=%s comments_today=%s a 0",
                            today, self.posts_today, self.comments_today)
                self.posts_today = 0
                self.comments_today = 0
            self.last_post_date = today
            self._save()
            send_event("state_reset_daily", {"date": today, "posts_today": self.posts_today, "comments_today": self.comments_today})

    def _save(self) -> None:
        db_state: Dict[str, Any] = {
            "cycle": int(self.cycle_count),
            "posts_today": int(self.posts_today),
            "comments_today": int(self.comments_today),
            "last_post_date": self.last_post_date,
            "last_post_timestamp": self.last_post_timestamp,  # v5.0: pacing
            "last_value_review": self.last_value_review,
            "consecutive_failures": int(self.consecutive_failures),
            "last_cycle_at": datetime.now().isoformat(),
            "version": "5.0",
        }
        save_agent_state(db_state)

    def save(self) -> None:
        self._save()
        send_event("state_saved", {"cycle": self.cycle_count, "posts_today": self.posts_today, "comments_today": self.comments_today})

    def increment_comments_today(self) -> int:
        self._check_daily_reset()
        self.comments_today += 1
        self._save()
        return self.comments_today

    def can_publish(self) -> bool:
        """v5.0: Pacing check — True if enough time has passed since last post."""
        if not self.last_post_timestamp:
            return True
        try:
            last = datetime.fromisoformat(self.last_post_timestamp)
            elapsed = datetime.now() - last
            if elapsed < timedelta(hours=PACING_MIN_HOURS):
                remaining = timedelta(hours=PACING_MIN_HOURS) - elapsed
                logger.info(
                    "Pacing: último post hace %.1f h. Próximo permitido en %d min.",
                    elapsed.total_seconds() / 3600,
                    int(remaining.total_seconds() / 60),
                )
                return False
        except (ValueError, TypeError):
            pass
        return True

    def mark_post_published(self) -> None:
        """v5.0: Record timestamp after successful publish for pacing."""
        self.last_post_timestamp = datetime.now().isoformat()
        self._save()

    def increment_posts_today(self) -> int:
        self._check_daily_reset()
        self.posts_today += 1
        self.mark_post_published()
        return self.posts_today

    def mark_value_review(self, review_path: str) -> None:
        self.last_value_review = datetime.now().isoformat()
        self._save()
        send_event("value_review_run", {"path": review_path})

    def _reset_all(self) -> None:
        self.cycle_count = 0
        self.posts_today = 0
        self.comments_today = 0
        self.last_post_date = None
        self.last_value_review = None
        self.consecutive_failures = 0

