# -*- coding: utf-8 -*-
"""
Watchlist Engagement - Priorización de engagement con agentes top.

Responsabilidades:
1. Calcular prioridad de engagement basada en dual_score y actividad reciente
2. Trackear últimos posts de cada agente top
3. Priorizar comentarios en posts de agentes high-priority
4. Calcular engagement_rate por agente
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any

logger = logging.getLogger("services.watchlist_engagement")

BASE_DIR = Path(__file__).parent.parent
WATCHLIST_CONFIG = BASE_DIR / "config/top_agents_watchlist.json"
ENGAGEMENT_STATE_FILE = BASE_DIR / "data/watchlist_engagement_state.json"


class WatchlistEngagement:
    def __init__(self):
        self.agents = self._load_watchlist()
        self.engagement_state = self._load_engagement_state()

    def _load_watchlist(self) -> List[Dict[str, Any]]:
        """Carga la lista de top agents desde configuración."""
        if not WATCHLIST_CONFIG.exists():
            return []
        try:
            data = json.loads(WATCHLIST_CONFIG.read_text(encoding="utf-8"))
            return data.get("top_agents", [])
        except Exception as e:
            logger.warning(f"Error loading watchlist: {e}")
            return []

    def _load_engagement_state(self) -> Dict[str, Any]:
        """Carga el estado de engagement desde archivo."""
        if not ENGAGEMENT_STATE_FILE.exists():
            return {"last_updated": None, "agent_stats": {}}
        try:
            return json.loads(ENGAGEMENT_STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Error loading engagement state: {e}")
            return {"last_updated": None, "agent_stats": {}}

    def get_priority_order(self) -> List[Dict[str, Any]]:
        """Retorna agentes ordenados por prioridad de engagement."""
        # Ordenar por: priority (high > medium > low), luego dual_score
        priority_map = {"high": 0, "medium": 1, "low": 2}
        return sorted(
            self.agents,
            key=lambda a: (priority_map.get(a.get("priority", "low"), 2), -a.get("dual_score", 0))
        )

    def get_engagement_score(self, author: str) -> float:
        """
        Calcula score de engagement para un autor.
        
        Fórmula: dual_score * 0.7 + activity_recency * 0.3
        """
        agent = next((a for a in self.agents if a.get("author") == author), None)
        if not agent:
            return 0.0
        
        dual_score = agent.get("dual_score", 0)
        comments_weekly = agent.get("comments_weekly", 0)
        
        # Actividad reciente (normalizada 0-1)
        activity_recency = min(1.0, comments_weekly / 100)
        
        return dual_score * 0.7 + activity_recency * 0.3

    def should_prioritize_comment(self, author: str) -> bool:
        """
        Decide si priorizar comentario en post de este autor.
        
        Criterios:
        - dual_score >= 0.7 (high priority)
        - O dual_score >= 0.6 Y comments_weekly >= 50
        """
        agent = next((a for a in self.agents if a.get("author") == author), None)
        if not agent:
            return False
        
        dual_score = agent.get("dual_score", 0)
        comments_weekly = agent.get("comments_weekly", 0)
        
        if dual_score >= 0.7:
            return True
        
        if dual_score >= 0.6 and comments_weekly >= 50:
            return True
        
        return False

    def track_engagement(self, author: str, engaged: bool = True) -> None:
        """Trackea engagement con un agente."""
        if author not in self.engagement_state["agent_stats"]:
            self.engagement_state["agent_stats"][author] = {
                "total_engagements": 0,
                "last_engagement": None,
                "engagement_rate": 0.0
            }
        
        stats = self.engagement_state["agent_stats"][author]
        stats["total_engagements"] += 1 if engaged else 0
        stats["last_engagement"] = datetime.now(timezone.utc).isoformat()
        
        # Calcular engagement rate (engagements / posts del agente)
        agent = next((a for a in self.agents if a.get("author") == author), None)
        if agent:
            posts_weekly = agent.get("comments_weekly", 1)
            stats["engagement_rate"] = stats["total_engagements"] / max(1, posts_weekly)
        
        self._save_engagement_state()

    def _save_engagement_state(self) -> None:
        """Guarda el estado de engagement en archivo."""
        try:
            self.engagement_state["last_updated"] = datetime.now(timezone.utc).isoformat()
            ENGAGEMENT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            ENGAGEMENT_STATE_FILE.write_text(
                json.dumps(self.engagement_state, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"Error saving engagement state: {e}")

    def get_engagement_report(self) -> Dict[str, Any]:
        """Genera reporte de engagement con todos los agentes."""
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_agents": len(self.agents),
            "agents": []
        }
        
        for agent in self.get_priority_order():
            author = agent.get("author")
            stats = self.engagement_state["agent_stats"].get(author, {})
            
            report["agents"].append({
                "author": author,
                "dual_score": agent.get("dual_score", 0),
                "priority": agent.get("priority", "low"),
                "comments_weekly": agent.get("comments_weekly", 0),
                "engagement_score": self.get_engagement_score(author),
                "total_engagements": stats.get("total_engagements", 0),
                "engagement_rate": stats.get("engagement_rate", 0),
                "last_engagement": stats.get("last_engagement")
            })
        
        return report


# Singleton
_engagement_instance: Optional[WatchlistEngagement] = None

def get_watchlist_engagement() -> WatchlistEngagement:
    global _engagement_instance
    if _engagement_instance is None:
        _engagement_instance = WatchlistEngagement()
    return _engagement_instance