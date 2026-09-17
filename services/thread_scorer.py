"""
Thread Scorer - Evalúa calidad de threads para decidir engagement.

Factores de scoring:
1. Autor es top agent → +2 pts
2. Dual score del post > 0.7 → +3 pts
3. Tema match con top_topics → +2 pts
4. Hora valle (50% descuento) → +1 pt
5. Pocas respuestas (<5) → +2 pts (oportunidad de ser primero)

Umbral para comentar: score >= 6
"""
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from services.watchlist_manager import get_watchlist

class ThreadScorer:
    # Pesos de scoring
    WEIGHT_TOP_AGENT = 2
    WEIGHT_HIGH_DUAL_SCORE = 3
    WEIGHT_TOPIC_MATCH = 2
    WEIGHT_VALLE_HOURS = 1
    WEIGHT_FIRST_MOVER = 2
    
    # Umbrales
    MIN_SCORE_TO_COMMENT = 6
    HIGH_DUAL_SCORE_THRESHOLD = 0.7
    MAX_EXISTING_REPLIES = 5
    
    def __init__(self):
        self.watchlist = get_watchlist()
        self.top_topics = ["agent", "llm", "security"]  # Desde strategy_state
    
    def score_thread(self, post: Dict[str, Any]) -> int:
        """
        Calcula score de un thread para decidir engagement.
        
        Args:
            post: Dict con info del post (author, dual_score, topic, replies_count, created_at)
        
        Returns:
            Score entero (0-10)
        """
        score = 0
        
        # 1. Autor es top agent
        author = post.get("author", "")
        if self.watchlist.is_top_agent(author, self.HIGH_DUAL_SCORE_THRESHOLD):
            score += self.WEIGHT_TOP_AGENT
        
        # 2. Dual score alto
        dual_score = post.get("dual_score", 0)
        if dual_score >= self.HIGH_DUAL_SCORE_THRESHOLD:
            score += self.WEIGHT_HIGH_DUAL_SCORE
        
        # 3. Match de tema
        topic = post.get("topic", "").lower()
        if any(t in topic for t in self.top_topics):
            score += self.WEIGHT_TOPIC_MATCH
        
        # 4. Hora valle
        if self._is_valle_hour():
            score += self.WEIGHT_VALLE_HOURS
        
        # 5. Primer movedor (pocas respuestas)
        replies_count = post.get("replies_count", 0)
        if replies_count < self.MAX_EXISTING_REPLIES:
            score += self.WEIGHT_FIRST_MOVER
        
        return score
    
    def should_engage(self, post: Dict[str, Any]) -> bool:
        """Decide si debe comentar en este thread."""
        score = self.score_thread(post)
        return score >= self.MIN_SCORE_TO_COMMENT
    
    def _is_valle_hour(self) -> bool:
        """Verifica si es hora valle (50% descuento DeepSeek)."""
        from services.model_cascade import _is_deepseek_peak_hour
        return not _is_deepseek_peak_hour()
    
    def get_engagement_reason(self, post: Dict[str, Any]) -> str:
        """Retorna razón principal para engagement."""
        reasons = []
        
        author = post.get("author", "")
        if self.watchlist.is_top_agent(author):
            reasons.append(f"Top agent: {author}")
        
        dual_score = post.get("dual_score", 0)
        if dual_score >= self.HIGH_DUAL_SCORE_THRESHOLD:
            reasons.append(f"High dual_score: {dual_score:.2f}")
        
        replies_count = post.get("replies_count", 0)
        if replies_count < self.MAX_EXISTING_REPLIES:
            reasons.append("First mover opportunity")
        
        if self._is_valle_hour():
            reasons.append("Valle hours (50% discount)")
        
        return "; ".join(reasons) if reasons else "Generic engagement"

# Singleton
_scorer_instance: Optional[ThreadScorer] = None

def get_thread_scorer() -> ThreadScorer:
    global _scorer_instance
    if _scorer_instance is None:
        _scorer_instance = ThreadScorer()
    return _scorer_instance
