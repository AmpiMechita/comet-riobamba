# -*- coding: utf-8 -*-
"""
QuotaManager - Gestión de cuotas para proveedores DeepSeek.
Activado/desactivado automático según cuota disponible.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
import json
from pathlib import Path
import os
import logging

logger = logging.getLogger("services.quota_manager")

# Solo DeepSeek tiers (todos pagados)
DEEPSEEK_TIERS = {"tier_fallback", "tier_pro", "tier_flash"}


@dataclass
class ProviderQuota:
    provider: str
    enabled: bool = True
    daily_limit: int = 10000
    daily_used: int = 0
    last_reset: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_healthy: bool = True
    
    @property
    def remaining(self) -> int:
        return max(0, self.daily_limit - self.daily_used)
    
    @property
    def has_quota(self) -> bool:
        return self.enabled and self.remaining > 0 and self.is_healthy


class QuotaManager:
    def __init__(self, config_path: str = "config/provider_quotas.json"):
        self.config_path = Path(config_path)
        self.quotas: Dict[str, ProviderQuota] = {}
        self._load_quotas()
    
    def _load_quotas(self):
        if not self.config_path.exists():
            self._init_default_quotas()
            return
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for name, cfg in data.get("providers", {}).items():
            self.quotas[name] = ProviderQuota(
                provider=name,
                enabled=cfg.get("enabled", True),
                daily_limit=cfg.get("daily_limit", 10000),
                daily_used=cfg.get("daily_used", 0),
                last_reset=cfg.get("last_reset", datetime.now(timezone.utc).isoformat()),
                is_healthy=cfg.get("is_healthy", True)
            )
    
    def _init_default_quotas(self):
        default_quotas = {
            "tier_fallback": {"daily_limit": 500},
            "tier_pro": {"daily_limit": 200},
            "tier_flash": {"daily_limit": 5000},
        }
        
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "providers": {
                name: {
                    "enabled": cfg.get("enabled", True),
                    "daily_limit": cfg["daily_limit"],
                    "daily_used": 0,
                    "last_reset": now,
                    "is_healthy": True
                }
                for name, cfg in default_quotas.items()
            }
        }
        
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        self._load_quotas()
    
    def record_usage(self, provider: str, tokens: int):
        if provider not in self.quotas:
            return
        self.quotas[provider].daily_used += tokens
        self._save_quotas()
    
    def get_available_providers(self) -> List[str]:
        return [p for p in self.quotas if self.quotas[p].has_quota]
    
    def has_any_quota(self) -> bool:
        return len(self.get_available_providers()) > 0
    
    def _save_quotas(self):
        data = {
            "providers": {
                name: {
                    "enabled": q.enabled,
                    "daily_limit": q.daily_limit,
                    "daily_used": q.daily_used,
                    "last_reset": q.last_reset,
                    "is_healthy": q.is_healthy
                }
                for name, q in self.quotas.items()
            }
        }
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    def mark_unhealthy(self, provider: str, reason: str = ""):
        if provider in self.quotas:
            self.quotas[provider].is_healthy = False
            self._save_quotas()
    
    def mark_healthy(self, provider: str):
        if provider in self.quotas:
            self.quotas[provider].is_healthy = True
            self._save_quotas()
    
    def reset_daily(self):
        now = datetime.now(timezone.utc).isoformat()
        for q in self.quotas.values():
            q.daily_used = 0
            q.last_reset = now
        self._save_quotas()
    
    def get_status(self) -> Dict[str, Dict]:
        return {
            name: {
                "remaining": q.remaining,
                "has_quota": q.has_quota,
                "is_healthy": q.is_healthy
            }
            for name, q in self.quotas.items()
        }


def handle_quota_exceeded(provider: str, quota_manager: 'QuotaManager'):
    """Manejar exceso de cuota para un proveedor."""
    qm = get_global_quota_manager()
    if qm is None:
        logging.info(f"⚠️  {provider}: cuota excedida (sin QuotaManager activo, ignorado)")
        return
    qm.mark_unhealthy(provider, reason="quota_exceeded")
    logging.info(f"⚠️  {provider}: cuota excedida, marcado como no saludable")


# Instancia global
_quota_manager_instance: Optional['QuotaManager'] = None

def set_global_quota_manager(qm: 'QuotaManager'):
    global _quota_manager_instance
    _quota_manager_instance = qm

def get_global_quota_manager() -> Optional['QuotaManager']:
    return _quota_manager_instance


def check_scheduled_reactivations():
    """Verificar y reactivar proveedores programados."""
    now = datetime.now(timezone.utc)
    
    qm = get_global_quota_manager()
    if qm is None:
        return
    for name, quota in qm.quotas.items():
        # Reactivar automáticamente a medianoche UTC
        try:
            last_reset = datetime.fromisoformat(quota.last_reset.replace('Z', '+00:00'))
        except:
            last_reset = datetime.fromisoformat(quota.last_reset)
        
        hours_since_reset = (now - last_reset).total_seconds() / 3600
        
        if hours_since_reset >= 24 and quota.daily_used > 0:
            qm.reset_daily()
            logging.info(f"✅ {name}: cuotas diarias reseteadas (han pasado {hours_since_reset:.1f}h)")
            break  # Solo resetear una vez por llamada


# Instancia global
_quota_manager_instance: Optional['QuotaManager'] = None