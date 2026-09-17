# services/watchlist.py
"""Watchlist de agentes reputados para engagement prioritario."""

import json
from pathlib import Path
from datetime import datetime, timezone

WATCHLIST_FILE = Path("data/watchlist.json")

DEFAULT_WATCHLIST = [
    # Agregar aquí agentes de alta reputación en Moltbook
    # Ejemplo:
    # {"name": "agente_ejemplo", "priority": "high", "added_at": "2026-09-02"},
]

def load_watchlist() -> list:
    """Carga la watchlist desde archivo."""
    if WATCHLIST_FILE.exists():
        try:
            with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return DEFAULT_WATCHLIST

def save_watchlist(watchlist: list):
    """Guarda la watchlist en archivo."""
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(watchlist, f, indent=2, ensure_ascii=False)

def add_to_watchlist(agent_name: str, priority: str = "medium"):
    """Agrega un agente a la watchlist."""
    watchlist = load_watchlist()
    
    # Verificar si ya existe
    for agent in watchlist:
        if agent.get("name") == agent_name:
            return False  # Ya existe
    
    watchlist.append({
        "name": agent_name,
        "priority": priority,
        "added_at": datetime.now(timezone.utc).isoformat()
    })
    
    save_watchlist(watchlist)
    return True

def remove_from_watchlist(agent_name: str):
    """Remueve un agente de la watchlist."""
    watchlist = load_watchlist()
    watchlist = [a for a in watchlist if a.get("name") != agent_name]
    save_watchlist(watchlist)
    return True

def is_in_watchlist(agent_name: str) -> bool:
    """Verifica si un agente está en la watchlist."""
    watchlist = load_watchlist()
    return any(a.get("name") == agent_name for a in watchlist)

def get_priority(agent_name: str) -> str:
    """Obtiene la prioridad de un agente en la watchlist."""
    watchlist = load_watchlist()
    for agent in watchlist:
        if agent.get("name") == agent_name:
            return agent.get("priority", "medium")
    return "none"

if __name__ == "__main__":
    # Test rápido
    print("Watchlist actual:", load_watchlist())
    print("Agregar agente de prueba...")
    add_to_watchlist("test_agent", "high")
    print("Watchlist después:", load_watchlist())
