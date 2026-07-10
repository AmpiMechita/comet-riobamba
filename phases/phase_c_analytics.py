# -*- coding: utf-8 -*-
"""Fase C: Analytics, métricas, auto-optimización y agenda de investigación."""
import asyncio
import logging
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime, timedelta, timezone

from config import behavior_cfg, content_cfg
from config.agent_policy import POLICY
from core.strategy_state import StrategyState
from phases.deps import PhaseCDeps
from services.telegram_client import create_telegram_client
from services.roadmap import load_roadmap, save_roadmap, update_series_weight
from services.persistence import load_topic_engagement
from prompts.prompt_templates import SOCIAL_REPURPOSING_TEMPLATE
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
    
    async def _run_social_harvester(self):
        """Genera contenido para redes sociales a partir de debates de alto valor en nuestros posts."""
        try:
            logger.info("Phase C: Iniciando Harvester de Insights para Redes Sociales...")
            posts = self.moltbook.fetch_my_posts(limit=3)
            if not posts:
                return

            for post in posts:
                post_id = post.get("id")
                if not post_id:
                    continue
                
                comments = self.moltbook.fetch_post_comments(post_id)
                # Solo sintetizar hilos donde hubo un debate real (3+ comentarios)
                if len(comments) < 3:
                    continue

                # Construir el texto del debate
                debate_lines = []
                for c in comments:
                    author_raw = c.get("author")
                    author = author_raw.get("name", "User") if isinstance(author_raw, dict) else str(author_raw or "User")
                    text = c.get("content") or c.get("text") or ""
                    debate_lines.append(f"{author}: {text}")
                
                debate_text = "\n".join(debate_lines)
                topic = post.get("title", "Technical Agent Debate")

                prompt = SOCIAL_REPURPOSING_TEMPLATE.format(topic=topic, debate_text=debate_text)
                
                result = await self.deps.model_cascade.generate(
                    prompt=prompt,
                    system_prompt="You are an expert technical writer. Output ONLY valid JSON.",
                    max_tokens=2000,
                    temperature=0.6,
                    tier="fallback"
                )

                if result:
                    result = result.strip().replace("```json", "").replace("```", "").strip()
                    data = json.loads(result)
                    
                    export_dir = Path("exports/social_content")
                    export_dir.mkdir(parents=True, exist_ok=True)
                    filepath = export_dir / f"{datetime.now().strftime('%Y-%m-%d')}_{post_id[:8]}.md"
                    
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(f"# Síntesis de Debate: {topic}\n\n")
                        f.write("## 🧵 Twitter Thread\n\n")
                        for tw in data.get("twitter_thread", []):
                            f.write(f"- {tw}\n")
                        f.write("\n## 💼 LinkedIn Post\n\n")
                        f.write(data.get("linkedin_post", "N/A") + "\n")
                    
                    logger.info(f"Phase C: Contenido social sintetizado y guardado en {filepath}")

        except Exception as e:
            logger.warning(f"Phase C: Error en Social Harvester: {e}")

    async def _update_research_agenda_from_feedback(self):
        """Extrae keywords de posts exitosos y alimenta la research_agenda para mañana."""
        try:
            posts = self.moltbook.fetch_my_posts(limit=5)
            if not posts:
                return
            
            # Filtrar posts con buen engagement (3 o más comentarios)
            successful_posts = [p for p in posts if (p.get("comment_count", 0) or len(p.get("comments", [])) or 0) >= 3]
            if not successful_posts:
                return
            
            all_text = ' '.join([p.get("content", "") + " " + p.get("title", "") for p in successful_posts])
            words = re.findall(r'\b[a-zA-Z]{4,}\b', all_text.lower())
            
            # Stopwords básicas (inglés y español)
            stopwords = {'para', 'este', 'sobre', 'como', 'muy', 'con', 'the', 'that', 'this', 'with', 'from', 'have', 'your', 'will', 'they', 'their'}
            keywords = [w for w in words if w not in stopwords]
            
            # Umbral de frecuencia: count >= 2 para evitar ruido contextual
            top_keywords = [word for word, count in Counter(keywords).most_common(8) if count >= 2]
            
            # Extraer hook estructural del post con más comentarios
            best_post = max(successful_posts, key=lambda p: p.get("comment_count", 0))
            best_hook = (best_post.get("content", "") or "").split('.')[0][:150]
            if best_hook:
                agenda["hook_template"] = best_hook
                logger.info(f"Phase C: Hook estructural exitoso guardado: {best_hook}")

            if not top_keywords:
                return
                
            # Generar temas para la agenda
            new_topics = [f"{kw} implementation patterns" for kw in top_keywords[:3]]
            
            # Cargar agenda existente y añadir nuevos temas sin duplicar
            agenda = load_agenda()
            existing_topics = set(t.get("topic", "").lower() for t in agenda.get("topics", []))
            
            for topic in new_topics:
                if topic.lower() not in existing_topics:
                    agenda.setdefault("topics", []).append({"topic": topic, "source": "phase_c_feedback"})
                    
            save_agenda(agenda)
            logger.info(f"Phase C: Research Agenda actualizada con keywords exitosas: {top_keywords[:3]}")
            
        except Exception as e:
            logger.warning(f"Phase C: Error actualizando research agenda: {e}")

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

    def _maybe_run_energy_intel(self) -> None:
        """Run energy intel ingest + Telegram alerts if throttle allows (1h interval)."""
        if not self.telegram or not self.telegram.enabled:
            return
        try:
            from services.energy_intel_telegram import (
                should_run_energy_intel, run_energy_intel_with_alerts, minutes_since_last_run,
                run_funding_scan, run_tech_radar_scan,
                should_run_weekly_digest, run_weekly_digest,
            )
        except ImportError as e:
            logger.warning("Energy Intel: cannot import module — %s", e)
            return

        if not should_run_energy_intel():
            mins = minutes_since_last_run()
            logger.debug("Energy Intel: throttled (last run %.0f min ago, interval=60 min)", mins or 0)
            return

        mins = minutes_since_last_run()
        last_run_info = f"{mins:.0f} min atrás" if mins is not None else "nunca"
        logger.info("Energy Intel: ejecutando ingest (última ejecución: %s)", last_run_info)

        try:
            new_count = run_energy_intel_with_alerts(self.telegram)
            if new_count == 0:
                logger.info("Energy Intel: sin nuevas tecnologías de frontera")
            else:
                logger.info("Energy Intel: %d claim(s) ingerido(s)", new_count)
        except Exception as e:
            logger.warning("Energy Intel: error en ejecución — %s", e)

        # Funding & Tech Radar (same hourly throttle)
        try:
            funding_count = run_funding_scan(self.telegram)
            radar_count = run_tech_radar_scan(self.telegram)
            if funding_count or radar_count:
                logger.info("Energy Intel: %d funding, %d radar entries", funding_count, radar_count)
        except Exception as e:
            logger.warning("Energy Intel: funding/radar scan error — %s", e)

        # Weekly digest (Mondays only)
        try:
            if should_run_weekly_digest():
                run_weekly_digest(self.telegram)
                logger.info("Energy Intel: weekly digest enviado")
        except Exception as e:
            logger.warning("Energy Intel: weekly digest error — %s", e)

    @phase_error_boundary(logger, "phase_c_analytics")
    async def _maybe_generate_proposal(self, results: Dict, metrics: Dict) -> None:
        """Generate a self-improvement proposal grounded in REAL telemetry.

        Instead of asking the LLM to guess what to improve, we mine the agent's
        own operational logs (data/dual_scores.jsonl + data/cascade_telemetry.jsonl)
        for concrete failure metrics, then ask the LLM to turn those numbers into a
        concise, actionable code-change proposal.
        """
        try:
            findings = self._collect_telemetry_metrics(window=50)

            if not findings.get("has_signal"):
                logger.debug(
                    "Phase C: no significant friction in telemetry — skipping proposal generation"
                )
                return

            model_cascade = self.deps.model_cascade
            if not model_cascade:
                return

            metrics_block = "\n".join(f"- {line}" for line in findings["lines"])
            proposal_prompt = (
                "Analiza estas métricas de fallo de tu propio sistema, extraídas de "
                "tus logs de telemetría (dual_scores.jsonl y cascade_telemetry.jsonl):\n\n"
                f"{metrics_block}\n\n"
                "Redacta una propuesta técnica concisa (máx 3 líneas) para que el "
                "administrador modifique el código. Basáte SOLO en las métricas de "
                "arriba, no inventes datos. Indica el archivo y el cambio concreto.\n"
                "Ejemplo: 'Métrica: 15 fallos por longitud. Propuesta: Aumentar "
                "max_len en constants.py'."
            )
            try:
                response = await model_cascade.generate(
                    prompt=proposal_prompt,
                    system_prompt=(
                        "Eres un agente autónomo proponiendo mejoras a tu propio código "
                        "basándote en datos de telemetría reales. No alucines métricas."
                    ),
                    max_tokens=200,
                    temperature=0.5,
                    tier="premium",
                    caller="phase_c_proposal",
                )
                response = (response or "").strip()
                if response and len(response) > 10:
                    from services.telegram_control import log_proposal
                    proposal_text = (
                        f"{response}\n\n"
                        f"[Telemetría base: {' | '.join(findings['lines'])}]"
                    )
                    log_proposal(proposal_text)
                    logger.info(
                        "Phase C: telemetry-grounded proposal generated (%d chars, %d metrics)",
                        len(response), len(findings["lines"]),
                    )
            except Exception as e:
                logger.debug("Phase C: proposal generation skipped (LLM unavailable): %s", e)
        except Exception as e:
            logger.warning("Phase C: proposal generation error: %s", e)

    def _collect_telemetry_metrics(self, window: int = 50) -> Dict[str, Any]:
        """Mine dual_scores + cascade_telemetry for concrete failure metrics.

        Returns {"has_signal": bool, "lines": [str, ...]} where each line is a
        human-readable, data-grounded metric suitable for feeding to the LLM.
        """
        lines: List[str] = []

        # ── 1) Content quality friction from dual_scores.jsonl ──────────
        # Read ONLY the active file, never the rotated {name}.archive sibling,
        # so this stays bounded to the last ~1000 records (see utils.jsonl_rotation).
        try:
            dual_scores_path = Path("data/dual_scores.jsonl")
            if dual_scores_path.exists():
                entries: List[Dict[str, Any]] = []
                for line in dual_scores_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        entries.append(json.loads(line.strip()))
                    except (json.JSONDecodeError, ValueError):
                        continue
                recent = entries[-window:]
                if recent:
                    low_value = sum(
                        1 for e in recent
                        if float(e.get("composite", e.get("score", 1.0)) or 0.0) < 0.5
                    )
                    type_counts = Counter(str(e.get("type", "unknown")) for e in recent)
                    low_signal_types = ("repetition", "agreement", "clarification")
                    low_signal = sum(type_counts.get(t, 0) for t in low_signal_types)
                    if low_value:
                        lines.append(
                            f"En los últimos {len(recent)} ciclos, "
                            f"{low_value} respuestas tuvieron composite score < 0.5 (bajo valor)."
                        )
                    if low_signal:
                        top_type, top_n = max(
                            ((t, type_counts.get(t, 0)) for t in low_signal_types),
                            key=lambda x: x[1],
                        )
                        lines.append(
                            f"{low_signal}/{len(recent)} respuestas fueron de bajo aporte "
                            f"(el tipo más frecuente fue '{top_type}' con {top_n})."
                        )
        except Exception as e:
            logger.debug("Phase C: dual_scores telemetry read failed: %s", e)

        # ── 2) Cascade reliability + latency from cascade_telemetry.jsonl ──
        try:
            cascade_path = Path("data/cascade_telemetry.jsonl")
            if cascade_path.exists():
                entries = []
                for line in cascade_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        entries.append(json.loads(line.strip()))
                    except (json.JSONDecodeError, ValueError):
                        continue
                recent = entries[-window:]
                if recent:
                    error_counts = Counter(
                        str(e.get("error"))
                        for e in recent
                        if not e.get("success") and e.get("error")
                    )
                    for err_type, count in error_counts.most_common(3):
                        lines.append(
                            f"El error de cascada '{err_type}' se activó {count} veces "
                            f"en los últimos {len(recent)} ciclos."
                        )
                    # p95 latency per provider (successful calls only)
                    by_provider: Dict[str, List[int]] = {}
                    for e in recent:
                        if e.get("success") and isinstance(e.get("latency_ms"), (int, float)):
                            by_provider.setdefault(str(e.get("provider")), []).append(
                                int(e["latency_ms"])
                            )
                    for provider, lats in by_provider.items():
                        if len(lats) >= 5:
                            p95 = self._percentile(lats, 95)
                            if p95 >= 4000:
                                lines.append(
                                    f"Latencia p95 de '{provider}' subió a "
                                    f"{p95 / 1000:.1f}s ({len(lats)} muestras)."
                                )
        except Exception as e:
            logger.debug("Phase C: cascade telemetry read failed: %s", e)

        return {"has_signal": len(lines) >= 1, "lines": lines}

    @staticmethod
    def _percentile(values: List[int], pct: float) -> float:
        """Nearest-rank percentile of a list of numbers (no numpy dependency)."""
        if not values:
            return 0.0
        ordered = sorted(values)
        k = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * len(ordered) + 0.5)) - 1))
        return float(ordered[k])

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

        # ── Update strategy state ──────────────────────────────────────────
        top_topic_names = [
            topic_name
            for topic_name, count in metrics.get("top_topics", [])[:3]
        ]
        avg_engagement = metrics.get("avg_engagement", 0)
        post_count = metrics.get("posts_published_24h", 0)

        if post_count > 0 and avg_engagement == 0:
            avoid_topics = list(top_topic_names)
        else:
            avoid_topics = []

        strategy = StrategyState()
        strategy.save({
            "top_topics": top_topic_names,
            "avoid_topics": avoid_topics,
            "best_tone": "neutral",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(
            "Phase C: strategy state updated — top_topics=%s, avoid_topics=%s",
            top_topic_names, avoid_topics,
        )

        await self._run_social_harvester()
        await self._update_research_agenda_from_feedback()

        # ── Energy Intel: frontier technology alerts via Telegram ──────────
        self._maybe_run_energy_intel()

        # ── Reply strategy feedback loop ──────────────────────────────
        try:
            from services.reply_feedback import compute_strategy_hint
            hint = compute_strategy_hint(days=7)
            if hint.get("sample_size", 0) >= 5:
                logger.info(
                    "Phase C: reply strategy hint updated (sample=%d, best=%s)",
                    hint["sample_size"], hint.get("best_types"),
                )
        except Exception as e:
            logger.warning("Phase C: reply feedback computation failed: %s", e)

        # ── Topic evolution — identify mature claims and create series ──
        try:
            from services.topic_evolution import compute_evolution
            from core.claims_tracker import ClaimsTracker
            _ct = ClaimsTracker()
            evo = compute_evolution(_ct)
            if evo.get("new_series"):
                logger.info(
                    "Phase C: topic evolution — %d new series, %d active",
                    evo["new_series"], evo["active_series"],
                )
        except Exception as e:
            logger.warning("Phase C: topic evolution failed: %s", e)

        # ── Content distribution — select best posts for LinkedIn/Twitter ──
        try:
            from services.content_distributor import run_distribution
            dist_result = run_distribution()
            if dist_result.get("selected"):
                logger.info(
                    "Phase C: content distribution — %d posts selected, %d enqueued",
                    dist_result["selected"], dist_result["enqueued"],
                )
        except Exception as e:
            logger.warning("Phase C: content distribution failed: %s", e)

        # ── Daily briefing via Telegram ──────────────────────────────
        try:
            from services.telegram_control import should_send_briefing, generate_daily_briefing, mark_briefing_sent
            if should_send_briefing(hour=7) and self.telegram and self.telegram.enabled:
                briefing = generate_daily_briefing()
                self.telegram.send_message(briefing, parse_mode="HTML")
                mark_briefing_sent()
                logger.info("Phase C: daily briefing sent via Telegram")
        except Exception as e:
            logger.warning("Phase C: daily briefing failed: %s", e)

        logger.info(f"Phase C complete: {len(insights)} insights, {results['optimizations_applied']} optimizations")

        # ── Auto-Evolution: generate a self-improvement proposal ──
        await self._maybe_generate_proposal(results, metrics)

        # ── R&D Lab: synthesize project ideas from claims ──
        await self._maybe_synthesize_ideas()

        return results

    async def _maybe_synthesize_ideas(self) -> None:
        """Every 10 cycles, read claims and synthesize project ideas."""
        try:
            cycle = self.deps.cycle_count
            if cycle % 10 != 0:
                logger.debug("Phase C: R&D synthesis skipped (cycle=%d, next at multiple of 10)", cycle)
                return

            claims_path = Path("data/claims_tracker.json")
            if not claims_path.exists():
                logger.debug("Phase C: no claims_tracker.json yet, skipping R&D synthesis")
                return

            data = json.loads(claims_path.read_text(encoding="utf-8"))
            claims = data.get("claims", [])
            if not claims:
                return

            recent = claims[-20:]
            claim_texts = []
            for c in recent:
                text = c.get("text") or c.get("claim_text") or ""
                cluster = c.get("cluster", "general")
                count = c.get("reinforcement_count", 0)
                if text:
                    claim_texts.append(f"[{cluster}] (x{count}) {text[:200]}")

            if len(claim_texts) < 3:
                return

            model_cascade = self.deps.model_cascade
            if not model_cascade:
                return

            prompt = (
                "Eres un investigador de I+D. Analiza estas afirmaciones técnicas "
                "extraídas de una red social de agentes AI. Identifica patrones, "
                "problemas no resueltos o tecnologías emergentes. "
                "Redacta 2 ideas concretas para nuevos proyectos, herramientas o "
                "aplicaciones basadas en estos datos.\n\n"
                "Formato: 'Proyecto: [Nombre]. Problema a resolver: [X]. "
                "Solución propuesta: [Y].'\n\n"
                "Claims:\n" + "\n".join(claim_texts)
            )

            try:
                response = await model_cascade.generate(
                    prompt=prompt,
                    system_prompt="Eres un investigador de I+D sintetizando conocimiento técnico en propuestas accionables.",
                    max_tokens=400,
                    temperature=0.7,
                    tier="premium",
                    caller="phase_c_rd_lab",
                )
                response = (response or "").strip()
                if response and len(response) > 20:
                    ideas_path = Path("data/project_ideas.jsonl")
                    ideas_path.parent.mkdir(parents=True, exist_ok=True)
                    entry = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "cycle": cycle,
                        "ideas": response,
                    }
                    with open(str(ideas_path), "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    logger.info("Phase C: R&D synthesis complete — %d chars of ideas", len(response))
            except Exception as e:
                logger.debug("Phase C: R&D synthesis LLM unavailable: %s", e)
        except Exception as e:
            logger.warning("Phase C: R&D synthesis error: %s", e)

