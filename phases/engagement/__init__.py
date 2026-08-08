import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import behavior_cfg
from core.write_policy import WriteRequest
from phases.deps import PhaseCDeps
from phases.engagement.classifier import Classifier
from phases.engagement.responder import Responder
from phases.engagement.tracker import Tracker
from services import reply_cap
from utils.phase_utils import phase_error_boundary, validate_phase_deps

logger = logging.getLogger("phases.phase_c.engagement")

# Tech keywords for comment triage (Phase C own-post context).
_TRIAGE_TECH = frozenset({
    "agent", "ai", "model", "data", "system", "error", "loop", "policy",
    "api", "log", "monitor", "observability", "cascade", "prompt", "token",
    "llm", "autonomous", "tool", "deployment", "pipeline",
    "latency", "throughput", "security", "architecture", "design",
    "memory", "reasoning", "planning", "benchmark", "metric",
    "circuit breaker", "rate limit", "guardrail", "fallback",
    "scaling", "orchestration",
    "fail", "failure", "bug", "break", "problem", "issue",
})


class PhaseCEngagement:
    """
    Fase C Engagement: detecta comentarios en posts propios del feed,
    clasifica, prioriza, genera respuestas y las publica.
    """

    def __init__(self, deps: PhaseCDeps):
        self.deps = deps
        validate_phase_deps(deps, ["model_cascade", "moltbook_client", "write_policy"])
        self.data_dir = Path("data")
        self.identity = self._load_agent_identity()

        self.tracker = Tracker(self.data_dir, self.identity)
        self.classifier = Classifier()
        self.responder = Responder(
            model_cascade=deps.model_cascade,
            write_policy=deps.write_policy,
            moltbook_client=deps.moltbook_client,
            tracker=self.tracker,
        )

    def _load_agent_identity(self) -> Dict:
        try:
            identity_path = Path("config") / "agent_identity.json"
            if identity_path.exists():
                with open(identity_path, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Phase C: no se pudo cargar agent_identity.json: {e}")
        return {"agent_name": "COMET-RIOBAMBA"}

    @phase_error_boundary(logger, "phase_c_engagement", fallback_return=[])
    async def execute(self) -> List[Dict]:
        if getattr(behavior_cfg, "whisper_mode", False):
            logger.info("Modo whisper: fase C simulada")
            return []

        self.responder._local_generation_disabled = False

        published_replies: List[Dict] = []
        observed_comments: List[Dict] = []
        replies_per_post: Counter = Counter()

        replies_today = self.tracker.count_successful_replies_today()
        max_day = int(self.deps.max_phase_c_replies_per_day)
        if replies_today >= max_day:
            logger.info(f"Phase C: límite diario alcanzado ({replies_today}/{max_day})")
            return []

        max_cycle = int(self.deps.max_phase_c_replies_per_cycle)
        replies_this_cycle = 0

        posts = self.responder.extract_posts_with_activity()
        logger.info(f"Phase C: {len(posts)} posts propios obtenidos")

        for post in posts:
            post_id = post.get("id")
            if not post_id:
                continue

            comments = self.responder.extract_comments_for_post(post_id)

            for raw_comment in comments:
                comment = self.responder.normalize_comment_payload(raw_comment)
                logger.info(
                    "Phase C DEBUG: normalized comment id=%s author=%s author_id=%s parent_id=%s text=%s",
                    comment.get("id"),
                    comment.get("author"),
                    comment.get("author_id"),
                    comment.get("parent_id"),
                    (comment.get("text") or "")[:80],
                )

                if replies_this_cycle >= max_cycle:
                    logger.info(f"Phase C: límite por ciclo alcanzado ({replies_this_cycle}/{max_cycle})")
                    self.tracker.build_review_for_cycle(observed_comments, published_replies)
                    return published_replies

                if replies_today >= max_day:
                    logger.info(f"Phase C: límite diario alcanzado durante el ciclo ({replies_today}/{max_day})")
                    self.tracker.build_review_for_cycle(observed_comments, published_replies)
                    return published_replies

                if self.tracker.is_own_comment(comment):
                    logger.info(
                        "Phase C DEBUG: skip own_comment comment_id=%s author=%s author_id=%s",
                        comment.get("id"),
                        comment.get("author"),
                        comment.get("author_id"),
                    )
                    continue

                should_track, source_type = self.tracker.can_consider_comment(
                    post, comment, self.deps.should_track_phase_c_thread,
                )
                if not should_track:
                    logger.info(
                        "Phase C DEBUG: skip not_tracked comment_id=%s source_type=%s author=%s parent_id=%s parent_author=%s",
                        comment.get("id"),
                        source_type,
                        comment.get("author"),
                        comment.get("parent_id"),
                        comment.get("parent_author"),
                    )
                    continue

                comment_id = comment.get("id")
                if comment_id and (
                    self.tracker.already_replied_to_comment(comment_id)
                    or reply_cap.has_replied_to_comment(f"{post_id}:{comment_id}")
                ):
                    logger.info(
                        "Phase C DEBUG: skip already_replied comment_id=%s author=%s",
                        comment_id,
                        comment.get("author"),
                    )
                    continue

                own_names = self.tracker.get_own_identity_names()
                comment_text = comment.get("content") or comment.get("text") or ""
                # ── Triage: skip comments that don't deserve a reply ──
                from phases.phase_b.scoring import _triage_comment_value
                skip_triage, triage_reason = _triage_comment_value(
                    comment_text, tech_keywords=_TRIAGE_TECH,
                )
                if skip_triage:
                    logger.info(
                        "triage: skip low-value comment (%s) comment_id=%s",
                        triage_reason, comment_id,
                    )
                    continue
                comment_type = self.classifier.classify_comment(comment_text)
                priority = self.classifier.priority_score(comment_type, comment_text)
                logger.info(
                    "Phase C DEBUG: decision comment_id=%s type=%s priority=%s text=%s",
                    comment.get("id"),
                    comment_type,
                    priority,
                    (comment_text or "")[:120],
                )

                observed = {
                    "post_id": post_id,
                    "post_title": post.get("title"),
                    "comment_id": comment_id,
                    "parent_id": comment.get("parent_id"),
                    "author": comment.get("author") or comment.get("username"),
                    "text": comment_text,
                    "is_on_our_post": source_type == "own_post",
                    "source_type": source_type,
                    "comment_type": comment_type,
                    "priority_score": priority,
                    "responded": False,
                }
                observed_comments.append(observed)
                self.tracker.log_comment_event("comment_observed", observed)

                if replies_per_post[post_id] >= 3:
                    logger.info("Phase C: reply omitido por límite de 3 respuestas en este post")
                    continue

                if not self.classifier.should_reply(comment_type, priority, comment_text, own_names):
                    logger.info("Phase C: reply omitido porque no es pregunta directa al agente")
                    continue

                reply_text = await self.responder.generate_reply(post, comment, self.identity)
                if not reply_text:
                    continue

                if not self.classifier.looks_mostly_english(reply_text):
                    logger.info("Phase C: reply omitido por no parecer mayormente en inglés")
                    continue

                req = WriteRequest(
                    write_type="reply",
                    title=None,
                    body=reply_text,
                    submolt=(post.get("submolt") or post.get("submolt_name") or "general"),
                    thread_id=post_id,
                    topic_key=((post.get("submolt") or post.get("submolt_name") or "general").strip().lower().replace(" ", "_")),
                    now=datetime.now(),
                    phase="C",
                )

                decision = self.deps.write_policy.decide(req)
                if not decision.allowed:
                    logger.info(f"Phase C: reply bloqueado por política en post {post_id}: {decision.reason}")
                    continue

                publish_result = await self.responder.publish_reply(post_id, reply_text, post, comment)

                success = publish_result.get("success", False) if publish_result else False
                error_text = publish_result.get("error") if publish_result else "unknown_error"
                reply_id = publish_result.get("reply_id") if publish_result else None

                response_payload = {
                    "post_id": post_id,
                    "comment_id": comment_id,
                    "response_text": reply_text,
                    "response_id": reply_id,
                    "success": success,
                    "error": error_text,
                    "comment_type": comment_type,
                    "priority_score": priority,
                    "source_type": source_type,
                }
                self.tracker.log_comment_event("comment_reply_attempt", response_payload)

                if success:
                    reply_cap.mark_replied_to_comment(f"{post_id}:{comment_id}")
                    replies_per_post[post_id] += 1
                    self.deps.write_policy.log_write(req, str(reply_id or post_id))
                    replies_this_cycle += 1
                    replies_today += 1
                    observed["responded"] = True
                    published_replies.append({
                        "post_id": post_id,
                        "comment_id": comment_id,
                        "reply_id": reply_id,
                        "content": reply_text,
                        "source_type": source_type,
                    })
                    self.tracker.log_comment_event("comment_reply_published", {
                        "post_id": post_id,
                        "comment_id": comment_id,
                        "reply_id": reply_id,
                        "source_type": source_type,
                        "comment_type": comment_type,
                        "priority_score": priority,
                    })
                    logger.info(
                        f"Phase C: Reply publicado en {str(post_id)[:8]}... "
                        f"respondiendo a {comment.get('author') or comment.get('username')} "
                        f"| source_type={source_type} | ciclo={replies_this_cycle}/{max_cycle}"
                    )

        self.tracker.build_review_for_cycle(observed_comments, published_replies)
        return published_replies
