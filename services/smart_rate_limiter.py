"""
Smart Rate Limiter - Optimiza engagement considerando costos, calidad y límites.

Responsabilidades:
1. Respetar límites de plataforma (max_comments_per_day, etc.)
2. Priorizar horas valle (50% descuento DeepSeek)
3. Priorizar top agents (watchlist)
4. Respetar min_comment_relevance_score
5. Distribuir comentarios a lo largo del día (evitar bursts)

Límites actuales (config/agent_policy.py):
- max_comments_per_day: 150
- max_feed_initiations_per_day: 10
- max_feed_replies_per_day: 60
- max_comment_replies_per_cycle: 30
- max_feed_comments_per_post: 10
"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from services.model_cascade import _is_deepseek_peak_hour

BASE_DIR = Path(__file__).parent.parent
RATE_LIMIT_STATE = BASE_DIR / "data/rate_limit_state.json"

class SmartRateLimiter:
    # Límites de plataforma
    MAX_COMMENTS_PER_DAY = 150
    MAX_FEED_INITIATIONS_PER_DAY = 10
    MAX_FEED_REPLIES_PER_DAY = 60
    MAX_COMMENTS_PER_CYCLE = 30
    MAX_COMMENTS_PER_POST = 10
    
    # Configuración estratégica
    VALLE_HOUR_BONUS = 1.5  # Multiplicador de prioridad en horas valle
    TOP_AGENT_BONUS = 2.0  # Multiplicador de prioridad para top agents
    
    def __init__(self):
        self.state = self._load_state()
        self.cycle_start = datetime.now(timezone.utc)
    
    def _load_state(self) -> Dict[str, Any]:
        """Carga estado de rate limits desde archivo."""
        if not RATE_LIMIT_STATE.exists():
            return self._create_default_state()
        try:
            return json.loads(RATE_LIMIT_STATE.read_text(encoding="utf-8"))
        except Exception:
            return self._create_default_state()
    
    def _create_default_state(self) -> Dict[str, Any]:
        """Crea estado inicial."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return {
            "date": today,
            "comments_published": 0,
            "feed_initiations": 0,
            "feed_replies": 0,
            "cycle_comments": 0,
            "last_comment_at": None,
            "comments_by_hour": {}
        }
    
    def _reset_if_new_day(self) -> None:
        """Resetea contadores si es nuevo día."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state.get("date") != today:
            self.state = self._create_default_state()
            self._save_state()
    
    def _save_state(self) -> None:
        """Guarda estado actual."""
        RATE_LIMIT_STATE.write_text(
            json.dumps(self.state, indent=2),
            encoding="utf-8"
        )
    
    def can_comment(self, thread_score: int, is_top_agent: bool = False) -> bool:
        """
        Decide si puede comentar basado en límites y prioridad.
        
        Args:
            thread_score: Score del thread (0-10)
            is_top_agent: Si el autor es top agent
        
        Returns:
            True si puede comentar, False si debe esperar
        """
        self._reset_if_new_day()
        
        # Verificar límites diarios
        if self.state["comments_published"] >= self.MAX_COMMENTS_PER_DAY:
            return False
        
        if self.state["feed_replies"] >= self.MAX_FEED_REPLIES_PER_DAY:
            return False
        
        # Verificar límite por ciclo
        if self.state["cycle_comments"] >= self.MAX_COMMENTS_PER_CYCLE:
            return False
        
        # Calcular prioridad ajustada
        priority = thread_score
        if is_top_agent:
            priority *= self.TOP_AGENT_BONUS
        
        # Bonus de hora valle
        if self._is_valle_hour():
            priority *= self.VALLE_HOUR_BONUS
        
        # Umbral dinámico: más estricto si estamos cerca del límite
        daily_usage = self.state["comments_published"] / self.MAX_COMMENTS_PER_DAY
        dynamic_threshold = 6.0  # Umbral base
        
        if daily_usage > 0.8:
            dynamic_threshold = 8.0  # Más estricto al 80% del límite
        elif daily_usage > 0.5:
            dynamic_threshold = 7.0  # Moderado al 50%
        
        # Top agents siempre pasan si thread_score >= 5
        if is_top_agent and thread_score >= 5:
            return True
        
        return priority >= dynamic_threshold
    
    def record_comment(self, comment_type: str = "feed_reply") -> None:
        """Registra un comentario publicado."""
        self._reset_if_new_day()
        
        self.state["comments_published"] += 1
        self.state["cycle_comments"] += 1
        self.state["last_comment_at"] = datetime.now(timezone.utc).isoformat()
        
        if comment_type == "feed_initiation":
            self.state["feed_initiations"] += 1
        elif comment_type == "feed_reply":
            self.state["feed_replies"] += 1
        
        # Tracking por hora
        hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
        if hour_key not in self.state["comments_by_hour"]:
            self.state["comments_by_hour"][hour_key] = 0
        self.state["comments_by_hour"][hour_key] += 1
        
        self._save_state()
    
    def reset_cycle(self) -> None:
        """Resetea contadores de ciclo."""
        self.state["cycle_comments"] = 0
        self._save_state()
    
    def _is_valle_hour(self) -> bool:
        """Verifica si es hora valle."""
        return not _is_deepseek_peak_hour()
    
    def get_usage_summary(self) -> Dict[str, Any]:
        """Retorna resumen de uso actual."""
        self._reset_if_new_day()
        return {
            "comments_published": self.state["comments_published"],
            "comments_remaining": self.MAX_COMMENTS_PER_DAY - self.state["comments_published"],
            "feed_initiations": self.state["feed_initiations"],
            "feed_replies": self.state["feed_replies"],
            "cycle_comments": self.state["cycle_comments"],
            "daily_usage_pct": round(
                self.state["comments_published"] / self.MAX_COMMENTS_PER_DAY * 100, 1
            ),
            "is_valle_hour": self._is_valle_hour()
        }
    
    def get_optimal_comment_window(self) -> Optional[str]:
        """
        Sugiere próxima ventana óptima para comentar.
        
        Returns:
            String con descripción de ventana (ej. "23:00-01:00 UTC") o None si no hay límites
        """
        if self.state["comments_published"] < self.MAX_COMMENTS_PER_DAY * 0.5:
            return "Any time (under 50% daily limit)"
        
        # Si estamos cerca del límite, sugerir horas valle
        if self._is_valle_hour():
            return "Now (valle hours - 50% discount)"
        else:
            return "Wait for valle hours (after 10:00 UTC or before 01:00 UTC)"

# Singleton
_limiter_instance: Optional[SmartRateLimiter] = None

def get_rate_limiter() -> SmartRateLimiter:
    global _limiter_instance
    if _limiter_instance is None:
        _limiter_instance = SmartRateLimiter()
    return _limiter_instance
