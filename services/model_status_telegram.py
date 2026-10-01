# -*- coding: utf-8 -*-
"""
Notificaciones Telegram de estado de proveedores y modelos (model_cascade).
"""
import asyncio
import json
import logging
import time
from collections import defaultdict
from pathlib import Path
import os
from typing import Any, Dict, Optional

from config import behavior_cfg
from services.telegram_client import TelegramClient, create_telegram_client

logger = logging.getLogger("services.model_status_telegram")

_STATE_FILE = Path(__file__).resolve().parents[1] / "data/model_status_telegram_state.json"
_DEFAULT_MAX_PER_HOUR = 3
_DEFAULT_COOLDOWN_SECONDS = 300


class ModelStatusTelegram:
    """
    Gestiona notificaciones Telegram de eventos de model_cascade.

    Eventos soportados:
    - model_provider_activated: proveedor vuelve a rotación (CLOSED/HALF_OPEN tras OPEN)
    - model_provider_deactivated: proveedor sacado de rotación (OPEN por errores)
    - model_quota_exhausted: cuota agotada o rate limit duro (429)
    - model_removed: modelo concreto desactivado permanentemente
    """

    def __init__(self, telegram_client: Optional[TelegramClient] = None):
        if telegram_client is not None:
            self.telegram = telegram_client
        else:
            from services.telegram_client import create_telegram_client
            self.telegram = create_telegram_client()
        self.enabled = self.telegram is not None and self.telegram.enabled
        self._last_sent: Dict[str, float] = {}
        self._global_window: list = []  # timestamps de los últimos envíos (rate limit global)
        self._load_state()
        self._max_per_hour = behavior_cfg.get("model_status_max_per_hour", _DEFAULT_MAX_PER_HOUR)
        self._cooldown = behavior_cfg.get("model_status_cooldown_seconds", _DEFAULT_COOLDOWN_SECONDS)

    def _load_state(self):
        try:
            if _STATE_FILE.exists():
                data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
                self._last_sent = data.get("last_sent", {})
        except Exception as e:
            logger.debug("model_status_telegram: no se pudo cargar estado: %s", e)

    def _save_state(self):
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _STATE_FILE.write_text(
                json.dumps({"last_sent": self._last_sent}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("model_status_telegram: no se pudo guardar estado: %s", e)

    def _should_send(self, key: str) -> bool:
        """Verifica rate limit por clave (provider|event)."""
        now = time.time()
        last = self._last_sent.get(key, 0)
        if now - last < self._cooldown:
            return False
        # Contar mensajes en la última hora
        hour_ago = now - 3600
        count = sum(1 for k, v in self._last_sent.items() if k.startswith(key.split("|")[0]) and v > hour_ago)
        if count >= self._max_per_hour:
            return False
        # Rate limit global (evita bursts que Telegram interpreta como "chat not found")
        now = time.time()
        self._global_window = [t for t in self._global_window if now - t < 60]
        if len(self._global_window) >= 5:
            return False
        self._global_window.append(now)

        return True

    def _send(self, text: str, parse_mode: str = "HTML"):
        if not self.enabled or self.telegram is None:
            return False
        try:
            ok = self.telegram.send_message(text, parse_mode=parse_mode, disable_notification=True)
            return ok
        except Exception as e:
            logger.warning("model_status_telegram: error enviando: %s", e)
            return False

    def notify(
        self,
        event: str,
        provider: str,
        model: str,
        tier: str,
        reason: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Envía notificación si pasa rate limit.

        event: "activated" | "deactivated" | "quota_exhausted" | "removed"
        """
        if not self.enabled:
            return False

        key = f"{provider}|{event}"
        if not self._should_send(key):
            return False

        icons = {
            "activated": "✅",
            "deactivated": "🔴",
            "quota_exhausted": "⚠️",
            "removed": "🗑️",
        }
        icon = icons.get(event, "ℹ️")

        lines = [
            f"{icon} <b>Model Cascade: {event.replace('_', ' ').title()}</b>",
            f"Proveedor: <code>{provider}</code>",
            f"Modelo: <code>{model}</code>",
            f"Tier: <code>{tier}</code>",
        ]
        if reason:
            lines.append(f"Motivo: {reason}")
        if details:
            for k, v in details.items():
                lines.append(f"  {k}: {v}")

        text = "\n".join(lines)
        ok = self._send(text)
        if ok:
            self._last_sent[key] = time.time()
            self._save_state()
        return ok


# Instancia global para importación fácil
_model_status_telegram: Optional[ModelStatusTelegram] = None


def get_model_status_telegram() -> ModelStatusTelegram:
    global _model_status_telegram
    if _model_status_telegram is None:
        _model_status_telegram = ModelStatusTelegram()
    return _model_status_telegram


def notify_model_event(
    event: str,
    provider: str,
    model: str,
    tier: str,
    reason: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> bool:
    """Función de conveniencia para notificar eventos desde cualquier módulo."""
    return get_model_status_telegram().notify(event, provider, model, tier, reason, details)