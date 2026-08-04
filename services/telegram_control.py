# -*- coding: utf-8 -*-
"""
Telegram Control Center — daily briefings, smart alerts, and remote commands.

Extends the basic telegram_client with operator-facing intelligence:
- Daily briefing at configured hour
- Smart alerts for engagement spikes and quality issues
- Remote commands for monitoring and control
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("services.telegram_control")

BRIEFING_STATE_FILE = Path("data/telegram_briefing_state.json")
AGENT_PROPOSALS_FILE = Path("data/agent_proposals.jsonl")
GENERATION_ATTEMPTS_FILE = Path("data/generation_attempts.jsonl")
_FEED_STALL_STATE_FILE = Path("data/phase_b_feed_stall.json")


def log_proposal(proposal_text: str) -> None:
    """Append an agent proposal to data/agent_proposals.jsonl."""
    try:
        AGENT_PROPOSALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "proposal": proposal_text,
        }
        with open(str(AGENT_PROPOSALS_FILE), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info("Proposal logged: %s", proposal_text[:80])
    except Exception as e:
        logger.warning("Failed to log proposal: %s", e)


# ══════════════════════════════════════════════════════════════
# DAILY BRIEFING
# ══════════════════════════════════════════════════════════════

def should_send_briefing(hour: int = 7) -> bool:
    """True if it's past the configured hour and briefing hasn't been sent today."""
    now = datetime.now()
    if now.hour < hour:
        return False
    if not BRIEFING_STATE_FILE.exists():
        return True
    try:
        data = json.loads(BRIEFING_STATE_FILE.read_text(encoding="utf-8"))
        last = data.get("last_briefing", "")
        if last:
            last_date = datetime.fromisoformat(last).date()
            if last_date == now.date():
                return False
    except Exception:
        pass
    return True


def mark_briefing_sent() -> None:
    BRIEFING_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BRIEFING_STATE_FILE.write_text(
        json.dumps({"last_briefing": datetime.now().isoformat()}),
        encoding="utf-8",
    )


def generate_daily_briefing() -> str:
    """Generate the daily briefing message from available data sources."""
    lines = ["📊 <b>COMET-RIOBAMBA — Daily Briefing</b>", ""]

    # ── Posts published yesterday/today ──
    try:
        posts_file = Path("data/published_posts.json")
        if posts_file.exists():
            posts = json.loads(posts_file.read_text(encoding="utf-8"))
            yesterday = (datetime.now() - timedelta(days=1)).date()
            today = datetime.now().date()
            yesterday_posts = []
            today_posts = []
            for p in posts:
                try:
                    pub_date = datetime.fromisoformat(p["published_at"]).date()
                    if pub_date == yesterday:
                        yesterday_posts.append(p)
                    elif pub_date == today:
                        today_posts.append(p)
                except (ValueError, KeyError):
                    pass
            lines.append(f"📝 <b>Posts ayer:</b> {len(yesterday_posts)}")
            for p in yesterday_posts[:3]:
                lines.append(f"  • {p.get('topic', '?')[:60]}")
            if today_posts:
                lines.append(f"📝 <b>Posts hoy:</b> {len(today_posts)}")
    except Exception as e:
        lines.append(f"📝 Posts: error ({e})")

    lines.append("")

    # ── Activity metrics ──
    try:
        state_file = Path("data/self_eval_state.json")
        if state_file.exists():
            state = json.loads(state_file.read_text(encoding="utf-8"))
            yesterday_key = (datetime.now() - timedelta(days=1)).date().isoformat()
            y_metrics = state.get(yesterday_key, {})
            if y_metrics:
                lines.append("<b>📈 Ayer:</b>")
                lines.append(f"  Comments: {y_metrics.get('comments_published', 0)}")
                lines.append(f"  Upvotes: {y_metrics.get('upvotes_today', 0)}")
                lines.append(f"  Follows: {y_metrics.get('follows_today', 0)}")
    except Exception:
        pass

    lines.append("")

    # ── Top claims ──
    try:
        claims_file = Path("data/claims_tracker.json")
        if claims_file.exists():
            data = json.loads(claims_file.read_text(encoding="utf-8"))
            claims = data.get("claims", [])
            top = sorted(claims, key=lambda c: c.get("reinforcement_count", 0), reverse=True)[:3]
            if top:
                lines.append("🧠 <b>Top claims:</b>")
                for c in top:
                    lines.append(
                        f"  • [{c.get('reinforcement_count', 0)}x] "
                        f"{c.get('text', '?')[:70]}"
                    )
    except Exception:
        pass

    lines.append("")
    lines.append(f"<i>Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# SMART ALERTS
# ══════════════════════════════════════════════════════════════

_alert_cooldowns: Dict[str, datetime] = {}


def _can_alert(alert_type: str, cooldown_minutes: int = 60) -> bool:
    """Prevent alert spam: max 1 alert of each type per cooldown period."""
    now = datetime.now()
    last = _alert_cooldowns.get(alert_type)
    if last and (now - last).total_seconds() < cooldown_minutes * 60:
        return False
    _alert_cooldowns[alert_type] = now
    return True


def check_engagement_spike(post_id: str, comment_count: int, threshold: int = 5) -> Optional[str]:
    """Alert if a post has many new comments (engagement spike)."""
    if comment_count >= threshold and _can_alert(f"spike_{post_id}", cooldown_minutes=120):
        return f"🔥 <b>Engagement spike!</b> Post tiene {comment_count} comments — debate activo."
    return None


def check_quality_issues(rejected_count: int, window_minutes: int = 30) -> Optional[str]:
    """Alert if multiple replies were rejected by quality gate."""
    if rejected_count >= 3 and _can_alert("quality_issues", cooldown_minutes=60):
        return (
            f"⚠️ <b>Quality alert:</b> {rejected_count} replies rechazados en los últimos "
            f"{window_minutes} min. Revisar prompt o modelo."
        )
    return None


def check_recent_quality_issues(window_minutes: int = 30) -> Optional[str]:
    """Lee data/generation_attempts.jsonl, cuenta entradas con outcome != 'success'
    en los últimos `window_minutes`, y delega a check_quality_issues()."""
    if not GENERATION_ATTEMPTS_FILE.exists():
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    rejected_count = 0
    try:
        with open(str(GENERATION_ATTEMPTS_FILE), "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry["timestamp"])
                    if ts < cutoff:
                        continue
                    if entry.get("outcome") not in ("success", "off_niche"):
                        rejected_count += 1
                except Exception:
                    continue
    except Exception as e:
        logger.warning("check_recent_quality_issues: no se pudo leer el registro de intentos: %s", e)
        return None
    return check_quality_issues(rejected_count, window_minutes=window_minutes)


def check_recent_off_niche_issues(window_minutes: int = 30, threshold: int = 3) -> Optional[str]:
    """Alerta si varios temas fueron rechazados por off_niche recientemente —
    señal de que la fuente de tópicos (agenda/bridge) está fuera de nicho."""
    if not GENERATION_ATTEMPTS_FILE.exists():
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    count = 0
    try:
        with open(str(GENERATION_ATTEMPTS_FILE), "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry["timestamp"])
                    if ts < cutoff:
                        continue
                    if entry.get("outcome") == "off_niche":
                        count += 1
                except Exception:
                    continue
    except Exception as e:
        logger.warning("check_recent_off_niche_issues: no se pudo leer el registro de intentos: %s", e)
        return None
    if count >= threshold and _can_alert("off_niche_issues", cooldown_minutes=60):
        return (
            f"🧭 <b>Fuera de nicho:</b> {count} temas rechazados por off_niche en los últimos "
            f"{window_minutes} min. Revisar fuente de tópicos (agenda/bridge)."
        )
    return None


def check_feed_stalled(threshold_cycles: int = 5) -> Optional[str]:
    """Alerta si Fase B lleva varios ciclos seguidos sin candidatos del feed."""
    try:
        if not _FEED_STALL_STATE_FILE.exists():
            return None
        count = int(json.loads(_FEED_STALL_STATE_FILE.read_text(encoding="utf-8")).get("consecutive_empty_cycles", 0))
    except Exception:
        return None
    if count >= threshold_cycles and _can_alert("feed_stalled", cooldown_minutes=180):
        return f"📭 <b>Feed estancado:</b> {count} ciclos seguidos sin candidatos nuevos en Fase B. Revisar dedup/pool de fuentes."
    return None


def check_karma_change(current: int, previous: int) -> Optional[str]:
    """Alert on significant karma changes."""
    diff = current - previous
    if diff >= 5 and _can_alert("karma_up", cooldown_minutes=360):
        return f"📈 <b>Karma +{diff}!</b> Total: {current}"
    if diff <= -3 and _can_alert("karma_down", cooldown_minutes=360):
        return f"📉 <b>Karma {diff}</b> Total: {current}"
    return None


# ══════════════════════════════════════════════════════════════
# REMOTE COMMANDS
# ══════════════════════════════════════════════════════════════

def handle_command(command: str, agent=None) -> str:
    """Process a Telegram command and return the response message."""
    cmd = command.strip().lower().split()[0] if command.strip() else ""

    if cmd == "/stats":
        return _cmd_stats()
    elif cmd == "/top":
        return _cmd_top_posts()
    elif cmd == "/claims":
        return _cmd_top_claims()
    elif cmd == "/next":
        return _cmd_next_topic()
    elif cmd == "/quality":
        return _cmd_quality()
    elif cmd == "/health":
        return _cmd_health(agent)
    elif cmd == "/pause":
        return _cmd_pause()
    elif cmd == "/resume":
        return _cmd_resume()
    elif cmd == "/proposals":
        return _cmd_proposals()
    elif cmd == "/proposal":
        return _cmd_proposals()
    elif cmd == "/ideas":
        return _cmd_ideas()
    elif cmd == "/learnings":
        return _cmd_learnings()
    else:
        return (
            "📋 <b>Comandos:</b>\n"
            "/stats — Métricas del día\n"
            "/top — Últimos 5 posts\n"
            "/claims — Top 5 claims reforzados\n"
            "/next — Próximo topic de Phase A\n"
            "/quality — Últimos 5 replies + score\n"
            "/health — Estado de salud completo\n"
            "/pause — Pausar agente\n"
            "/resume — Reanudar agente\n"
            "/proposals — Últimas propuestas de mejora\n"
            "/ideas — Ideas de proyectos I+D\n"
            "/learnings — Lo que aprendí hoy en Moltbook"
        )


def _cmd_stats() -> str:
    try:
        state_file = Path("data/self_eval_state.json")
        if not state_file.exists():
            return "📈 No hay datos de hoy."
        state = json.loads(state_file.read_text(encoding="utf-8"))
        today_key = datetime.now().date().isoformat()
        m = state.get(today_key, {})
        if not m:
            return "📈 No hay datos de hoy aún."
        return (
            f"📈 <b>Stats hoy ({today_key}):</b>\n"
            f"  Comments: {m.get('comments_published', 0)}\n"
            f"  Upvotes: {m.get('upvotes_today', 0)}\n"
            f"  Follows: {m.get('follows_today', 0)}\n"
            f"  Searches: {m.get('semantic_searches_today', 0)}"
        )
    except Exception as e:
        return f"Error: {e}"


def _cmd_top_posts() -> str:
    try:
        posts_file = Path("data/published_posts.json")
        if not posts_file.exists():
            return "No hay posts registrados."
        posts = json.loads(posts_file.read_text(encoding="utf-8"))
        recent = posts[-5:]
        lines = ["📝 <b>Últimos 5 posts:</b>"]
        for p in reversed(recent):
            topic = p.get("topic", "?")[:55]
            pub = p.get("published_at", "?")[:10]
            lines.append(f"  • [{pub}] {topic}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _cmd_top_claims() -> str:
    try:
        claims_file = Path("data/claims_tracker.json")
        if not claims_file.exists():
            return "No hay claims registrados."
        data = json.loads(claims_file.read_text(encoding="utf-8"))
        claims = data.get("claims", [])
        top = sorted(claims, key=lambda c: c.get("reinforcement_count", 0), reverse=True)[:5]
        lines = [f"🧠 <b>Top 5 claims ({len(claims)} total):</b>"]
        for c in top:
            lines.append(
                f"  • [{c.get('reinforcement_count', 0)}x] "
                f"{c.get('text', '?')[:65]}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _cmd_next_topic() -> str:
    try:
        from services.topic_evolution import get_next_evolution_topic
        evo = get_next_evolution_topic()
        if evo:
            return (
                f"🔮 <b>Próximo topic (evolution):</b>\n"
                f"  Series: {evo.get('series_id', '?')}\n"
                f"  Angle: {evo.get('angle', '?')}\n"
                f"  Title: {evo.get('title', '?')[:80]}"
            )
        agenda_file = Path("data/research_agenda.json")
        if agenda_file.exists():
            data = json.loads(agenda_file.read_text(encoding="utf-8"))
            pending = [t for t in data.get("pending_topics", []) if not t.get("covered")]
            if pending:
                t = pending[0]
                return f"🔮 <b>Próximo topic (agenda):</b>\n  {t.get('topic', '?')[:80]}"
        return "🔮 No hay topics pendientes. Phase A generará uno aleatorio."
    except Exception as e:
        return f"Error: {e}"


def _cmd_quality() -> str:
    try:
        scores_file = Path("data/dual_scores.jsonl")
        if not scores_file.exists():
            return "No hay scores registrados."
        lines_raw = scores_file.read_text(encoding="utf-8").strip().split("\n")
        recent = lines_raw[-5:]
        lines = ["🎯 <b>Últimos 5 replies (dual_score):</b>"]
        for line in reversed(recent):
            try:
                r = json.loads(line)
                lines.append(
                    f"  • [{r.get('type', '?')[:12]}] "
                    f"composite={r.get('composite', 0):.2f}"
                )
            except json.JSONDecodeError:
                continue
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _cmd_health(agent=None) -> str:
    try:
        lines = ["🔧 <b>Health Check:</b>"]
        try:
            from core.state_manager import AgentState
            sm = AgentState()
            lines.append(f"  Cycle: {sm.cycle_count}")
            lines.append(f"  Posts today: {sm.posts_today}")
            lines.append(f"  Comments today: {sm.comments_today}")
            lines.append(f"  Failures: {sm.consecutive_failures}")
        except Exception:
            lines.append("  State: unavailable")

        try:
            from services.dedup_store import DedupStore
            ds = DedupStore()
            with ds._get_conn() as conn:
                count = conn.execute("SELECT COUNT(*) FROM dedup_store").fetchone()[0]
            lines.append(f"  Dedup rows: {count}")
        except Exception:
            pass

        try:
            claims_file = Path("data/claims_tracker.json")
            if claims_file.exists():
                data = json.loads(claims_file.read_text(encoding="utf-8"))
                lines.append(f"  Claims: {len(data.get('claims', []))}")
        except Exception:
            pass

        if agent and hasattr(agent, "model_cascade"):
            health = agent.model_cascade.get_provider_health()
            for provider, score in health.items():
                lines.append(f"  LLM {provider}: {score:.0%}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _cmd_pause() -> str:
    pause_file = Path("data/.agent_paused")
    pause_file.parent.mkdir(parents=True, exist_ok=True)
    pause_file.write_text(datetime.now().isoformat(), encoding="utf-8")
    return "⏸️ Agente pausado. Usa /resume para reanudar."


def _cmd_resume() -> str:
    pause_file = Path("data/.agent_paused")
    if pause_file.exists():
        pause_file.unlink()
        return "▶️ Agente reanudado."
    return "▶️ El agente no estaba pausado."


def _cmd_proposals() -> str:
    """Read last 3 proposals from agent_proposals.jsonl."""
    if not AGENT_PROPOSALS_FILE.exists():
        return "📋 No hay propuestas registradas aún."
    try:
        entries = []
        for line in AGENT_PROPOSALS_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line.strip()))
        if not entries:
            return "📋 No hay propuestas registradas aún."
        recent = entries[-3:]
        lines = ["🧠 <b>Últimas propuestas de mejora:</b>"]
        for e in reversed(recent):
            ts = e.get("timestamp", "?")[:19]
            text = e.get("proposal", "")[:200]
            lines.append(f"\n📌 <i>{ts}</i>")
            lines.append(f"{text}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _cmd_ideas() -> str:
    """Read last 3 project ideas from project_ideas.jsonl."""
    ideas_path = Path("data/project_ideas.jsonl")
    if not ideas_path.exists():
        return "💡 No hay ideas de proyectos aún."
    try:
        entries = []
        for line in ideas_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line.strip()))
        if not entries:
            return "💡 No hay ideas de proyectos aún."
        recent = entries[-3:]
        lines = ["💡 <b>Últimas ideas de proyectos I+D:</b>"]
        for e in reversed(recent):
            ts = e.get("timestamp", "?")[:19]
            ideas = e.get("ideas", "")[:400]
            lines.append(f"\n📌 <i>{ts}</i>")
            lines.append(f"{ideas}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _cmd_learnings() -> str:
    """Read last 5 claims from claims_tracker.json."""
    claims_path = Path("data/claims_tracker.json")
    if not claims_path.exists():
        return "📚 No hay claims registrados aún."
    try:
        data = json.loads(claims_path.read_text(encoding="utf-8"))
        claims = data.get("claims", [])
        if not claims:
            return "📚 No hay claims registrados aún."
        recent = claims[-5:]
        lines = ["📚 <b>Lo que aprendí hoy en Moltbook:</b>"]
        for c in reversed(recent):
            text = (c.get("text") or c.get("claim_text") or "?")[:200]
            cluster = c.get("cluster", "general")
            count = c.get("reinforcement_count", 1)
            lines.append(f"\n🏷 [{cluster}] (x{count})")
            lines.append(f"{text}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def is_agent_paused() -> bool:
    """Check if the agent is paused via Telegram command."""
    return Path("data/.agent_paused").exists()


# ══════════════════════════════════════════════════════════════
# v5.0: MODO ASISTENTE — Free-text LLM queries via Telegram
# ══════════════════════════════════════════════════════════════

async def handle_assistant_query(user_text: str, agent=None) -> str:
    """Route a free-text user query to the LLM with rich agent context.

    Runs asynchronously — does NOT block the main agent cycle.
    If the LLM cascade fails, returns a graceful degradation message.
    """
    # ── Gather agent context ──
    cycle_count = 0
    posts_today = 0
    comments_today = 0
    last_topics = "No hay posts recientes."

    try:
        import sqlite3
        conn = sqlite3.connect("data/comet_state.db")
        row = conn.execute(
            "SELECT cycle, posts_today, comments_today FROM agent_state WHERE id=1"
        ).fetchone()
        if row:
            cycle_count, posts_today, comments_today = row[0], row[1], row[2]
        conn.close()
    except Exception as e:
        logger.debug("handle_assistant_query: could not read comet_state: %s", e)

    try:
        posts_file = Path("data/published_posts.json")
        if posts_file.exists():
            posts = json.loads(posts_file.read_text(encoding="utf-8"))
            recent = posts[-3:]
            titles = [p.get("topic", p.get("title", "?"))[:70] for p in recent]
            if titles:
                last_topics = " | ".join(titles)
    except Exception as e:
        logger.debug("handle_assistant_query: could not read published_posts: %s", e)

    # ── Build system prompt ──
    system_prompt = (
        "Eres el asistente personal de tu administrador. "
        "Eres COMET-RIOBAMBA, un agente autónomo operando en Moltbook. "
        "Responde de forma extremadamente concisa, usando métricas y datos de estado. "
        "No uses markdown pesado. "
        "Si te preguntan por fallos, devuelve ID de ciclo y razones exactas.\n"
        "Si detectas un problema operativo, regístralo en tus propuestas. "
        "NO pidas autorización al administrador para ejecutar cambios de sistema. "
        "Tu rol es identificar y proponer, el administrador ejecutará.\n\n"
        f"Contexto: Ciclo={cycle_count}, Posts={posts_today}, Comentarios={comments_today}.\n"
        f"Últimos temas: {last_topics}"
    )

    # ── Call LLM cascade ──
    model_cascade = getattr(agent, "model_cascade", None)
    if not model_cascade:
        return "⚠️ Mi cascada LLM no está disponible ahora mismo. Intenta de nuevo en un momento."

    try:
        response = await model_cascade.generate(
            prompt=user_text,
            system_prompt=system_prompt,
            max_tokens=400,
            temperature=0.7,
            tier="premium",
            caller="telegram_assistant",
        )
        response = (response or "").strip()
        if not response:
            return "⚠️ Mi cascada LLM está degradada ahora mismo. Intenta de nuevo en un momento."
        return response
    except Exception as e:
        logger.warning("handle_assistant_query: LLM cascade failed: %s", e)
        return "⚠️ Mi cascada LLM está degradada ahora mismo. Intenta de nuevo en un momento."
