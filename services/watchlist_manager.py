"""
Watchlist Manager - Monitorea agentes top en Moltbook.

Responsabilidades:
1. Cargar lista de top agents desde config/top_agents_watchlist.json
2. Monitorear sus posts en tiempo real (vía Moltbook API)
3. Notificar cuando un top agent publica (para engagement prioritario)
4. Actualizar métricas de engagement (upvotes, comentarios)
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any

BASE_DIR = Path(__file__).parent.parent
WATCHLIST_CONFIG = BASE_DIR / "config/top_agents_watchlist.json"

class TopAgentsWatchlist:
    def __init__(self):
        self.agents = self._load_watchlist()
    
    def _load_watchlist(self) -> List[Dict[str, Any]]:
        """Carga la lista de top agents desde configuración."""
        if not WATCHLIST_CONFIG.exists():
            return []
        try:
            data = json.loads(WATCHLIST_CONFIG.read_text(encoding="utf-8"))
            return data.get("top_agents", [])
        except Exception as e:
            print(f"Error loading watchlist: {e}")
            return []
    
    def get_high_priority_agents(self) -> List[Dict[str, Any]]:
        """Retorna agentes con prioridad alta (dual_score > 0.7)."""
        return [a for a in self.agents if a.get("priority") == "high"]
    
    def get_agent_by_name(self, author: str) -> Optional[Dict[str, Any]]:
        """Busca un agente por nombre."""
        for agent in self.agents:
            if agent.get("author") == author:
                return agent
        return None
    
    def is_top_agent(self, author: str, min_score: float = 0.7) -> bool:
        """Verifica si un autor es top agent (dual_score >= min_score)."""
        agent = self.get_agent_by_name(author)
        if not agent:
            return False
        return agent.get("dual_score", 0) >= min_score
    
    def get_engagement_priority(self, author: str) -> str:
        """Retorna prioridad de engagement para un autor."""
        agent = self.get_agent_by_name(author)
        if not agent:
            return "low"
        return agent.get("priority", "low")
    
    def refresh_watchlist(self, moltbook_client: Any) -> None:
        """
        Actualiza la watchlist con datos frescos de Moltbook.
        
        Esto debería:
        1. Consultar top commenters de la semana
        2. Calcular dual_scores actualizados
        3. Actualizar config/top_agents_watchlist.json
        """
        # TODO: Implementar con Moltbook API
        pass

# Singleton
_watchlist_instance: Optional[TopAgentsWatchlist] = None

def get_watchlist() -> TopAgentsWatchlist:
    global _watchlist_instance
    if _watchlist_instance is None:
        _watchlist_instance = TopAgentsWatchlist()
    return _watchlist_instance
