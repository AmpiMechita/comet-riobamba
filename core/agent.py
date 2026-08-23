# -*- coding: utf-8 -*-
"""
COMET-RIOBAMBA v4.3.0 - Core Agent Module
Agente autónomo para generación y publicación de contenido técnico en IA/ML.
"""
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import behavior_cfg, content_cfg
from config.agent_policy import POLICY
from config.config import validate_config
from config.credentials import Credentials
from core.observability import send_event
from core.state_manager import AgentState
from core.tracer import Span
from core.value_review import run_value_review
from core.write_policy import WritePolicyEngine
from services.self_eval import update_today_metrics
from core.challenge_solver import LLMClientAdapter
from core.self_monitor import SelfMonitor
from services.model_cascade import ModelCascade
from services.moltbook_api_client import MoltbookAPIClient, is_parent_not_found_404
from services.platform_awareness import PlatformAwareness
from services.reply_cap import mark_unrepliable_comment, mark_replied_to_comment
from services.dedup_store import DedupStore
from services.telegram_client import create_telegram_client
from services.deepseek_balance import (
    check_deepseek_balance, was_balance_sent_today,
    mark_balance_sent, format_balance_message,
)
from services.persistence import (
    fetch_pending_outbox,
    mark_outbox,
    update_outbox_backoff,
    enqueue_outbox,
)
from services.global_circuit import (
    should_skip_cycle,
    get_current_interval,
    register_cycle_result,
)
from phases.deps import PhaseADeps, PhaseBDeps, PhaseCDeps
from phases.phase_a_content import PhaseAContentGeneration
from phases.phase_b import PhaseB
from phases.phase_c_analytics import PhaseCAnalytics
from phases.engagement import PhaseCEngagement

logger = logging.getLogger("core.agent")


def _write_json_atomic(path: Path, data: Any, **json_kwargs) -> None:
    """Escribe JSON de forma atómica: temp file + os.replace().

    Garantiza que el archivo destino nunca queda en estado truncado/corrupto
    incluso si el proceso se interrumpe durante la escritura.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, **json_kwargs)
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


class COMETRiobambaAgent:
    def __init__(
        self,
        credentials: Optional[Credentials] = None,
        model_cascade: Optional[ModelCascade] = None,
        moltbook_client: Optional[MoltbookAPIClient] = None,
    ):
        self.version = "5.0"
        self.config_version = content_cfg.get("config_version", "5.0")
        self.start_time = datetime.now()
        self.shutdown_requested = False
        self._last_watchdog_check = 0.0
        self.state = AgentState()

        from config import BASE_DIR
        logger.info("Working Directory: %s | BASE_DIR: %s", os.getcwd(), BASE_DIR)

        if credentials is None:
            credentials = Credentials.from_env()
        self.credentials = credentials
        self.model_cascade = model_cascade or ModelCascade(credentials=credentials, agent=self)
        self.moltbook_api_client = moltbook_client or MoltbookAPIClient(
    credentials=credentials,
    llm_client=LLMClientAdapter(self.model_cascade),
)

        try:
            self.platform_awareness = PlatformAwareness(agent=self)
            self._platform_awareness_available = True
        except Exception as e:
            logger.warning("⚠ PlatformAwareness no disponible: %s. Usando logging fallback.", e)
            self.platform_awareness = None
            self._platform_awareness_available = False

        self.telegram_client = create_telegram_client()
        if self.telegram_client and self.telegram_client.enabled:
            if not self._test_telegram_connection():
                logger.warning("⚠ Telegram: conexión no verificada. Revisar BOT_TOKEN y CHAT_ID en .env")

        self.write_policy = WritePolicyEngine(behavior_cfg, Path("data"))
        self._pending_home_posts: Set[str] = set()
        self._last_announcement_id: Optional[str] = None
        self._home_dashboard_enabled: bool = os.getenv("HOME_DASHBOARD_ENABLED", "true").lower() == "true"

        self._phase_a_deps = PhaseADeps(
            model_cascade=self.model_cascade,
            moltbook_client=self.moltbook_api_client,
            behavior_cfg=behavior_cfg,
            posts_today=self.state.posts_today,
            get_posts_today=lambda: self.state.posts_today,
        )
        self._phase_b_deps = PhaseBDeps(
            model_cascade=self.model_cascade,
            moltbook_client=self.moltbook_api_client,
            behavior_cfg=behavior_cfg,
            agent_name="comet_riobamba",
            posts_today=self.state.posts_today,
            get_posts_today=lambda: self.state.posts_today,
            get_comments_today=lambda: self.state.comments_today,
            increment_comments_today=lambda: self.state.increment_comments_today(),
            pending_home_post_ids=self._pending_home_posts,
        )
        self._phase_c_deps = PhaseCDeps(
            model_cascade=self.model_cascade,
            moltbook_client=self.moltbook_api_client,
            write_policy=self.write_policy,
            telegram_client=self.telegram_client,
            behavior_cfg=behavior_cfg,
            content_cfg=content_cfg,
            cycle_count=self.state.cycle_count,
            agent_name="COMET-RIOBAMBA",
            max_phase_c_replies_per_day=POLICY.max_phase_c_replies_per_day,
            max_phase_c_replies_per_cycle=POLICY.max_phase_c_replies_per_cycle,
            should_track_phase_c_thread=getattr(self, "should_track_phase_c_thread", None),
            get_comments_today=lambda: self.state.comments_today,
            increment_comments_today=lambda: self.state.increment_comments_today(),
        )
        self._phase_a: Optional[PhaseAContentGeneration] = None
        self._phase_b: Optional[PhaseB] = None
        self._phase_c: Optional[PhaseCAnalytics] = None
        self._phase_c_engagement: Optional[PhaseCEngagement] = None

        self.state_file = Path("data/state/agent_state.json")
        self.health_file = Path("data/state/health.json")
        # Graceful stop without OS signals: create data/stop.flag to request a
        # clean shutdown (detected within 1s in the main loop). Reliable on
        # Windows where SIGINT/CTRL_BREAK to a child process is not available.
        self.stop_flag_file = Path("data/stop.flag")
        # Hold de mantenimiento (data/maintenance.flag): shutdown graceful que NO
        # borra el flag (a diferencia de stop.flag), de modo que el watchdog lo
        # sigue respetando y NO relanza el agente. Solo se quita a mano.
        self.maintenance_flag_file = Path("data/maintenance.flag")
        self.last_phase_b_run_at = time.time()
        # Load last seen announcement ID from disk
        try:
            ann_path = Path("data/last_announcement.json")
            if ann_path.exists():
                data = json.loads(ann_path.read_text(encoding="utf-8"))
                self._last_announcement_id = data.get("last_seen_id") or data.get("id")
        except Exception:
            self._last_announcement_id = None

        logger.info("Agente inicializado: %s", self.version)
        if self.telegram_client and self.telegram_client.enabled:
            logger.info("✅ Telegram monitoring enabled")

    def _test_telegram_connection(self) -> bool:
        if not self.telegram_client:
            return False
        try:
            return self.telegram_client.send_message(
                " COMET-RIOBAMBA: prueba de conexión",
                disable_notification=True,
            )
        except Exception as e:
            logger.warning("Telegram test failed: %s", e)
            return False

    def _maybe_send_daily_balance(self) -> None:
        """Send DeepSeek balance via Telegram once per day (first cycle of the day)."""
        if not self.telegram_client or not self.telegram_client.enabled:
            return
        if was_balance_sent_today():
            return
        try:
            balance = check_deepseek_balance()
            if balance is None:
                logger.info("DeepSeek balance check: no se pudo obtener saldo, omitido.")
                return
            msg = format_balance_message(balance, self.cycle_count)
            self.telegram_client.send_message(msg, parse_mode="HTML")
            mark_balance_sent()
            logger.info("💰 DeepSeek balance enviado por Telegram: $%.2f USD", balance)
        except Exception as e:
            logger.warning("Error en balance diario: %s", e)

    def _maybe_send_nightly_inbound_report(self) -> None:
        """Send nightly Watchlist Inbound report via Telegram once per day (default 21:00)."""
        if not self.telegram_client or not self.telegram_client.enabled:
            return
        try:
            from services.telegram_control import should_send_inbound_report, generate_inbound_report, mark_inbound_report_sent
            if should_send_inbound_report():
                report_msg = generate_inbound_report()
                self.telegram_client.send_message(report_msg, parse_mode="HTML")
                mark_inbound_report_sent()
                logger.info("🎯 Reporte nocturno de Watchlist Inbound enviado por Telegram")
        except Exception as e:
            logger.warning("Error enviando reporte inbound nocturno: %s", e)

    def _maybe_run_nightly_reflection(self) -> None:
        """Distila las interacciones del dia en topics de agenda (cadencia
        interna diaria; fail-safe: si falla, nunca rompe el ciclo)."""
        try:
            from services.nightly_reflection import run_reflection
            res = run_reflection()
            if res.get("ran"):
                logger.info(
                    "Reflexion nocturna: %s eventos, %s topics añadidos a la agenda.",
                    res.get("events_seen", 0), res.get("topics_added", 0),
                )
        except Exception as e:
            logger.warning("Reflexion nocturna skip: %s", e)

    def _safe_record_action(self, action: str, success: bool = False, details: str = ""):
        if self._platform_awareness_available and self.platform_awareness:
            try:
                if hasattr(self.platform_awareness, "register_action"):
                    self.platform_awareness.register_action(action, success=success, details=details)
                else:
                    logger.info("✨ Acción '%s' registrada (logging fallback)", action)
            except AttributeError:
                logger.info("✨ Acción '%s' registrada (logging fallback)", action)
            except Exception as e:
                logger.warning("⚠ Error registrando acción '%s': %s", action, e)
        else:
            logger.info("✨ Acción '%s' registrada (logging fallback)", action)

    @property
    def cycle_count(self) -> int:
        return self.state.cycle_count

    @cycle_count.setter
    def cycle_count(self, value: int) -> None:
        self.state.cycle_count = value

    @property
    def posts_today(self) -> int:
        return self.state.posts_today

    @property
    def comments_today(self) -> int:
        return self.state.comments_today

    @property
    def consecutive_failures(self) -> int:
        return self.state.consecutive_failures

    @consecutive_failures.setter
    def consecutive_failures(self, value: int) -> None:
        self.state.consecutive_failures = value

    @property
    def _last_value_review(self):
        return self.state.last_value_review

    @_last_value_review.setter
    def _last_value_review(self, value):
        self.state.last_value_review = value

    def _retry_outbox(self) -> int:
        """Retry pending posts from the SQLite outbox table.

        Classifies failures to prevent duplicate posts after ambiguous errors:
        - 4xx validation errors → 'failed' (do not retry).
        - 429 rate-limit → 'pending' with Retry-After delay from server.
        - Timeout / network exception → 'needs_reconciliation' (must be manually
          reviewed before retrying — the request may have reached Moltbook).
        - 5xx / other → 'pending' with backoff (safe to retry).
        """
        published = 0

        pending = fetch_pending_outbox(limit=10)
        post_items = [item for item in pending if item.get("kind") == "post"]
        if not post_items:
            return 0

        logger.info("Outbox: reintentando %s posts pendientes antes de Fase A...", len(post_items))

        max_posts = behavior_cfg.get("max_posts_per_day", POLICY.max_posts_per_day)
        min_backoff = POLICY.outbox_min_backoff_seconds
        max_backoff = POLICY.outbox_max_backoff_seconds

        for item in post_items:
            if self.state.posts_today >= max_posts:
                logger.info("Outbox: límite diario alcanzado, difiriendo posts restantes")
                break

            payload = item.get("payload", {})
            try:
                result = self.moltbook_api_client.create_post(
                    title=payload.get("title"),
                    body=payload.get("body"),
                    metadata=payload.get("metadata", {}),
                )
                http_status = result.get("status") or 0
                if result.get("success") or http_status == 201:
                    published += 1
                    self.state.increment_posts_today()
                    self._safe_record_action("create_post", success=True)
                    mark_outbox(item["id"], "published")
                    logger.info("Outbox: post publicado exitosamente (ID: %s)", result.get("id"))
                elif http_status == 429:
                    # Rate-limit: use the Retry-After value the server returned
                    # instead of generic exponential backoff.
                    retry_after = result.get("retry_after_seconds")
                    retry_attempt = item.get("retry_attempt", 0) + 1
                    capped = min(retry_after or 60, max_backoff)
                    update_outbox_backoff(
                        item["id"], str(result)[:200], retry_attempt,
                        min_backoff, max_backoff,
                        explicit_delay_seconds=capped,
                    )
                    logger.warning(
                        "Outbox: 429 rate-limit (Retry-After=%ss, capped=%ss), retry_attempt=%s",
                        retry_after, capped, retry_attempt,
                    )
                elif 400 <= http_status < 500:
                    # Client error: validation, auth, forbidden — not retryable.
                    mark_outbox(item["id"], "failed", str(result)[:200])
                    logger.warning("Outbox: post marcado 'failed' (HTTP %s)", http_status)
                else:
                    # 5xx / unknown — safe to retry with backoff.
                    retry_attempt = item.get("retry_attempt", 0) + 1
                    update_outbox_backoff(item["id"], str(result)[:200], retry_attempt, min_backoff, max_backoff)
                    logger.warning("Outbox: fallo post, retry_attempt=%s", retry_attempt)
            except Exception as e:
                # Network exception / timeout — ambiguous: the request may have
                # reached Moltbook. Do NOT retry automatically.
                mark_outbox(item["id"], "needs_reconciliation", str(e)[:200])
                logger.warning(
                    "Outbox: post marcado 'needs_reconciliation' tras excepción de red: %s", e
                )

        return published

    # TODO 5.0-LP1: Post outbox migrated to SQLite (was JSON data/outbox.db)

    def _check_home_dashboard(self) -> None:
        """Fetch /home dashboard at cycle start, log summary, detect new activity and announcements."""
        with Span("home_dashboard"):
            if not self._home_dashboard_enabled:
                return
            try:
                home = self.moltbook_api_client.fetch_home_dashboard()
                if not home:
                    return

                logger.info(
                    "Agent home: karma=%s, unread_notifications=%s, active_posts=%s",
                    home.get("karma", "?"),
                    home.get("unread_notifications", "?"),
                    home.get("active_posts", "?"),
                )

                # ── Karma change alert ──────────────────────────────────
                try:
                    alert_state_path = Path("data/telegram_alert_state.json")
                    alert_state: Dict = {}
                    if alert_state_path.exists():
                        alert_state = json.loads(alert_state_path.read_text(encoding="utf-8")) or {}
                    last_karma = alert_state.get("last_karma")
                    current_karma = home.get("karma")
                    if (
                        last_karma is not None
                        and current_karma is not None
                        and self.telegram_client
                        and self.telegram_client.enabled
                    ):
                        from services.telegram_control import check_karma_change
                        alert = check_karma_change(current_karma, last_karma)
                        if alert:
                            self.telegram_client.send_message(alert)
                    alert_state["last_karma"] = current_karma
                    _write_json_atomic(alert_state_path, alert_state, ensure_ascii=False)
                except Exception as e:
                    logger.debug("Home: karma alert check failed: %s", e)

                # ── New activity on own posts ───────────────────────────
                activity_posts: List[Dict] = home.get("activity_on_your_posts") or []
                pending: Set[str] = set()
                for post in activity_posts:
                    if post.get("new_notification_count", 0) > 0:
                        pid = post.get("id") or post.get("post_id") or ""
                        title = post.get("post_title") or post.get("title", "?")
                        commenters = post.get("authors") or post.get("latest_commenters") or []
                        logger.info(
                            'Agent home: post "%s" has %s new comment(s) from %s',
                            title, post["new_notification_count"], ", ".join(commenters) or "unknown",
                        )
                        if pid:
                            pending.add(pid)
                        if pid and self.telegram_client and self.telegram_client.enabled:
                            try:
                                from services.telegram_control import check_engagement_spike
                                alert = check_engagement_spike(
                                    pid, post.get("new_notification_count", 0), threshold=5
                                )
                                if alert:
                                    self.telegram_client.send_message(alert)
                            except Exception as e:
                                logger.debug("Home: engagement spike alert failed: %s", e)
                self._pending_home_posts.clear()
                self._pending_home_posts.update(pending)
                update_today_metrics(home_reads_today=1)

                # ── New Moltbook announcement ───────────────────────────
                announcement = home.get("latest_moltbook_announcement")
                if announcement and isinstance(announcement, dict):
                    ann_id = announcement.get("id") or ""
                    if ann_id and ann_id != self._last_announcement_id:
                        logger.info(
                            'Agent home: new Moltbook announcement — "%s"',
                            announcement.get("title", "?"),
                        )
                        self._last_announcement_id = ann_id
                        # Persist last seen announcement ID
                        try:
                            ann_path = Path("data/last_announcement.json")
                            _write_json_atomic(ann_path, {"last_seen_id": ann_id}, ensure_ascii=False)
                        except Exception as e:
                            logger.debug("Home: could not persist announcement id: %s", e)

                # ── Quality issues alert (once per cycle) ───────────────
                if self.telegram_client and self.telegram_client.enabled:
                    try:
                        from services.telegram_control import check_recent_quality_issues
                        alert = check_recent_quality_issues()
                        if alert:
                            self.telegram_client.send_message(alert)
                    except Exception as e:
                        logger.debug("Home: quality issues alert failed: %s", e)

                # ── Off-niche topics alert (once per cycle) ─────────────
                if self.telegram_client and self.telegram_client.enabled:
                    try:
                        from services.telegram_control import check_recent_off_niche_issues
                        alert = check_recent_off_niche_issues()
                        if alert:
                            self.telegram_client.send_message(alert)
                    except Exception as e:
                        logger.debug("Home: off_niche alert failed: %s", e)

                # ── Phase B feed stall alert (once per cycle) ───────────
                if self.telegram_client and self.telegram_client.enabled:
                    try:
                        from services.telegram_control import check_feed_stalled
                        alert = check_feed_stalled()
                        if alert:
                            self.telegram_client.send_message(alert)
                    except Exception as e:
                        logger.debug("Home: feed stalled alert failed: %s", e)

            except Exception as e:
                logger.warning("Home dashboard check failed (continuing cycle): %s", e)

    def _retry_comment_outbox(self) -> int:
        published = 0
        pending = fetch_pending_outbox(limit=10)
        comment_items = [item for item in pending if item.get("kind") == "comment"]
        if not comment_items:
            return 0

        logger.info("Comment outbox: reintentando %s comentarios pendientes...", len(comment_items))
        max_daily = behavior_cfg.get("max_comments_per_day", POLICY.max_comments_per_day)
        min_backoff = POLICY.outbox_min_backoff_seconds
        max_backoff = POLICY.outbox_max_backoff_seconds

        for item in comment_items:
            if int(self.state.posts_today) + int(self.state.comments_today) >= max_daily:
                logger.info("Comment outbox: límite diario alcanzado, difiriendo %s items restantes", len(comment_items) - published)
                break

            payload = item.get("payload", {})
            post_id = payload.get("post_id")
            content = payload.get("content")
            parent_comment_id = payload.get("parent_comment_id")

            if not post_id or not content:
                logger.warning("Comment outbox: item %s inválido, marcando como failed", item.get("id"))
                mark_outbox(item["id"], "failed", "payload inválido")
                continue

            try:
                result = self.moltbook_api_client.create_comment(
                    post_id=str(post_id),
                    content=content,
                    parent_comment_id=str(parent_comment_id) if parent_comment_id else None,
                )
                success = False
                if isinstance(result, dict):
                    success = bool(result.get("success"))
                else:
                    success = bool(getattr(result, "success", False))

                if success:
                    published += 1
                    self.state.increment_comments_today()
                    mark_outbox(item["id"], "published")
                    # ── C1: los paths de fallo encolan al outbox SIN marcar
                    # ningún dedup. Sin estos marks, el próximo scan de Phase B
                    # vuelve a ver el comentario/post como sin responder y
                    # publica un DUPLICADO visible. Marcar aquí es el único
                    # punto donde el outbox retry tiene éxito.
                    try:
                        _real_cid = ""
                        if isinstance(result, dict):
                            _real_cid = result.get("comment_id") or result.get("id") or ""
                        _dedup = DedupStore()
                        _dedup.set_commented_post(str(post_id))
                        if _real_cid:
                            _dedup.add_agent_comment(str(post_id), str(_real_cid))
                        if parent_comment_id:
                            mark_replied_to_comment(f"{post_id}:{parent_comment_id}")
                        logger.info(
                            "Comment outbox: dedup durable marcado post=%s parent=%s cid=%s",
                            post_id, parent_comment_id or "-", _real_cid or "-",
                        )
                    except Exception as _e:
                        logger.warning("Comment outbox: dedup mark fallo (no bloqueante): %s", _e)
                    logger.info("Comment outbox: comentario publicado en post %s (ID outbox: %s)", post_id, item.get("id"))
                else:
                    # Clasificar el fallo igual que el outbox de posts (_retry_outbox):
                    #   - 429 rate-limit → pending con Retry-After (backoff).
                    #   - 4xx client error (p.ej. 404 "Parent comment not found") → failed,
                    #     no se reintenta (un padre borrado nunca va a volver).
                    #   - 5xx / status=0 (error de red capturado por create_comment) → pending
                    #     con backoff (transitorio, seguro de reintentar).
                    http_status = result.get("status") if isinstance(result, dict) else 0
                    if http_status == 429:
                        retry_after = result.get("retry_after_seconds")
                        retry_attempt = item.get("retry_attempt", 0) + 1
                        capped = min(retry_after or 60, max_backoff)
                        update_outbox_backoff(
                            item["id"], str(result)[:200], retry_attempt,
                            min_backoff, max_backoff, explicit_delay_seconds=capped,
                        )
                        logger.warning(
                            "Comment outbox: 429 rate-limit (Retry-After=%ss, capped=%ss), retry_attempt=%s",
                            retry_after, capped, retry_attempt,
                        )
                    elif http_status == 404 and is_parent_not_found_404(result):
                        # Padre borrado: determinista. Marcar el comentario como
                        # unrepliable (nunca vuelve a la cola de Phase B) y el
                        # item como failed (no reintentar — 44 retries no sirven).
                        parent_comment_id = payload.get("parent_comment_id")
                        if parent_comment_id:
                            mark_unrepliable_comment(f"{post_id}:{parent_comment_id}")
                        mark_outbox(item["id"], "failed", str(result)[:200])
                        logger.warning(
                            "Comment outbox: 404 padre inexistente — item %s failed, "
                            "comment %s marcado unrepliable",
                            item.get("id"), parent_comment_id,
                        )
                    elif 400 <= http_status < 500:
                        mark_outbox(item["id"], "failed", str(result)[:200])
                        logger.warning(
                            "Comment outbox: comentario marcado 'failed' (HTTP %s) en post %s", http_status, post_id
                        )
                    else:
                        retry_attempt = item.get("retry_attempt", 0) + 1
                        update_outbox_backoff(
                            item["id"], str(result)[:200], retry_attempt, min_backoff, max_backoff
                        )
                        logger.warning(
                            "Comment outbox: fallo publicando comentario en post %s, retry_attempt=%s: %s",
                            post_id, retry_attempt, result,
                        )
            except Exception as e:
                retry_attempt = item.get("retry_attempt", 0) + 1
                update_outbox_backoff(item["id"], str(e)[:200], retry_attempt)
                logger.warning("Comment outbox: error publicando comentario en post %s, retry_attempt=%s: %s", post_id, retry_attempt, e)

        return published

    def _write_health_snapshot(self, results: Dict[str, Any], duration: float) -> None:
        try:
            self.health_file.parent.mkdir(parents=True, exist_ok=True)
            phase_a = results.get("phase_a", {}) or {}
            phase_b = results.get("phase_b", {}) or {}
            phase_c = results.get("phase_c", {}) or {}

            snapshot = {
                "cycle": self.cycle_count,
                "posts_today": self.posts_today,
                "duration_seconds": duration,
                "last_error": results.get("error"),
                "phase_a": {
                    "posts_published": phase_a.get("posts_published", 0),
                    "drafts_generated": phase_a.get("drafts_generated", 0),
                },
                "phase_b": {
                    "replies_published": phase_b.get("replies_published", 0),
                },
                "phase_c": {
                    "insights_generated": phase_c.get("insights_generated", 0),
                    "analytics_run": phase_c.get("analytics_run", False),
                },
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "version": self.version,
            }
            _write_json_atomic(self.health_file, snapshot, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("⚠ No se pudo escribir health.json: %s", e)

    async def _run_phase_a(self) -> Dict[str, Any]:
        self._phase_a_deps.posts_today = self.posts_today
        if self._phase_a is None:
            self._phase_a = PhaseAContentGeneration(deps=self._phase_a_deps)
        phase_a = self._phase_a
        raw_result = await phase_a.execute()

        if isinstance(raw_result, list):
            posts_count = len([p for p in raw_result if isinstance(p, dict) and p.get("body")])
            return {
                "posts_published": posts_count,
                "drafts_generated": len(raw_result),
                "posts": raw_result,
                "success": posts_count > 0,
            }
        if isinstance(raw_result, dict):
            return raw_result
        return {"posts_published": 0, "drafts_generated": 0, "posts": [], "success": False}

    async def _run_phase_b(self) -> Dict[str, Any]:
        if not behavior_cfg.get("phase_b_enabled"):
            return {"skipped": "phase_b_disabled"}
        if behavior_cfg.get("whisper_mode"):
            return {"skipped": "whisper_mode_active"}
        if self._phase_b is None:
            self._phase_b = PhaseB(deps=self._phase_b_deps)
        return await self._phase_b.execute()

    async def _run_phase_b_only(self) -> Dict[str, Any]:
        """Run Phase B independently without Phase A/C."""
        self.state._check_daily_reset()
        logger.info("=" * 58)
        logger.info("FASE B (solo) #%s", self.cycle_count)
        logger.info("=" * 58)
        if not behavior_cfg.get("phase_b_enabled"):
            logger.info("Phase B (solo): deshabilitada, saltando.")
            return {"skipped": "phase_b_disabled"}

        comment_outbox_published = self._retry_comment_outbox()
        if comment_outbox_published > 0:
            logger.info("Comment outbox: %s comentario(s) publicado(s)", comment_outbox_published)

        b_results = await self._run_phase_b()
        self.last_phase_b_run_at = time.time()

        if isinstance(b_results, dict) and b_results.get("replies_published"):
            self._safe_record_action("phase_b_reply", success=True)
        return b_results

    async def _run_phase_c(self) -> Dict[str, Any]:
        if not behavior_cfg.get("phase_c_enabled"):
            return {"skipped": "phase_c_disabled"}
        if self.cycle_count % int(os.getenv("PHASE_C_INTERVAL", "3")) != 0:
            return {"skipped": "phase_c_cycle_gate", "cycle": self.cycle_count}
        self._phase_c_deps.cycle_count = self.cycle_count
        if self._phase_c is None:
            self._phase_c = PhaseCAnalytics(deps=self._phase_c_deps)
        try:
            return await self._phase_c.execute()
        except Exception as e:
            logger.warning("Phase C: error no capturado por el boundary: %s", e, exc_info=True)
            return {"analytics_run": False, "insights_generated": 0, "error": str(e)}

    def _rotate_cycle_logs(self, keep: int = 150) -> None:
        logs_dir = Path("logs")
        if not logs_dir.is_dir():
            return
        try:
            pattern = re.compile(r"^cycle_(\d+)\.json$")
            files: List[Path] = []
            for f in logs_dir.iterdir():
                m = pattern.match(f.name)
                if m:
                    files.append((int(m.group(1)), f))
            if len(files) <= keep:
                return
            files.sort(key=lambda x: x[0])
            for _, f in files[: -keep]:
                f.unlink()
        except Exception as e:
            logger.warning("No se pudo rotar logs de ciclo: %s", e)

    def _log_cycle_summary(self, results: Dict[str, Any], duration: float):
        summary_lines: List[str] = [
            f"🔄 Ciclo #{self.cycle_count} completado",
            f" Duración: {duration:.1f}s",
        ]

        if "phase_a" in results:
            a = results["phase_a"]
            if isinstance(a, dict):
                if a.get("posts_published"):
                    summary_lines.append(f"✅ Fase A: {a['posts_published']} post(s) publicado(s)")
                elif a.get("drafts_generated"):
                    summary_lines.append(f" Fase A: {a['drafts_generated']} borrador(es) generado(s)")

        if "phase_b" in results:
            b = results["phase_b"]
            if isinstance(b, dict) and b.get("replies_published"):
                extras = []
                if b.get("upvotes"):
                    extras.append(f"{b['upvotes']} upvote(s)")
                if b.get("follows"):
                    extras.append(f"{b['follows']} follow(s)")
                extras_str = ", " + ", ".join(extras) if extras else ""
                summary_lines.append(f"💬 Fase B: {b['replies_published']} respuesta(s){extras_str}")

        if "phase_c" in results:
            c = results["phase_c"]
            if isinstance(c, dict) and c.get("insights_generated"):
                summary_lines.append(f"🧠 Fase C: {c['insights_generated']} insight(s)")

        # ── Telemetria del tier classify: llamadas de clasificacion del ciclo ──
        try:
            _classify = self.model_cascade.get_tier_stats("classify")
            if _classify.get("calls"):
                summary_lines.append(
                    f" classify: {_classify['calls']} llamadas "
                    f"(provider={_classify.get('provider', '?')}, costo=${_classify.get('cost', 0.0):.4f})"
                )
        except Exception:
            pass

        summary = "\n".join(summary_lines)
        logger.info(summary)

        if self.telegram_client and self.telegram_client.enabled:
            phase_a = results.get("phase_a", {})
            phase_b = results.get("phase_b", {})
            has_activity = (
                (isinstance(phase_a, dict) and phase_a.get("posts_published"))
                or (isinstance(phase_b, dict) and phase_b.get("replies_published"))
            )
            if has_activity:
                try:
                    sent = self.telegram_client.send_message(
                        f"<b>COMET-RIOBAMBA</b>\n{summary}",
                        parse_mode="HTML",
                        disable_notification=True,
                    )
                    if not sent:
                        logger.warning("⚠ Telegram: mensaje no enviado (revisar chat_id/token)")
                except Exception as e:
                    logger.warning("⚠ Telegram send error: %s", e)

    async def _run_cycle(self) -> Dict[str, Any]:
        cycle_start = time.time()
        self.cycle_count += 1
        send_event("cycle_start", {"cycle": self.cycle_count})

        # Check if paused via Telegram /pause command
        try:
            from services.telegram_control import is_agent_paused
            if is_agent_paused():
                logger.info("Agent is PAUSED (via Telegram /pause). Skipping cycle #%s.", self.cycle_count)
                return {"cycle_id": self.cycle_count, "skipped": True, "reason": "paused"}
        except ImportError:
            pass

        self.state._check_daily_reset()
        self._check_home_dashboard()
        self._maybe_send_daily_balance()
        self._maybe_send_nightly_inbound_report()
        self._maybe_run_nightly_reflection()

        max_posts = behavior_cfg.get("max_posts_per_day", POLICY.max_posts_per_day)
        phase_a_blocked = self.posts_today >= max_posts
        if phase_a_blocked:
            logger.info(
                "Phase A: límite diario alcanzado (%s/%s). Saltando Phase A.",
                self.posts_today, max_posts,
            )

        logger.info("=" * 58)
        logger.info("CICLO #%s INICIADO", self.cycle_count)
        logger.info("=" * 58)

        results: Dict[str, Any] = {
            "cycle_id": self.cycle_count,
            "start_time": datetime.now().isoformat(),
            "phase_a": {},
            "phase_b": {},
            "phase_c": {},
        }

        try:
            a_results: Dict[str, Any] = {}

            # ── Launch Phase B in background while Phase A generates ──
            phase_b_task = None
            if behavior_cfg.get("phase_b_enabled") and not behavior_cfg.get("whisper_mode"):
                send_event("phase_b_scan_start", {"cycle": self.cycle_count})
                logger.info("Phase B: launched in background while Phase A generates")
                phase_b_task = asyncio.create_task(self._run_phase_b())

            if not phase_a_blocked:
                logger.info("Outbox: reintentando posts pendientes antes de Fase A...")
                outbox_published = self._retry_outbox()
                if outbox_published > 0:
                    logger.info("Outbox: %s post(s) publicado(s) de pendientes", outbox_published)

                comment_outbox_published = self._retry_comment_outbox()
                if comment_outbox_published > 0:
                    logger.info("Comment outbox: %s comentario(s) publicado(s) de pendientes", comment_outbox_published)

                # ── Self-Monitoring diagnosis before Phase A ──────────────
                try:
                    monitor = SelfMonitor(Path.cwd())
                    diagnosis = monitor.run_diagnosis()
                    self._phase_a_deps.self_diagnosis = diagnosis
                    try:
                        diag_path = Path("data/self_diagnosis.jsonl")
                        diag_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(diag_path, "a", encoding="utf-8") as f:
                            f.write(json.dumps(diagnosis, ensure_ascii=False) + "\n")
                        logger.info(">>> [WIRE CHECK] Escribiendo self_diagnosis.jsonl")
                    except Exception as exc:
                        logger.debug("SelfMonitor: no se pudo persistir diagnosis: %s", exc)
                    if diagnosis["intervention_required"]:
                        logger.info(
                            "SelfMonitor: intervention_required=True interventions=%s",
                            diagnosis["interventions"],
                        )
                        for key, details in diagnosis.items():
                            if isinstance(details, dict) and details.get("stuck") or details.get("rigid") or details.get("recycling"):
                                logger.info("SelfMonitor: %s — %s", key, details)
                except Exception as exc:
                    logger.warning("SelfMonitor: diagnosis falló, continuando sin intervención: %s", exc)
                    self._phase_a_deps.self_diagnosis = None

                logger.info("\nFASE A: Generación de Contenido Original")
                a_results = await self._run_phase_a()

            results["phase_a"] = a_results

            diagnosis = getattr(self._phase_a_deps, "self_diagnosis", None)
            if diagnosis and diagnosis.get("intervention_required"):
                logger.info(
                    "Cycle #%s: self-diagnosis triggered interventions=%s",
                    self.cycle_count, diagnosis.get("interventions"),
                )

            posts_published = 0
            if isinstance(a_results, dict):
                if a_results.get("posts_published"):
                    posts_published = a_results["posts_published"]
                    for _ in range(posts_published):
                        self.state.increment_posts_today()
                        self._safe_record_action("create_post", success=True)
                    send_event("phase_a_publish_success", {"count": posts_published, "cycle": self.cycle_count})
                elif a_results.get("skipped"):
                    send_event("phase_a_publish_skip", {"reason": a_results["skipped"], "cycle": self.cycle_count})
                else:
                    send_event("phase_a_publish_skip", {"reason": "no_content", "cycle": self.cycle_count})

            if behavior_cfg.get("phase_b_enabled") and not behavior_cfg.get("whisper_mode"):
                if phase_b_task is not None:
                    b_results = await phase_b_task
                    results["phase_b"] = b_results
                else:
                    # Fallback: Phase B wasn't launched (whisper mode)
                    logger.info("\nFASE B: Respuestas a Comunidad")
                    b_results = await self._run_phase_b()
                    results["phase_b"] = b_results

                if isinstance(b_results, dict) and b_results.get("replies_published"):
                    self._safe_record_action(
                        "phase_b_reply",
                        success=True,
                    )
                    if self.telegram_client:
                        try:
                            self.telegram_client.send_alert(
                                "💬 Fase B: Respuestas generadas",
                                f"{b_results['replies_published']} respuestas publicadas a comentarios recientes.",
                                level="INFO",
                            )
                        except Exception as e:
                            logger.warning("⚠ Telegram alert error: %s", e)

            if behavior_cfg.get("phase_c_enabled"):
                logger.info("\nFASE C: Analytics & Optimización")
                c_results = await self._run_phase_c()
                results["phase_c"] = c_results

                if (
                    isinstance(c_results, dict)
                    and c_results.get("analytics_run")
                    and c_results.get("insights_generated")
                ):
                    logger.info("Fase C: %s insights generados", c_results["insights_generated"])

            logger.info(
                "Afirmación de seguridad: Estoy en armonía con mi propósito. Mis palabras construyen puentes."
            )
            self.state.save()

        except Exception as e:
            logger.error("Error en ciclo #%s: %s", self.cycle_count, e, exc_info=True)
            results["error"] = str(e)
            self.state.consecutive_failures += 1

            if self.state.consecutive_failures >= POLICY.max_consecutive_post_failures and self.telegram_client:
                try:
                    self.telegram_client.send_alert(
                        "🔴 Error crítico en agente",
                        f"{self.state.consecutive_failures} fallos consecutivos. Revisar logs.",
                        level="ERROR",
                    )
                except Exception:
                    pass
        else:
            self.state.consecutive_failures = 0

        duration = time.time() - cycle_start
        results["duration_seconds"] = duration
        results["end_time"] = datetime.now().isoformat()
        self._write_health_snapshot(results, duration)
        self._log_cycle_summary(results, duration)
        send_event("cycle_end", {"cycle": self.cycle_count, "duration": duration, "error": results.get("error")})

        self._rotate_cycle_logs()

        logger.info("=" * 58)
        logger.info("CICLO #%s FINALIZADO en %.3fs", self.cycle_count, duration)
        logger.info("=" * 58)

        return results

    async def run(self):
        logger.info("=" * 58)
        logger.info("COMET-RIOBAMBA v%s", self.version)
        logger.info("=" * 58)

        config_summary = {
            "version": self.version,
            "config_version": self.config_version,
            "cycle_count": self.cycle_count,
            "whisper_mode": behavior_cfg.get("whisper_mode"),
            "start_time": self.start_time.isoformat(),
            "phase_b_enabled": behavior_cfg.get("phase_b_enabled"),
            "phase_c_enabled": behavior_cfg.get("phase_c_enabled"),
            "telegram_enabled": bool(self.telegram_client and self.telegram_client.enabled),
        }
        logger.info(json.dumps(config_summary, indent=2, default=str))
        logger.info(
            "Behavior config (effective): max_posts_per_day=%s, cycle_interval_seconds=%s, "
            "max_comments_per_day=%s, max_comment_replies_per_cycle=%s, max_comments_per_post=%s",
            behavior_cfg.get("max_posts_per_day", POLICY.max_posts_per_day),
            behavior_cfg.get("cycle_interval_seconds", POLICY.cycle_interval_seconds),
            behavior_cfg.get("max_comments_per_day", POLICY.max_comments_per_day),
            behavior_cfg.get("max_comment_replies_per_cycle", POLICY.max_comment_replies_per_cycle),
            behavior_cfg.get("max_comments_per_post", POLICY.max_comments_per_post),
        )

        if behavior_cfg.get("whisper_mode"):
            logger.info("\n⚠ MODO WHISPER ACTIVADO - No se publicarán posts reales")

        # ── Start Telegram listener as background task ──
        if self.telegram_client and self.telegram_client.enabled:
            asyncio.create_task(self.telegram_client.listen_for_commands(self))
            logger.info("✅ Telegram listener background task started")

        # ── Update Moltbook profile on startup ──
        try:
            identity_path = Path("config") / "agent_identity.json"
            if identity_path.exists():
                identity = json.loads(identity_path.read_text(encoding="utf-8-sig"))
                bio = identity.get("bio", "")
                if bio:
                    self.moltbook_api_client.update_agent_profile(bio=bio)
        except Exception as e:
            logger.warning("⚠ Moltbook profile update failed on startup: %s", e)

        base_interval = behavior_cfg.get("cycle_interval_seconds", POLICY.cycle_interval_seconds)

        while not self.shutdown_requested:
            # Detect an out-of-band graceful stop request (data/stop.flag).
            if self._check_stop_flag() or self._check_maintenance_flag():
                break
            cycle_interval = get_current_interval(base_interval)
            skip, reason = should_skip_cycle()
            if skip:
                logger.warning("Circuit breaker global abierto. Ciclo omitido. Motivo: %s", reason)
                logger.info("Esperando %ss antes de reintentar...", cycle_interval)
                for _ in range(int(cycle_interval)):
                    if self.shutdown_requested or self._check_stop_flag() or self._check_maintenance_flag():
                        break
                    await asyncio.sleep(1)
                continue

            results = await self._run_cycle()
            error = results.get("error")
            phase_a = results.get("phase_a") or {}
            phase_b = results.get("phase_b") or {}
            self.last_phase_b_run_at = time.time()
            had_activity = bool(
                (isinstance(phase_a, dict) and phase_a.get("posts_published"))
                or (isinstance(phase_b, dict) and phase_b.get("replies_published"))
            )

            cycle_interval = register_cycle_result(
                error=error,
                had_activity=had_activity,
                base_interval_seconds=base_interval,
            )

            # --- ADAPTIVE SCHEDULER ---
            # Si el agente publicó o respondió (debate activo), acortamos el sueño a 2 horas (7200s)
            # para poder responder rápidamente si el usuario replica.
            if had_activity and cycle_interval > 7200:
                logger.info("🧠 Adaptive Scheduler: Actividad detectada. Reduciendo espera a 2h para mantener debate vivo.")
                cycle_interval = 7200

            review_interval = behavior_cfg.get("value_review_interval_days", POLICY.value_review_interval_days)
            last_review = self.state.last_value_review
            if review_interval > 0:
                if last_review is None:
                    self.state.last_value_review = datetime.now().isoformat()
                    self.state.save()
                else:
                    try:
                        last_review_dt = datetime.fromisoformat(last_review)
                        days_since = (datetime.now() - last_review_dt).days
                        if days_since >= review_interval:
                            logger.info("Iniciando revisión de valor (intervalo=%s días)...", review_interval)
                            review_file = await run_value_review(
                                self.model_cascade,
                                days=review_interval,
                                max_events=50,
                            )
                            self.state.mark_value_review(str(review_file) if review_file else "")
                            if review_file:
                                logger.info("Revisión de valor completada: %s", review_file)
                    except (ValueError, TypeError):
                        self.state.last_value_review = datetime.now().isoformat()
                        self.state.save()

            # Independent Phase B clock: run Phase B-only pass if interval elapsed
            pb_interval = behavior_cfg.get("phase_b_interval_seconds", POLICY.phase_b_interval_seconds)
            elapsed_since_phase_b = time.time() - self.last_phase_b_run_at
            if behavior_cfg.get("phase_b_enabled") and elapsed_since_phase_b >= pb_interval:
                logger.info("Phase B (solo): %ss desde última ejecución >= intervalo %ss",
                            int(elapsed_since_phase_b), pb_interval)
                await self._run_phase_b_only()

            logger.info("Esperando %ss hasta el próximo ciclo", cycle_interval)
            for _ in range(int(cycle_interval)):
                if self.shutdown_requested or self._check_stop_flag() or self._check_maintenance_flag():
                    break
                self._maybe_supervise_watchdog()
                await asyncio.sleep(1)
                # Intra-sleep Phase B check: run Phase B-only if interval elapsed
                if behavior_cfg.get("phase_b_enabled"):
                    elapsed = time.time() - self.last_phase_b_run_at
                    if elapsed >= pb_interval:
                        logger.info("Phase B (solo intra-sleep): %ss desde última ejecución >= intervalo %ss",
                                    int(elapsed), pb_interval)
                        await self._run_phase_b_only()

        logger.info("🛑 Agente detenido. Guardando estado final...")
        self.state.save()

        if self.telegram_client and self.telegram_client.enabled:
            try:
                self.telegram_client.send_message(
                    (
                        "⚪ <b>COMET-RIOBAMBA</b>\n"
                        "Agente detenido limpiamente.\n"
                        f"Ciclos totales: {self.cycle_count}"
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

        logger.info("✅ Shutdown completado")

    def request_shutdown(self):
        logger.info("🔄 Shutdown solicitado...")
        self.shutdown_requested = True

    @staticmethod
    def _pid_alive(pid: Optional[int]) -> bool:
        """¿Existe el proceso? Versión robusta Windows (18/08/2026).

        os.kill(pid, 0) en Windows puede lanzar OSError WinError 87
        ("parámetro no correcto") incluso con PID vivo; tratar eso como
        'muerto' hacía que el agente relanzara el watchdog cada 300s.
        Mismo fallback que monitoring/watchdog.py: si kill no decide,
        tasklist lo confirma; si tasklist tampoco, asumir vivo (fail-safe)."""
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            pass
        try:
            import subprocess
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, timeout=10,
            )
            text = out.stdout.decode("utf-8", errors="replace")
            return f"{pid}" in text
        except Exception:
            return True  # ambigüo → no relanzar un proceso que podría vivir

    def _maybe_supervise_watchdog(self) -> None:
        """Supervisa el watchdog cada WATCHDOG_SUPERVISION_S (default 300s):
        si su lock está ausente o con pid muerto, lo relanza. El agente es el
        supervisor natural: corre 24/7 y su entorno de ejecución ya está
        probado (a diferencia del Start-Process desde guard/scheduler)."""
        interval = int(os.getenv("WATCHDOG_SUPERVISION_S", "300"))
        if time.time() - self._last_watchdog_check < interval:
            return
        self._last_watchdog_check = time.time()
        try:
            from config import BASE_DIR
            lock_file = BASE_DIR / ".watchdog.lock"
            lock_alive = False
            if lock_file.exists():
                try:
                    pid = int(lock_file.read_text(encoding="utf-8").strip())
                    lock_alive = self._pid_alive(pid)
                except ValueError:
                    lock_alive = False
            if lock_alive:
                return
            if (BASE_DIR / "data" / "stop.flag").exists():
                return  # agente deteniéndose/parado → no relanzar el guard
            python = sys.executable
            proc = subprocess.Popen(
                [python, "-u", "monitoring/watchdog.py"],
                cwd=str(BASE_DIR),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
            )
            logger.info("🛡️ Watchdog no estaba corriendo → relanzado (PID %s)", proc.pid)
        except Exception as e:
            logger.warning("Watchdog supervision falló: %s", e)

    def _check_stop_flag(self) -> bool:
        """If data/stop.flag exists, request shutdown and remove the flag.

        Returns True if a stop was requested. The flag is deleted so it does not
        linger and abort the next startup. Checked in the main loop's 1s sleep
        ticks, so it adds no new latency.
        """
        try:
            if self.stop_flag_file.exists():
                logger.info("🛑 stop.flag detectado en %s — solicitando shutdown graceful.", self.stop_flag_file)
                try:
                    self.stop_flag_file.unlink()
                except Exception as e:
                    logger.warning("No se pudo eliminar stop.flag (%s): %s", self.stop_flag_file, e)
                self.shutdown_requested = True
                return True
        except Exception as e:
            logger.warning("Error revisando stop.flag: %s", e)
        return False

    def _check_maintenance_flag(self) -> bool:
        """If data/maintenance.flag exists, request shutdown graceful WITHOUT
        removing the flag (a diferencia de stop.flag). El flag persiste para que
        el watchdog lo siga respetando y no relance el agente. Solo se quita a
        mano para reanudar la operación."""
        try:
            if self.maintenance_flag_file.exists():
                logger.info("🧰 maintenance.flag detectado en %s — solicitando shutdown graceful (hold de mantenimiento).", self.maintenance_flag_file)
                self.shutdown_requested = True
                return True
        except Exception as e:
            logger.warning("Error revisando maintenance.flag: %s", e)
        return False

    def _maintenance_hold_active(self) -> bool:
        """True si el hold de mantenimiento está activo (el agente no debe arrancar)."""
        try:
            return self.maintenance_flag_file.exists()
        except Exception:
            return False


async def main(credentials: Optional[Credentials] = None):
    if credentials is None:
        credentials = Credentials.from_env()
    try:
        validate_config(credentials)
    except EnvironmentError as e:
        logger.error("Configuración inválida: %s", e)
        sys.exit(1)

    import signal

    agent = COMETRiobambaAgent(credentials=credentials)

    # ── Hold de mantenimiento: si data/maintenance.flag existe, NO arrancar.
    # Incluso un relanzamiento del watchdog respeta esto (lo trata como detenido),
    # así que el agente no se levanta mientras el hold esté activo.
    if agent._maintenance_hold_active():
        logger.info("🧰 maintenance.flag presente — agente NO arranca (hold de mantenimiento). Quitar data/maintenance.flag para reanudar.")
        sys.exit(0)

    def handle_signal(signum, frame):
        logger.info("Señal %s recibida. Iniciando shutdown...", signum)
        agent.request_shutdown()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        await agent.run()
    except KeyboardInterrupt:
        logger.info("Interrupción manual detectada")
    finally:
        agent.request_shutdown()
        # ── Cleanup resources ────────────────────────────────────
        try:
            if agent._phase_b and hasattr(agent._phase_b, "_memory"):
                agent._phase_b._memory.close()
            if agent.moltbook_api_client and hasattr(agent.moltbook_api_client, "session"):
                agent.moltbook_api_client.session.close()
        except Exception:
            logger.warning("Error durante limpieza de recursos", exc_info=True)
        await asyncio.sleep(2)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())






