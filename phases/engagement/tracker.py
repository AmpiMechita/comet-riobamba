import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("phases.phase_c.tracker")

DEFAULT_OWN_NAMES = {"comet-riobamba", "cometriobamba", "comet riobamba"}

ACTOR_NAME_KEYS = [
    "username", "handle", "user_handle",
    "name", "display_name", "agent_name", "author",
]

ACTOR_ID_KEYS = [
    "author_id", "user_id", "creator_id", "owner_id", "profile_id",
]

NESTED_ACTOR_KEYS = ["author", "user", "creator", "owner", "profile"]


class Tracker:
    def __init__(self, data_dir: Path, identity: Dict):
        self.data_dir = data_dir
        self.identity = identity
        self.comment_events_path = data_dir / "comment_events.jsonl"
        self.reviews_path = data_dir / "conversation_reviews.jsonl"
        self.improvements_path = data_dir / "improvement_candidates.jsonl"
        self.blackboard_path = data_dir / "blackboard.jsonl"

    # ── JSONL helpers ─────────────────────────────────────────────

    def _append_jsonl(self, path: Path, payload: Dict) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Phase C: no se pudo escribir {path.name}: {e}")

    def _utc_now(self) -> str:
        return datetime.utcnow().isoformat() + "Z"

    # ── Tracked posts ─────────────────────────────────────────────

    def _tracked_posts_path(self) -> Path:
        return self.data_dir / "tracked_posts.json"

    def load_tracked_post_ids(self) -> List[str]:
        path = self._tracked_posts_path()
        try:
            if not path.exists():
                return []
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            ids = data.get("tracked_post_ids", []) if isinstance(data, dict) else []
            clean_ids = []
            for value in ids:
                text = str(value).strip()
                if text and text not in clean_ids:
                    clean_ids.append(text)
            return clean_ids
        except Exception as e:
            logger.warning(f"Phase C: no se pudo leer tracked_posts.json: {e}")
            return []

    def save_tracked_post_ids(self, post_ids: List[str]) -> None:
        path = self._tracked_posts_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            clean_ids = []
            for value in post_ids:
                text = str(value).strip()
                if text and text not in clean_ids:
                    clean_ids.append(text)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"tracked_post_ids": clean_ids}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Phase C: no se pudo escribir tracked_posts.json: {e}")

    def merge_tracked_posts(self, posts: List[Dict]) -> List[Dict]:
        tracked_ids = self.load_tracked_post_ids()
        if not tracked_ids:
            return posts if isinstance(posts, list) else []
        merged = []
        seen = set()
        for post in (posts or []):
            post_id = str(post.get("id") or "").strip()
            if post_id and post_id not in seen:
                merged.append(post)
                seen.add(post_id)
        for post_id in tracked_ids:
            if post_id not in seen:
                merged.append({
                    "id": post_id,
                    "title": f"Tracked post {post_id[:8]}",
                    "content": "",
                    "_tracked_only": True,
                })
                seen.add(post_id)
        return merged

    def register_post_id_if_missing(self, post_id: Optional[str]) -> None:
        text = str(post_id or "").strip()
        if not text:
            return
        tracked = self.load_tracked_post_ids()
        if text in tracked:
            return
        tracked.append(text)
        self.save_tracked_post_ids(tracked)
        logger.info(f"Phase C: post rastreado agregado {text}")

    # ── Comment dedup ─────────────────────────────────────────────

    def already_replied_to_comment(self, comment_id: str) -> bool:
        try:
            if not self.comment_events_path.exists():
                return False
            with open(self.comment_events_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        item = json.loads(line)
                        if (
                            item.get("event_type") == "comment_reply_attempt"
                            and item.get("comment_id") == comment_id
                            and item.get("success") is True
                        ):
                            return True
                    except Exception:
                        continue
        except Exception:
            return False
        return False

    def count_successful_replies_today(self) -> int:
        try:
            if not self.comment_events_path.exists():
                return 0
            today = datetime.now().date()
            count = 0
            with open(self.comment_events_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except Exception:
                        continue
                    if item.get("event_type") != "comment_reply_published":
                        continue
                    ts = item.get("timestamp_utc")
                    if not ts:
                        continue
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except Exception:
                        continue
                    if dt.date() == today:
                        count += 1
            return count
        except Exception as e:
            logger.warning(f"Phase C: no se pudo contar replies del día: {e}")
            return 0

    # ── Identity helpers ──────────────────────────────────────────

    def normalize_actor_name(self, value) -> str:
        if isinstance(value, str):
            text = value.strip().lower()
            if text.startswith("@"):
                text = text[1:]
            return text
        if isinstance(value, dict):
            for key in ACTOR_NAME_KEYS:
                inner = value.get(key)
                if isinstance(inner, str) and inner.strip():
                    text = inner.strip().lower()
                    if text.startswith("@"):
                        text = text[1:]
                    return text
            return ""
        return ""

    def collect_identity_candidates(self, obj: Dict) -> Set[str]:
        candidates = set()
        if not isinstance(obj, dict):
            return candidates
        for key in ACTOR_NAME_KEYS:
            value = obj.get(key)
            normalized = self.normalize_actor_name(value)
            if normalized:
                candidates.add(normalized)
        for key in NESTED_ACTOR_KEYS:
            value = obj.get(key)
            if isinstance(value, dict):
                for inner_key in ACTOR_NAME_KEYS:
                    normalized = self.normalize_actor_name(value.get(inner_key))
                    if normalized:
                        candidates.add(normalized)
        return candidates

    def collect_identity_ids(self, obj: Dict) -> Set[str]:
        ids = set()
        if not isinstance(obj, dict):
            return ids
        for key in ACTOR_ID_KEYS:
            value = obj.get(key)
            if value is not None and str(value).strip():
                ids.add(str(value).strip())
        for key in NESTED_ACTOR_KEYS:
            value = obj.get(key)
            if isinstance(value, dict):
                for inner_key in ["id", "_id", "user_id", "author_id", "profile_id"]:
                    inner = value.get(inner_key)
                    if inner is not None and str(inner).strip():
                        ids.add(str(inner).strip())
        return ids

    def get_own_identity_names(self) -> Set[str]:
        names = set()
        identity = self.identity if isinstance(self.identity, dict) else {}
        for key in ["agent_name", "username", "handle", "user_handle", "display_name", "name"]:
            value = identity.get(key)
            normalized = self.normalize_actor_name(value)
            if normalized:
                names.add(normalized)
        try:
            from config import behavior_cfg
            for key in ["agent_handle", "agent_name", "username"]:
                value = getattr(behavior_cfg, key, None)
                normalized = self.normalize_actor_name(value)
                if normalized:
                    names.add(normalized)
        except Exception:
            pass
        names.update(DEFAULT_OWN_NAMES)
        return {x for x in names if x}

    def get_own_identity_ids(self) -> Set[str]:
        ids = set()
        identity = self.identity if isinstance(self.identity, dict) else {}
        for key in ["id", "_id", "user_id", "author_id", "profile_id"]:
            value = identity.get(key)
            if value is not None and str(value).strip():
                ids.add(str(value).strip())
        return ids

    def matches_our_identity(self, obj: Dict) -> bool:
        candidate_names = self.collect_identity_candidates(obj)
        candidate_ids = self.collect_identity_ids(obj)
        own_names = self.get_own_identity_names()
        own_ids = self.get_own_identity_ids()
        if own_ids and candidate_ids and (own_ids & candidate_ids):
            return True
        if own_names and candidate_names and (own_names & candidate_names):
            return True
        return False

    def is_our_post(self, post: Dict) -> bool:
        return self.matches_our_identity(post)

    def is_own_comment(self, comment: Dict) -> bool:
        return self.matches_our_identity(comment)

    def detect_thread_source_type(self, post: Dict, comment: Dict) -> str:
        if comment.get("source_type") in ("own_post", "own_comment"):
            return comment.get("source_type")
        if comment.get("parent_id") in (None, ""):
            return "own_post"
        parent_stub = {
            "author": comment.get("parent_author"),
            "username": comment.get("parent_username"),
            "handle": comment.get("parent_handle"),
            "user_handle": comment.get("parent_user_handle"),
            "author_id": comment.get("parent_author_id"),
            "user_id": comment.get("parent_user_id"),
        }
        if comment.get("parent") and isinstance(comment.get("parent"), dict):
            parent_stub.update(comment.get("parent"))
        if comment.get("reply_to") and isinstance(comment.get("reply_to"), dict):
            parent_stub.update(comment.get("reply_to"))
        if comment.get("parent_id") and self.matches_our_identity(parent_stub):
            return "own_comment"
        if self.matches_our_identity(parent_stub):
            return "own_comment"
        return "unknown"

    def can_consider_comment(self, post: Dict, comment: Dict, should_track_callback) -> Tuple[bool, str]:
        source_type = self.detect_thread_source_type(post, comment)
        if source_type == "unknown":
            return False, source_type
        if should_track_callback:
            return bool(should_track_callback(source_type)), source_type
        if source_type in ("own_post", "own_comment"):
            return True, source_type
        return False, source_type

    # ── Event logging ─────────────────────────────────────────────

    def log_comment_event(self, event_type: str, payload: Dict) -> None:
        event = {
            "timestamp_utc": self._utc_now(),
            "event_type": event_type,
            "agent_name": self.identity.get("agent_name", "COMET-RIOBAMBA"),
            **payload,
        }
        self._append_jsonl(self.comment_events_path, event)

    def log_review(self, payload: Dict) -> None:
        event = {
            "timestamp_utc": self._utc_now(),
            "agent_name": self.identity.get("agent_name", "COMET-RIOBAMBA"),
            **payload,
        }
        self._append_jsonl(self.reviews_path, event)

    def log_improvement_candidate(self, payload: Dict) -> None:
        event = {
            "timestamp_utc": self._utc_now(),
            "agent_name": self.identity.get("agent_name", "COMET-RIOBAMBA"),
            **payload,
        }
        self._append_jsonl(self.improvements_path, event)

    def log_blackboard(self, payload: Dict) -> None:
        event = {
            "timestamp_utc": self._utc_now(),
            "sender": self.identity.get("agent_name", "COMET-RIOBAMBA"),
            **payload,
        }
        self._append_jsonl(self.blackboard_path, event)

    def build_review_for_cycle(self, observed_comments: List[Dict], published_replies: List[Dict]) -> None:
        if not observed_comments:
            return
        types = {}
        for item in observed_comments:
            ctype = item.get("comment_type", "unknown")
            types[ctype] = types.get(ctype, 0) + 1
        review = {
            "event_type": "conversation_review",
            "goal": "mantener o incrementar la discusión con contenido de mayor calidad",
            "what_happened": {
                "comments_observed": len(observed_comments),
                "replies_published": len(published_replies),
                "comment_types": types,
            },
            "what_worked": [x for x in ["preguntas detectadas", "críticas priorizadas", "aportes con evidencia capturados"] if types],
            "what_needs_improvement": [
                "mejorar clasificación semántica",
                "detectar referencias cruzadas con mayor precisión",
                "convertir patrones repetidos en mejoras editoriales",
            ],
        }
        self.log_review(review)
        if types.get("critique", 0) >= 2 or types.get("question", 0) >= 3:
            self.log_improvement_candidate({
                "event_type": "improvement_candidate",
                "finding": "alto volumen de preguntas o críticas en comentarios de posts propios",
                "interpretation": "el contenido despierta interés pero necesita más claridad, estructura o evidencia",
                "proposed_change": "reforzar prompts de fase A para incluir mecanismo, proceso y criterio de evaluación",
                "expected_result": "mayor calidad de discusión y menos ambigüedad inicial",
                "status": "proposed",
            })
            self.log_blackboard({
                "type": "proposal",
                "target": "all",
                "topic": "content_quality_improvement",
                "priority": "high",
                "confidence": 0.72,
                "ttl": 7,
                "recommended_action": "ajustar prompts editoriales y priorizar respuestas con profundidad metodológica",
            })
