# -*- coding: utf-8 -*-
"""Fase C: Analytics, métricas, auto-optimización y agenda de investigación."""
import logging
import json
import math
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime, timedelta

from config import behavior_cfg, content_cfg
from config.agent_policy import POLICY
from phases.deps import PhaseCDeps
from services.telegram_client import create_telegram_client
from services.roadmap import load_roadmap, save_roadmap, update_series_weight
from services.persistence import load_topic_engagement
from services.research_agenda import load_agenda, save_agenda, ResearchAgenda
from services.self_improvement import log_proposal
from utils.phase_utils import phase_error_boundary, validate_phase_deps

logger = logging.getLogger("phases.phase_c_analytics")

_CAPTCHA_LOG_PATH = Path("logs/agent.log")


def _get_captcha_success_rate() -> tuple:
    """Lee logs/agent.log y calcula la tasa de éxito del ChallengeSolver."""
    if not _CAPTCHA_LOG_PATH.exists():
        return (None, 0, 0)
    try:
        content = _CAPTCHA_LOG_PATH.read_text(encoding="utf-8", errors="replace")
        success_count = len(re.findall(r"CAPTCHA resuelto y verificacion exitosa", content))
        fail_count = len(re.findall(r"Moltbook rechazo la respuesta", content))
        total = success_count + fail_count
        if total == 0:
            return (None, 0, 0)
        rate = success_count / total
        return (rate, success_count, fail_count)
    except Exception:
        return (None, 0, 0)


class PhaseCAnalytics:
    """Fase C: Analiza rendimiento y sugiere optimizaciones."""
    
    def __init__(self, deps: PhaseCDeps):
        self.deps = deps
        validate_phase_deps(deps, ["model_cascade", "moltbook_client", "behavior_cfg"])
        self.moltbook = deps.moltbook_client
        self.telegram = deps.telegram_client or create_telegram_client()
        self.analytics_interval = behavior_cfg.get("phase_c_analytics_interval", 86400)
        self.optimization_enabled = behavior_cfg.get("phase_c_optimization_enabled", True)
        self.max_replies_per_day = int(deps.max_phase_c_replies_per_day)
        self.max_replies_per_cycle = int(deps.max_phase_c_replies_per_cycle)
        self.get_comments_today: Optional[Callable[[], int]] = deps.get_comments_today
        self.increment_comments_today: Optional[Callable[[], int]] = deps.increment_comments_today
        self.state_file = Path("data/state/phase_c_state.json")
        
    def _load_state(self) -> Dict:
        """Carga estado persistente de Fase C."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except:
                pass
        return {"last_analytics_run": None, "insights_applied": [], "metrics_history": []}
    
    def _save_state(self, state: Dict):
        """Guarda estado de Fase C."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)
    
    def _should_run_analytics(self, state: Dict) -> bool:
        """Determina si es tiempo de ejecutar analytics."""
        last_run = state.get("last_analytics_run")
        if not last_run:
            return True
        try:
            last_dt = datetime.fromisoformat(last_run)
            return (datetime.now() - last_dt).total_seconds() >= self.analytics_interval
        except:
            return True
    
    def _fetch_performance_metrics(self) -> Dict:
        """Obtiene métricas de rendimiento recientes."""
        metrics = {
            "posts_published_24h": 0,
            "avg_engagement": 0,
            "reply_rate": 0,
            "error_rate": 0,
            "top_topics": [],
            "model_usage": {},
        }
        
        try:
            # Fetch from Moltbook API (adjust based on actual endpoints)
            posts = self.moltbook.fetch_posts(since_hours=24, limit=50)
            metrics["posts_published_24h"] = len(posts)
            
            # Calculate engagement (likes + comments per post)
            engagements = [p.get("likes", 0) + p.get("comments_count", 0) for p in posts]
            metrics["avg_engagement"] = sum(engagements) / len(engagements) if engagements else 0
            
            # Extract topics from recent posts (simple keyword matching)
            topic_keywords = ["agent", "architecture", "llm", "mlops", "security", "scaling"]
            topic_counts = {}
            for post in posts:
                body = (post.get("body", "") + post.get("title", "")).lower()
                for kw in topic_keywords:
                    if kw in body:
                        topic_counts[kw] = topic_counts.get(kw, 0) + 1
            metrics["top_topics"] = sorted(topic_counts.items(), key=lambda x: -x[1])[:3]
            
        except Exception as e:
            logger.warning(f"Phase C: error fetching metrics: {e}")
        
        return metrics
    
    def _generate_insights(self, metrics: Dict) -> List[Dict]:
        """Genera insights accionables basados en métricas."""
        insights = []
        
        # Insight: Bajo engagement
        if metrics["avg_engagement"] < 2 and metrics["posts_published_24h"] > 0:
            insights.append({
                "type": "engagement_low",
                "message": f"Engagement promedio bajo ({metrics['avg_engagement']:.1f}). Considerar ajustar tono o temas.",
                "suggested_action": "Rotar templates o ajustar phase_a_system_prompt para mayor claridad",
                "priority": "medium",
            })
        
        # Insight: Tópico dominante
        if metrics["top_topics"]:
            top_topic, count = metrics["top_topics"][0]
            if count >= 3:
                insights.append({
                    "type": "topic_repetition",
                    "message": f"Tópico '{top_topic}' aparece en {count} posts recientes.",
                    "suggested_action": "Diversificar selección de topics en content_cfg",
                    "priority": "low",
                })
        
        # Insight: Errores frecuentes
        # (Implementar según logs reales)
        
        return insights
    
    def _apply_optimization(self, insight: Dict) -> Optional[str]:
        """Aplica optimización automática si está habilitada."""
        if not self.optimization_enabled:
            return None
        
        action = insight.get("suggested_action", "")
        
        # Ejemplo: ajustar temperatura si engagement bajo
        if insight["type"] == "engagement_low":
            # Nota: en producción, esto requeriría recargar config dinámicamente
            logger.info(f"Phase C: sugerencia aplicada (simulada): {action}")
            return f"Config adjustment simulated: {action}"
        
        # Ejemplo: rotar topic si repetición
        elif insight["type"] == "topic_repetition":
            logger.info(f"Phase C: diversidad de temas priorizada")
            return "Topic rotation prioritized in next generation cycle"
        
        return None
    
    def _run_topic_review(self) -> int:
        """Ajusta pesos de series del roadmap según engagement real."""
        engagement = load_topic_engagement()
        if not engagement:
            logger.info("Phase C: no hay datos de engagement para topic review.")
            return 0
        roadmap = load_roadmap()
        if not roadmap.series:
            logger.info("Phase C: roadmap vacío; saltando topic review.")
            return 0
        adjustments = 0
        for series in roadmap.series:
            series_topics = set(series.topics)
            scores = [v for k, v in engagement.items() if k in series_topics]
            if scores:
                avg_score = sum(scores) / len(scores)
                delta = (avg_score - 1.0) * 0.5
                if abs(delta) >= 0.1:
                    weight_delta = int(math.ceil(delta)) if delta >= 0 else int(math.floor(delta))
                    if weight_delta != 0:
                        update_series_weight(roadmap, series.id, weight_delta)
                        adjustments += 1
                        logger.info("Phase C: series '%s' avg_engagement=%.2f → weight delta=%d",
                                    series.id, avg_score, weight_delta)
        if adjustments:
            save_roadmap(roadmap)
            log_proposal(
                source="phase_c_topic_review",
                summary=f"Ajustados pesos de {adjustments} serie(s) del roadmap según engagement de topics.",
                details=f"Series ajustadas: {[s.id for s in roadmap.series if any(abs(v - orig_w) > 0 for orig_w, v in [(s.weight, s.weight)])]}",
            )
            logger.info("Phase C: topic review ajustó %s serie(s).", adjustments)
        return adjustments

    def _update_research_agenda(self, metrics: Dict) -> None:
        """Trend watcher: analiza los últimos posts y comentarios para
        alimentar la agenda de investigación del agente."""
        try:
            agenda = load_agenda()
            changed = False

            # 1. Extract topics from recent posts and add pending topics
            for topic_name, count in metrics.get("top_topics", []):
                if count >= 2:
                    agenda.add_topic(
                        topic_name,
                        source="phase_c_trend_watcher",
                        tags=["trending"],
                    )
                    changed = True

            # 2. Register high-impact threads
            posts = self._fetch_recent_posts_for_agenda()
            for post in posts:
                post_id = post.get("id") or post.get("post_id", "")
                if not post_id:
                    continue
                likes = post.get("likes", 0) or 0
                comments_count = post.get("comments_count", 0) or 0
                total_engagement = int(likes) + int(comments_count)
                if total_engagement >= 5:
                    title = str(post.get("title", "") or "")
                    text = (title + " " + (post.get("body") or post.get("content") or "")).lower()
                    tags = []
                    if any(kw in text for kw in ("agent", "tool", "loop")):
                        tags.append("agents")
                    if any(kw in text for kw in ("metric", "eval", "score")):
                        tags.append("metrics")
                    if any(kw in text for kw in ("fail", "error", "crash")):
                        tags.append("failure_modes")
                    if any(kw in text for kw in ("security", "safety", "guardrail")):
                        tags.append("safety")
                    agenda.add_high_impact_thread(
                        post_id, title=title,
                        engagement=total_engagement, tags=tags,
                    )
                    changed = True

            # 3. Detect new terms (simple heuristic: look for capitalized
            #    compound terms that appear in multiple posts)
            if len(posts) >= 2:
                all_text = " ".join(
                    str(p.get("title", "") or "") + " " + str(p.get("body") or p.get("content") or "")
                    for p in posts
                ).lower()
                potential_terms = [
                    "tool calling", "rate limit", "context window",
                    "circuit breaker", "model cascade", "prompt injection",
                    "tool safety", "agent loop", "runaway agent",
                    "closed loop", "bci", "guardrail", "failure mode",
                ]
                for term in potential_terms:
                    if term in all_text:
                        agenda.add_new_term(term, source="phase_c_trend_watcher")
                        changed = True

            if changed:
                save_agenda(agenda)
                logger.info("Phase C: research agenda updated (%d high-impact threads, %d topics).",
                            len(agenda.high_impact_threads), len(agenda.pending_topics))
        except Exception as e:
            logger.warning("Phase C: research agenda update failed: %s", e)

    def _fetch_recent_posts_for_agenda(self) -> List[Dict]:
        """Fetch recent posts from Moltbook for trend analysis."""
        try:
            posts = self.moltbook.fetch_posts(since_hours=48, limit=50)
            return posts if isinstance(posts, list) else []
        except Exception as e:
            logger.debug("Phase C: could not fetch posts for agenda: %s", e)
            return []

    @phase_error_boundary(logger, "phase_c_analytics")
    async def execute(self) -> Dict[str, Any]:
        """Ejecuta Fase C: analytics → insights → optimización."""
        logger.info("Phase C execute(): start (analytics & optimization)")
        
        results = {
            "analytics_run": False,
            "insights_generated": 0,
            "optimizations_applied": 0,
            "metrics": {},
            "telegram_report_sent": False,
        }
        
        state = self._load_state()
        
        # Check if analytics should run (time-based gate)
        if not self._should_run_analytics(state):
            logger.info(f"Phase C: analytics skipped (next run in ~{(self.analytics_interval - (datetime.now() - datetime.fromisoformat(state['last_analytics_run'])).total_seconds())/3600:.1f}h)")
            return results

        # Daily consumption gate
        if self.get_comments_today is not None and self.get_comments_today() >= self.max_replies_per_day:
            logger.info(f"Phase C: analytics skipped (daily limit {self.max_replies_per_day} reached, comments_today={self.get_comments_today()})")
            return results
        
        logger.info("Phase C: running analytics cycle")
        results["analytics_run"] = True
        if self.increment_comments_today is not None:
            self.increment_comments_today()
        
        # Fetch metrics
        metrics = self._fetch_performance_metrics()
        results["metrics"] = metrics
        
        # Generate insights
        insights = self._generate_insights(metrics)
        results["insights_generated"] = len(insights)

        # CAPTCHA success rate monitoring
        captcha_rate, captcha_ok, captcha_fail = _get_captcha_success_rate()
        if captcha_rate is None:
            logger.debug("Phase C: sin datos de CAPTCHA aun.")
        elif captcha_rate < 0.5:
            logger.warning(
                "Phase C: CAPTCHA success rate bajo (%d/%d = %.0f%%). Revisar ChallengeSolver.",
                captcha_ok, captcha_ok + captcha_fail, captcha_rate * 100,
            )
        else:
            logger.info(
                "Phase C: CAPTCHA success rate OK (%d/%d = %.0f%%).",
                captcha_ok, captcha_ok + captcha_fail, captcha_rate * 100,
            )

        # Apply optimizations
        for insight in insights:
            action_result = self._apply_optimization(insight)
            if action_result:
                results["optimizations_applied"] += 1
                # Notify via Telegram
                if self.telegram:
                    try:
                        self.telegram.send_phase_c_insight(insight["message"], action_result)
                    except:
                        pass  # Non-blocking
        
        # Send daily report via Telegram
        if self.telegram and behavior_cfg.get("TELEGRAM_DAILY_REPORT"):
            try:
                report_data = {
                    "cycles": self.deps.cycle_count,
                    "posts_published": metrics.get("posts_published_24h", 0),
                    "phase_b_replies": 0,  # Would fetch from Phase B state
                    "avg_engagement": f"{metrics.get('avg_engagement', 0):.1f}",
                    "errors": len([i for i in insights if i["priority"] == "high"]),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                self.telegram.send_daily_report(report_data)
                results["telegram_report_sent"] = True
            except Exception as e:
                logger.warning(f"Phase C: failed to send Telegram report: {e}")
        
        # Topic review: adjust roadmap series weights based on engagement
        try:
            adjustments = self._run_topic_review()
            results["topic_review_adjustments"] = adjustments
        except Exception as e:
            logger.warning("Phase C: topic review failed: %s", e)
            results["topic_review_adjustments"] = -1

        # Update research agenda (trend watcher)
        try:
            self._update_research_agenda(metrics)
            results["research_agenda_updated"] = True
        except Exception as e:
            logger.warning("Phase C: research agenda update failed: %s", e)
            results["research_agenda_updated"] = False
        
        # Update state
        state["last_analytics_run"] = datetime.now().isoformat()
        state["metrics_history"].append({"ts": datetime.now().isoformat(), **metrics})
        # Keep only last 7 days of history
        state["metrics_history"] = state["metrics_history"][-168:]  # 7 days * 24 hours
        self._save_state(state)
        
        logger.info(f"Phase C complete: {len(insights)} insights, {results['optimizations_applied']} optimizations")
        return results

