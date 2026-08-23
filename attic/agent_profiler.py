import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class AgentProfiler:
    """
    Mantiene perfiles incrementales por agente externo (otros usuarios / agentes)
    a partir de los eventos que ya generamos en JSONL.
    """

    def __init__(self, datadir: Optional[Path] = None) -> None:
        self.datadir = datadir or Path("data")
        self.profiles_path = self.datadir / "agent_profiles.jsonl"
        self._profiles_cache: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def _utcnow(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load_profiles_once(self) -> None:
        if self._loaded:
            return
        if not self.profiles_path.exists():
            self._loaded = True
            return
        try:
            with open(self.profiles_path, "r", encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    author = record.get("author")
                    if author:
                        self._profiles_cache[author] = record
            self._loaded = True
            logger.info(f"AgentProfiler cargó {len(self._profiles_cache)} perfiles")
        except Exception as e:
            logger.error(f"Error cargando perfiles: {e}")
            self._loaded = True

    def _upsert_profile(self, author: str, update: Dict[str, Any]) -> None:
        self._load_profiles_once()
        current = self._profiles_cache.get(author, {
            "author": author,
            "first_seen_utc": self._utcnow(),
            "comments_observed": 0,
            "avg_comment_length": 0.0,
            "questions_ratio": 0.0,
            "critiques_ratio": 0.0,
            "replies_from_us": 0,
            "last_updated_utc": self._utcnow()
        })
        # Actualizar campos
        for k, v in update.items():
            if k == "comments_observed":
                current[k] = current.get(k, 0) + v
            elif k == "replies_from_us":
                current[k] = current.get(k, 0) + v
            elif k == "total_length":
                old_total = current.get("total_length", 0)
                current["total_length"] = old_total + v
                if current["comments_observed"] > 0:
                    current["avg_comment_length"] = current["total_length"] / current["comments_observed"]
            elif k == "questions_count":
                old_q = current.get("questions_count", 0)
                current["questions_count"] = old_q + v
                if current["comments_observed"] > 0:
                    current["questions_ratio"] = current["questions_count"] / current["comments_observed"]
            elif k == "critiques_count":
                old_c = current.get("critiques_count", 0)
                current["critiques_count"] = old_c + v
                if current["comments_observed"] > 0:
                    current["critiques_ratio"] = current["critiques_count"] / current["comments_observed"]
            else:
                current[k] = v
        current["last_updated_utc"] = self._utcnow()
        self._profiles_cache[author] = current
        # Escribir en JSONL (append)
        try:
            with open(self.profiles_path, "a", encoding="utf-8-sig") as f:
                f.write(json.dumps(current, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Error escribiendo perfil para {author}: {e}")

    def record_comment_event(self, event: Dict[str, Any]) -> None:
        """
        Procesa un evento de comentario (comment_observed, comment_reply_published, etc.)
        y actualiza el perfil del autor externo.
        """
        event_type = event.get("event_type")
        if not event_type:
            return
        author = None
        if "comment" in event:
            author = event["comment"].get("author")
        elif "observed" in event:
            author = event["observed"].get("author")
        if not author:
            return

        if event_type == "comment_observed":
            text = event.get("observed", {}).get("text", "")
            length = len(text) if text else 0
            update = {
                "comments_observed": 1,
                "total_length": length
            }
            text_lower = text.lower()
            if "?" in text:
                update["questions_count"] = 1
            if any(word in text_lower for word in ["crítica", "error", "mal", "debería"]):
                update["critiques_count"] = 1
            self._upsert_profile(author, update)

        elif event_type == "comment_reply_published":
            self._upsert_profile(author, {"replies_from_us": 1})

    def get_profile(self, author: str) -> Optional[Dict[str, Any]]:
        self._load_profiles_once()
        return self._profiles_cache.get(author)


_DEFAULT_PROFILER: Optional[AgentProfiler] = None


def get_profiler() -> AgentProfiler:
    global _DEFAULT_PROFILER
    if _DEFAULT_PROFILER is None:
        _DEFAULT_PROFILER = AgentProfiler()
    return _DEFAULT_PROFILER

