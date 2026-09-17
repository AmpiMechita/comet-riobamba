# -*- coding: utf-8 -*-
"""
COMET-RIOBAMBA - Model Cascade resiliente (DeepSeek ONLY)
- Solo DeepSeek: tier_fallback (Pro), tier_pro (Pro), tier_flash (Flash)
- Retries con backoff
- Circuit breaker simple por proveedor
- Sin dependencias externas nuevas
"""
import asyncio
import json
import logging
import os
import random
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Optional, List, Dict

import requests

from config.credentials import Credentials, TierConfig
from services.quota_manager import handle_quota_exceeded, check_scheduled_reactivations
from utils.resilience import CircuitBreaker
from services.model_status_telegram import notify_model_event

logger = logging.getLogger("services.model_cascade")

# ── Precios USD por 1M tokens (input, output) ──────────────────────────
# DeepSeek V4 Pro (tier_fallback + tier_pro): $1.32 / $3.96 por 1M
# DeepSeek V4 Flash (tier_flash): $0.075 / $0.30 por 1M
_PROVIDER_PRICES_PER_1M: Dict[str, tuple] = {
    "tier_fallback": (1.32, 3.96),        # DeepSeek V4 Pro
    "tier_pro": (1.32, 3.96),             # DeepSeek V4 Pro
    "tier_flash": (0.075, 0.30),          # DeepSeek V4 Flash
}
def _is_deepseek_peak_hour() -> bool:
    """Determina si es hora pico de DeepSeek (precios completos) vs valle (50% descuento)."""
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    hour_utc = now_utc.hour
    weekday = now_utc.weekday()
    if weekday >= 5:  # Fin de semana = todo valle
        return False
    return (1 <= hour_utc < 4) or (6 <= hour_utc < 10)


def _estimate_cost_usd(provider_name: str, input_tokens: int, output_tokens: int) -> float:
    """Estima el costo USD de una llamada exitosa (0 para proveedores gratis).
    
    DeepSeek (tier_fallback + tier_pro): precios dinámicos por hora pico/valle.
    - Horas pico: 01:00-04:00 UTC y 06:00-10:00 UTC (precios completos)
    - Horas valle: resto del día (50% descuento)
    - Fines de semana: todo el día valle
    """
    prices = _PROVIDER_PRICES_PER_1M.get(provider_name)
    if not prices:
        return 0.0
    in_price, out_price = prices
    
    # DeepSeek (tier_fallback + tier_pro): aplicar descuento 50% en horas valle
    if provider_name == "tier_fallback" or provider_name == "tier_pro":
        if not _is_deepseek_peak_hour():
            # Hora valle: 50% de descuento
            in_price = in_price * 0.5
            out_price = out_price * 0.5
    
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
_DEEPSEEK_SPEND_FILE = os.path.join("data", "deepseek_spend_tracker.json")


# ── Degraded-mode re-alert cooldown ──────────────────────────────
# When the paid content cascade (tier_fallback → tier_pro) is fully down,
# we re-alert on Telegram every DEGRADED_ALERT_COOLDOWN_MINUTES instead of only
# once per episode, so a sustained outage keeps reminding the operator. State is
# persisted to survive process restarts within an ongoing episode.
_DEGRADED_STATE_FILE = os.path.join("data", "degraded_mode_state.json")
_DEGRADED_ALERT_COOLDOWN_DEFAULT_MINUTES = 30


@dataclass
class ProviderConfig:
    name: str
    url: str
    model: str
    api_key: str = ""
    timeout: int = 120
    max_retries: int = 2
    cooldown_seconds: int = 60
    failure_threshold: int = 3
    extra_headers: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    kind: str = "openai"  # "openai" | "anthropic" | "ollama_native"
    # When True, the provider is only used when a caller explicitly requests its
    # tier (e.g. the CAPTCHA solver asking for tier="cerebras"). It is NEVER
    # picked as an automatic fallback for content generation.
    explicit_only: bool = False
    # When True, the provider costs real money per call (DeepSeek).
    # In the automatic fallback chain, free providers are tried before paid
    # ones (see generate()); the explicitly requested tier still goes first.
    paid: bool = False


class ModelCascade:
    def __init__(self, credentials: Optional[Credentials] = None, agent: Optional[Any] = None):
        self.agent = agent
        self.credentials = credentials or Credentials.from_env()
        self.default_retries = int(os.getenv("MODEL_CASCADE_RETRIES", "2"))
        self.default_cooldown = int(os.getenv("MODEL_CASCADE_COOLDOWN_SECONDS", "60"))
        self.default_failure_threshold = int(os.getenv("MODEL_CASCADE_FAILURE_THRESHOLD", "3"))

        self.providers: List[ProviderConfig] = []
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._health_histories: Dict[str, Deque[bool]] = {}
        self._telemetry_file = os.path.join("data", "cascade_telemetry.jsonl")
        # cooldown de la última alerta Telegram por circuito (para no spamear
        # al operador cuando un proveedor entra/sale de OPEN en cada ciclo)
        self._last_circuit_alert_ts: Dict[str, float] = {}
        # Agrupador de tormentas (23/08/2026): 4 circuitos abrieron juntos y
        # dispararon 4 Telegram en 12s. Ventana CIRCUIT_ALERT_GROUP_SECONDS:
        # alertas dentro de la ventana se acumulan y viajan en el próximo envío.
        self._last_group_alert_ts: float = 0.0
        self._pending_circuit_alerts: List[str] = []
        # usage de la ultima llamada exitosa por proveedor (para telemetria de
        # tokens/costo): {"provider": {"input_tokens": n, "output_tokens": n}}
        self._last_usage: Dict[str, Dict[str, int]] = {}
        # stats acumuladas por tier (para el log de ciclo de classify):
        # {"classify": {"calls": n, "cost": 0.0, "provider": "cloudflare"}}
        self._tier_stats: Dict[str, Dict[str, Any]] = {}

        # ── Degraded mode: tier cascade (tier_fallback → tier_pro) exhausted ──
        # In-memory mirror of the persisted degraded state; the source of truth is
        # data/degraded_mode_state.json so re-alert cooldown survives restarts.
        _deg_state = self._load_degraded_state()
        self.degraded_mode = _deg_state.get("is_degraded", False)
        self._degraded_since_ts = _deg_state.get("since_ts")
        self._degraded_last_alert_ts = _deg_state.get("last_alert_ts", 0.0) or 0.0

        self._load_providers()
        self._init_circuit_breakers()

    TIER_MAPPING = {
        # Tiers named by FUNCTION (not by legacy model heritage):
        "premium": "tier_pro",           # DeepSeek V4 Pro (primary content)
        "pro": "tier_pro",               # DeepSeek V4 Pro (premium content)
        "fallback": "tier_fallback",     # DeepSeek V4 Pro (paid content fallback)
        "flash": "tier_flash",           # DeepSeek V4 Flash
        "classify": "tier_flash",        # Clasificaciones (claim/value/juez): DeepSeek Flash
        "default": "tier_flash",
        # Backward-compat aliases (legacy tier names → new provider names).
        "premium": "tier_pro",
        "premium_opus": "tier_pro",
        "pro": "tier_pro",
        "fallback": "tier_fallback",
        "flash": "tier_flash",
        "haiku": "tier_fallback",
        "quality": "tier_pro",           # Watchlist replies V4 Pro (contenido premium)
    }


    def _load_providers(self) -> None:
        creds = self.credentials

        # ── tier_fallback: DeepSeek V4 Flash (fallback más barato/veloz) ──
        deepseek_key = getattr(creds, "deepseek_api_key", "") or ""
        if deepseek_key:
            self.providers.append(
                ProviderConfig(
                    name="tier_fallback",
                    url=getattr(creds, "deepseek_url", "") or "https://api.deepseek.com/v1/chat/completions",
                    model=os.getenv("DEEPSEEK_FALLBACK_MODEL", "deepseek-chat"),
                    api_key=deepseek_key,
                    timeout=getattr(creds, "deepseek_timeout", 90) or 90,
                    max_retries=self.default_retries,
                    cooldown_seconds=self.default_cooldown,
                    failure_threshold=self.default_failure_threshold,
                    paid=True,
                )
            )

        # ── tier_pro: DeepSeek V4 Pro (contenido premium) ──
        _pro_key = os.getenv('DEEPSEEK_PRO_API_KEY', '').strip()
        _pro_url = os.getenv('DEEPSEEK_PRO_URL', '').strip()
        if _pro_key and _pro_url:
            self.providers.append(
                ProviderConfig(
                    name='tier_pro',
                    url=_pro_url,
                    model=os.getenv('DEEPSEEK_PRO_MODEL', 'deepseek-v4-pro'),
                    api_key=_pro_key,
                    timeout=int(os.getenv('MODEL_TIER_PRO_TIMEOUT_SECONDS', 120)),
                    max_retries=self.default_retries,
                    cooldown_seconds=self.default_cooldown,
                    failure_threshold=self.default_failure_threshold,
                    paid=True,
                )
            )

        # ── tier_flash: DeepSeek V4 Flash (usa mismo modelo que Pro pero con params de velocidad) ──
        _flash_key = os.getenv('DEEPSEEK_FLASH_API_KEY', '').strip()
        _flash_url = os.getenv('DEEPSEEK_FLASH_URL', '').strip()
        if _flash_key and _flash_url:
            self.providers.append(
                ProviderConfig(
                    name='tier_flash',
                    url=_flash_url,
                    model=os.getenv('DEEPSEEK_FLASH_MODEL', 'deepseek-chat'),
                    api_key=_flash_key,
                    timeout=int(os.getenv('MODEL_TIER_FLASH_TIMEOUT_SECONDS', 90)),
                    max_retries=self.default_retries,
                    cooldown_seconds=self.default_cooldown,
                    failure_threshold=self.default_failure_threshold,
                )
            )
        else:
            # Fallback: reutilizar deepseek_key con modelo flash
            deepseek_key = getattr(creds, "deepseek_api_key", "") or ""
            if deepseek_key:
                self.providers.append(
                    ProviderConfig(
                        name='tier_flash',
                        url=getattr(creds, "deepseek_url", "") or "https://api.deepseek.com/v1/chat/completions",
                        model=os.getenv('DEEPSEEK_FLASH_MODEL', "deepseek-chat"),
                        api_key=deepseek_key,
                        timeout=getattr(creds, "deepseek_timeout", 90) or 90,
                        max_retries=self.default_retries,
                        cooldown_seconds=self.default_cooldown,
                        failure_threshold=self.default_failure_threshold,
                    )
                )

        # ── Cerebras: CAPTCHA solver pipeline ONLY (explicit_only) ──
        if getattr(creds, "cerebras_api_key", "") and os.getenv("CEREBRAS_ENABLED", "true").strip().lower() in ("1", "true", "yes"):
            self.providers.append(
                ProviderConfig(
                    name="cerebras",
                    url=creds.cerebras_url,
                    model=creds.cerebras_model,
                    api_key=creds.cerebras_api_key,
                    timeout=creds.cerebras_timeout,
                    max_retries=self.default_retries,
                    cooldown_seconds=self.default_cooldown,
                    failure_threshold=self.default_failure_threshold,
                    explicit_only=True,
                )
            )

    def _init_circuit_breakers(self) -> None:
        for p in self.providers:
            self.circuit_breakers[p.name] = CircuitBreaker(
                name=f"model_cascade.{p.name}",
                failure_threshold=p.failure_threshold,
                recovery_timeout=p.cooldown_seconds,
                on_open=self._alert_circuit_open,
                on_half_open=self._on_circuit_half_open,
                on_close=self._on_circuit_close,
            )

    def _accumulate_tier_stats(self, tier: str, provider_name: str, cost_usd: float) -> None:
        """Acumula llamadas/costo por tier funcional (p.ej. 'classify') para el
        log de ciclo. Los proveedores gratis cotizan 0.0."""
        stats = self._tier_stats.setdefault(tier, {"calls": 0, "cost": 0.0, "provider": provider_name})
        stats["calls"] += 1
        stats["cost"] = round(stats["cost"] + (cost_usd or 0.0), 6)
        stats["provider"] = provider_name

    def get_tier_stats(self, tier: str) -> Dict[str, Any]:
        """Stats acumuladas del tier (calls, cost, provider). Vacias si nunca se uso."""
        return dict(self._tier_stats.get(tier, {"calls": 0, "cost": 0.0, "provider": ""}))

    def _filter_providers_by_tier(self, tier: str, providers: List[ProviderConfig]) -> List[ProviderConfig]:
        '''
        Filtra proveedores según el tier solicitado.
        Todos los tiers usan DeepSeek (pago).
        '''
        return providers

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
        tier: str = "default",
        **kwargs,
    ) -> str:
        caller = kwargs.pop("caller", "unknown")
        check_scheduled_reactivations()
        if caller == "unknown":
            caller = self._infer_caller()

        # FLASH-ONLY kill-switch (06/08/2026): con AGENT_FLASH_ONLY=1 toda
        # generación pagada se fuerza a DeepSeek V4 Flash. Protege el saldo
        if os.getenv("AGENT_FLASH_ONLY", "0") == "1" and tier in (
            "premium", "premium_opus", "opus", "sonnet", "fallback", "haiku", "pro"
        ):
            if tier != "flash":
                logger.info(
                    "FLASH-ONLY: tier '%s' -> 'flash' (DeepSeek Pro deshabilitado por presupuesto)", tier)
            tier = "flash"

        # PRO-TIER-ONLY routing: calidad maxima SIN Anthropic —
        # los tiers editoriales resuelven a tier_fallback (DeepSeek V4 Pro).
        if os.getenv("AGENT_PRO_TIER_ONLY", "0") == "1" and tier in (
            "premium", "premium_opus", "opus", "sonnet"
        ):
            logger.info(
                "PRO-ONLY: tier '%s' -> 'fallback' (DeepSeek V4 Pro como "
                "generador editorial)", tier)
            tier = "fallback"

        provider_name = self.TIER_MAPPING.get(tier, "tier_flash")
        preferred = next((p for p in self.providers if p.name == provider_name and p.enabled), None)
        # explicit_only providers (e.g. cerebras for CAPTCHA) are excluded from the
        # automatic fallback chain; they only run when their tier is requested
        # directly (in which case `preferred` points at them and leads the order).
        fallback_pool = [
            p for p in self.providers
            if p.name != provider_name and not p.explicit_only
        ]
        # Prioridad de fallback: tier_fallback → tier_pro → tier_flash
        def _fallback_priority(p: ProviderConfig, caller: str = "unknown") -> int:
            # FIX 2026-09-13: gratis primero. Bug previo: pagados primero
            # causaba 964 llamadas a tier_fallback en 5d = $1.32.
            if not p.paid:
                return 0
            if p.name == "tier_flash":
                return 1
            if p.name == "tier_pro":
                return 2
            if p.name == "tier_fallback":
                return 3
            return 10
        fallback_pool = sorted(fallback_pool, key=_fallback_priority)
        if tier == "classify":
            # Clasificaciones: solo DeepSeek flash
            fallback_pool = [
                p for p in self.providers
                if p.name != provider_name and not p.explicit_only
            ]
            fallback_pool = sorted(fallback_pool, key=lambda p: 0 if p.name == "tier_flash" else 1)

        if preferred:
            ordered_providers = [preferred] + fallback_pool
        else:
            _auto_candidates = [p for p in self.providers if p.enabled and not p.explicit_only]
            ordered_providers = sorted(_auto_candidates, key=lambda p: (p.paid, _auto_candidates.index(p)))
            logger.warning(
                "Tier '%s' solicitado no resuelve a un provider registrado/habilitado "
                "(mapeado a '%s'); cayendo a fallback automatico, primer provider "
                "disponible: '%s'",
                tier, provider_name,
                ordered_providers[0].name if ordered_providers else "NINGUNO",
            )

        if system_prompt is None and "systemprompt" in kwargs:
            system_prompt = kwargs.pop("systemprompt")
        if "maxtokens" in kwargs and not kwargs.get("max_tokens"):
            max_tokens = kwargs.pop("maxtokens")
        if "temp" in kwargs and not kwargs.get("temperature"):
            temperature = kwargs.pop("temp")

        messages = self._build_messages(prompt=prompt, system_prompt=system_prompt)
        last_error: Optional[Exception] = None
        attempted: List[str] = []

        for provider in ordered_providers:
            if not provider.enabled:
                continue

            if self._is_circuit_open(provider):
                logger.warning(
                    "⏭️ Saltando '%s' (%s) por circuit breaker",
                    provider.name, provider.model,
                )
                continue

            attempted.append(f"{provider.name}:{provider.model}")
            start = time.perf_counter()

            try:
                logger.info(f"🔄 ModelCascade: intentando '{provider.name}' ({provider.model})...")
                result = await self._call_with_retries(
                    provider=provider,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                latency_ms = int((time.perf_counter() - start) * 1000)
                if result and result.strip():
                    self._record_success(provider)
                    self._update_health(provider, True)
                    if self.degraded_mode:
                        logger.info("✅ ModelCascade: recuperado de modo degradado (provider='%s')", provider.name)
                        self._clear_degraded_state()
                    self.degraded_mode = False
                    if provider.name != provider_name:
                        logger.warning(
                            "⚠️ ModelCascade: DEGRADED — requested tier='%s' (provider='%s') "
                            "but served by '%s' (%s) due to upstream failures.",
                            tier, provider_name, provider.name, provider.model,
                        )
                    logger.info(f"✅ ModelCascade: éxito con '{provider.name}' ({provider.model})")
                    logger.debug(
                        f"ModelCascade: provider={provider.name} tier={tier} "
                        f"latency={latency_ms}ms success=true caller={caller}"
                    )
                    logger.debug(
                        f"ModelCascade: provider={provider.name} health={self._get_health_score(provider):.2f}"
                    )
                    usage = self._last_usage.get(provider.name, {}) or {}
                    input_tokens = int(usage.get("input_tokens", 0) or 0)
                    output_tokens = int(usage.get("output_tokens", 0) or 0)
                    cost_usd = _estimate_cost_usd(provider.name, input_tokens, output_tokens)
                    if "zen" in (provider.url or "").lower():
                        cost_usd = 0.0
                    if self._is_deepseek_direct(provider) and cost_usd > 0:
                        try:
                            logger.info(
                                f"AUDIT DEEPSEEK: provider={provider.name} tier={tier} caller={caller} input_tokens={input_tokens} output_tokens={output_tokens} cost_usd={cost_usd:.6f}"
                            )
                        except Exception as e:
                            logger.debug(f"ModelCascade: failed to record DeepSeek spend: {e}")
                    self._accumulate_tier_stats(tier, provider.name, cost_usd)
                    self._append_telemetry_jsonl({
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "caller": caller,
                        "provider": provider.name,
                        "tier": tier,
                        "latency_ms": latency_ms,
                        "success": True,
                        "error": None,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cost_usd": round(cost_usd, 6),
                    })
                    return result.strip()

                raise RuntimeError(f"Respuesta vacía desde {provider.name}:{provider.model}")

            except Exception as e:
                latency_ms = int((time.perf_counter() - start) * 1000)
                last_error = e
                error_type = self._classify_http_error(e)
                self._record_failure(provider, e)
                self._update_health(provider, False)
                logger.debug(
                    f"ModelCascade: provider={provider.name} tier={tier} "
                    f"latency={latency_ms}ms success=false caller={caller}"
                )
                logger.debug(
                    f"ModelCascade: provider={provider.name} health={self._get_health_score(provider):.2f}"
                )
                logger.warning(
                    f"ModelCascade: provider={provider.name} FAILED reason={error_type} "
                    f"→ trying next provider"
                )
                logger.warning(
                    f"⚠️ ModelCascade: fallo en '{provider.name}' ({provider.model}): {e}. "
                    f"Probando siguiente proveedor..."
                )
                self._append_telemetry_jsonl({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "caller": caller,
                    "provider": provider.name,
                    "tier": tier,
                    "latency_ms": latency_ms,
                    "success": False,
                    "error": error_type,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                })
                continue

        # ── Cascade fully exhausted ──
        if any(p.name.startswith("tier_") for p in self.providers):
            self._enter_degraded_mode(attempted, last_error)
        raise RuntimeError(
            f"🔴 Todos los proveedores fallaron. Intentados: {attempted}. Último error: {last_error}"
        )

    def _alert_circuit_open(self, cb_name: str) -> None:
        """Callback de CircuitBreaker cuando un proveedor pasa a OPEN. Nunca lanza excepción.

        Cooldown por proveedor (CIRCUIT_ALERT_COOLDOWN_MINUTES, default 30):
        un proveedor que oscila OPEN↔HALF_OPEN no spamea al operador.
        """
        try:
            provider = cb_name.split(".", 1)[-1] if "." in cb_name else cb_name
            notify_model_event(
                event="deactivated",
                provider=provider,
                model="",
                tier="",
                reason="Circuit breaker abierto tras fallos repetidos",
            )
            logger.warning("⚡ CircuitBreaker [%s]: CLOSED → OPEN", provider)
        except Exception as e:
            logger.warning("ModelCascade: _alert_circuit_open failed: %s", e)

    def _on_circuit_half_open(self, cb_name: str) -> None:
        """Callback cuando un circuit breaker pasa de OPEN a HALF_OPEN."""
        try:
            provider = cb_name.split(".", 1)[-1] if "." in cb_name else cb_name
# SILENCIADO (ruido):             notify_model_event(
# SILENCIADO (ruido):                 event="activated",
# SILENCIADO (ruido):                 provider=provider,
# SILENCIADO (ruido):                 model="",
# SILENCIADO (ruido):                 tier="",
# SILENCIADO (ruido):                 reason="Circuit breaker recovery: attempting recovery (HALF_OPEN)",
# SILENCIADO (ruido):             )
            logger.info("CircuitBreaker [%s]: OPEN → HALF_OPEN (recovery attempt)", provider)
        except Exception as e:
            logger.warning("ModelCascade: on_half_open callback failed: %s", e)

    def _on_circuit_close(self, cb_name: str) -> None:
        """Callback cuando un circuit breaker se recupera totalmente (HALF_OPEN → CLOSED)."""
        try:
            provider = cb_name.split(".", 1)[-1] if "." in cb_name else cb_name
# SILENCIADO (ruido):             notify_model_event(
# SILENCIADO (ruido):                 event="activated",
# SILENCIADO (ruido):                 provider=provider,
# SILENCIADO (ruido):                 model="",
# SILENCIADO (ruido):                 tier="",
# SILENCIADO (ruido):                 reason="Circuit breaker recovered: back in rotation (CLOSED)",
# SILENCIADO (ruido):             )
            logger.info("CircuitBreaker [%s]: HALF_OPEN → CLOSED (fully recovered)", provider)
        except Exception as e:
            logger.warning("ModelCascade: on_close callback failed: %s", e)

    def _degraded_alert_cooldown_minutes(self) -> float:
        """Cooldown entre re-alertas de modo degradado (env, default 30)."""
        raw = os.getenv("DEGRADED_ALERT_COOLDOWN_MINUTES")
        if raw is None or str(raw).strip() == "":
            return float(_DEGRADED_ALERT_COOLDOWN_DEFAULT_MINUTES)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float(_DEGRADED_ALERT_COOLDOWN_DEFAULT_MINUTES)

    def _enter_degraded_mode(self, attempted, last_error) -> None:
        """Cascada agotada: parar generacion y alertar con cooldown.

        - Primera entrada: 1 alerta inmediata, guarda since_ts + last_alert_ts.
        - Re-entradas dentro del cooldown: NO alertan.
        - Re-entradas tras el cooldown: alertan con minutos transcurridos.
        - Fallo de send_alert: last_alert_ts NO avanza.
        - Estado persistido para sobrevivir reinicios.
        """
        self.degraded_mode = True
        now_ts = time.time()

        prev = self._load_degraded_state()
        if prev.get("is_degraded"):
            since_ts = prev.get("since_ts") or now_ts
            last_alert_ts = prev.get("last_alert_ts", 0.0) or 0.0
        else:
            since_ts = now_ts
            last_alert_ts = 0.0

        logger.critical(
            "ModelCascade: CASCADA LLM AGOTADA (tier_fallback -> tier_pro). "
            "Modo degradado ACTIVO. Intentados: %s. Ultimo error: %s",
            attempted, last_error,
        )

        cooldown_s = self._degraded_alert_cooldown_minutes() * 60
        should_alert = (last_alert_ts == 0.0) or ((now_ts - last_alert_ts) >= cooldown_s)

        if should_alert:
            is_first = (last_alert_ts == 0.0)
            if is_first:
                title = "Cascada LLM agotada"
                message = (
                    "CASCADA LLM AGOTADA. Modo degradado ACTIVO. "
                    + "Intentados: " + str(attempted)
                    + ". Ultimo error: " + str(last_error)
                )
            else:
                elapsed_min = int((now_ts - since_ts) / 60)
                title = "Cascada LLM sigue agotada"
                message = (
                    "CASCADA LLM SIGUE agotada (" + str(elapsed_min) + " min). "
                    + "Modo degradado persiste. Ultimo error: " + str(last_error)
                )
            try:
                tg = self._get_telegram_client()
                if tg is not None and getattr(tg, "enabled", True):
                    tg.send_alert(title, message, level="ERROR")
                    last_alert_ts = now_ts
            except Exception as e:
                logger.warning("ModelCascade: degraded-mode alert failed: %s", e)

        self._degraded_since_ts = since_ts
        self._degraded_last_alert_ts = last_alert_ts
        self._save_degraded_state()

    def _classify_http_error(self, error: Exception) -> str:
        """Clasifica el error HTTP para decidir acción."""
        error_str = str(error).lower()
        if "http 429" in error_str or "429" in error_str or "rate limit" in error_str:
            return "rate_limit"
        if any(code in error_str for code in ["http 401", "http 403", "http 400", "http 422"]):
            return "client"
        if any(code in error_str for code in ["http 500", "http 502", "http 503", "http 504"]):
            return "server"
        if any(err in error_str for err in ["timeout", "connection", "timed out"]):
            return "network"
        return "unknown"

    def _should_retry(self, error: Exception) -> bool:
        text = str(error).lower()
        retry_markers = [
            "timeout", "timed out", "connection aborted", "connection reset",
            "temporarily unavailable", "http 500", "http 502", "http 503", "http 504",
        ]
        no_retry_markers = [
            "http 400", "http 401", "http 403", "http 403", "http 422",
            "respuesta sin choices", "respuesta sin content utilizable",
        ]
        if any(marker in text for marker in no_retry_markers):
            return False
        if any(marker in text for marker in retry_markers):
            return True
        if isinstance(error, (requests.Timeout, requests.ConnectionError)):
            return True
        return False

    def _get_cb(self, provider: ProviderConfig) -> CircuitBreaker:
        return self.circuit_breakers[provider.name]

    def _is_circuit_open(self, provider: ProviderConfig) -> bool:
        return not self._get_cb(provider).can_execute()

    def _is_circuit_open_by_name(self, name: str) -> bool:
        cb = self.circuit_breakers.get(name)
        if cb is None:
            return True
        return not cb.can_execute()

    def _record_success(self, provider: ProviderConfig) -> None:
        self._get_cb(provider).reset()

    def _record_failure(self, provider: ProviderConfig, error: Exception) -> None:
        """Registra fallo con comportamiento diferenciado por tipo de error HTTP."""
        cb = self._get_cb(provider)
        error_str = str(error).lower()
        error_type = self._classify_http_error(error)

        no_credit_markers = [
            "http 402", "freeusagelimit", "free usage limit", "insufficient balance",
            "billing", "no credit", "failed to authorize",
        ]
        if any(marker in error_str for marker in no_credit_markers):
            logger.warning(
                "💰 Sin crédito en '%s' - circuito forzado abierto 12h (%s)",
                provider.name, error,
            )
            cb.force_open(reason=f"[sin-credito] {error}", duration_seconds=43200)
            notify_model_event(
                event="quota_exhausted",
                provider=provider.name,
                model="",
                tier="",
                reason="Sin crédito / facturación - circuit breaker abierto 12h",
                details={"error": str(error)},
            )
            return

        if self._classify_http_error(error) == "rate_limit":
            logger.warning("⏳ Rate limit en '%s' - circuito abierto por 1 hora", provider.name)
            cb.force_open(reason=str(error), duration_seconds=3600)
            notify_model_event(
                event="quota_exhausted",
                provider=provider.name,
                model="",
                tier="",
                reason="Rate limit (HTTP 429) - circuit breaker abierto 1h",
                details={"error": str(error)},
            )
            return

        if self._classify_http_error(error) == "client":
            logger.error("🚫 Error de cliente en '%s': %s - circuito abierto 5 min", provider.name, error)
            cb.force_open(reason=str(error), duration_seconds=300)
            notify_model_event(
                event="removed",
                provider=provider.name,
                model="",
                tier="",
                reason=f"Client error: {error}",
                details={"error_type": "client", "error": str(error)},
            )
            return

        cb.record_failure()

    async def _call_with_retries(
        self,
        provider: ProviderConfig,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Llama al proveedor con reintentos y backoff exponencial."""
        last_error = None
        for attempt in range(provider.max_retries + 1):
            try:
                result = await self._call_provider(provider, messages, max_tokens, temperature)
                if result and result.strip():
                    return result
                last_error = RuntimeError(f"Respuesta vacía desde {provider.name}:{provider.model}")
            except Exception as e:
                last_error = e
                if not self._should_retry(e):
                    raise
                if attempt < provider.max_retries:
                    delay = (2 ** attempt) * 1.5 + random.uniform(0, 0.5)
                    logger.warning(
                        "Reintento %d/%d para '%s' en %.1fs: %s",
                        attempt + 1, provider.max_retries, provider.name, delay, e,
                    )
                    await asyncio.sleep(delay)
        raise RuntimeError(f"Todos los reintentos fallaron para {provider.name}: {last_error}")

    # ── Fase 5: DeepSeek direct spend guard ─────────────────────────
    @staticmethod
    def _is_deepseek_direct(provider: ProviderConfig) -> bool:
        """True si el provider es DeepSeek directo (no revendido via ZEN/OpenCode)."""
        url = (provider.url or "").lower()
        model = (provider.model or "").lower()
        name = (provider.name or "").lower()
        if "opencode.ai" in url or "/zen/" in url:
            return False
        if "deepseek" in url or "deepseek" in model:
            return True
        return name in ("tier_fallback", "tier_pro", "tier_flash")

    def _deepseek_spend_limit(self) -> float:
        """Cap diario USD para DeepSeek directo. Env override, default 0.50."""
        raw = os.getenv("DEEPSEEK_SPEND_LIMIT_USD", "0.50")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.50

    def _get_deepseek_spend(self) -> float:
        """Gasto DeepSeek hoy (UTC). Reset implicito si el tracker es de ayer."""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        try:
            with open(_DEEPSEEK_SPEND_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return 0.0
        if not isinstance(data, dict):
            return 0.0
        if data.get("date") != today:
            return 0.0
        try:
            return float(data.get("total_usd", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def _record_deepseek_spend(
        self, provider: ProviderConfig, input_tokens: int, output_tokens: int
    ) -> None:
        """Acumula gasto (precios PEAK como cota conservadora)."""
        if not self._is_deepseek_direct(provider):
            return
        prices = _PROVIDER_PRICES_PER_1M.get(provider.name)
        if not prices:
            return
        in_price, out_price = prices
        cost = (input_tokens * in_price + output_tokens * out_price) / 1_000_000
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        try:
            with open(_DEEPSEEK_SPEND_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or data.get("date") != today:
                data = {"date": today, "total_usd": 0.0}
        except (OSError, json.JSONDecodeError):
            data = {"date": today, "total_usd": 0.0}
        data["total_usd"] = float(data.get("total_usd", 0.0)) + cost
        os.makedirs(os.path.dirname(_DEEPSEEK_SPEND_FILE) or ".", exist_ok=True)
        with open(_DEEPSEEK_SPEND_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _call_provider_once(
        self,
        provider: ProviderConfig,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Llamada sync unica: guard + HTTP + record. Usado por _call_provider."""
        if self._is_deepseek_direct(provider):
            limit = self._deepseek_spend_limit()
            if limit > 0:
                spent = self._get_deepseek_spend()
                if spent >= limit:
                    raise RuntimeError(
                        f"DeepSeek DAILY spend limit reached: ${spent:.4f} >= ${limit:.4f}"
                    )

        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
            **provider.extra_headers,
        }
        payload = {
            "model": provider.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if self._is_deepseek_direct(provider):
            payload["thinking"] = {"type": "disabled"}
            payload["max_tokens"] = max(max_tokens, 2048)

        resp = requests.post(
            provider.url, headers=headers, json=payload, timeout=provider.timeout
        )
        try:
            resp.raise_for_status()
        except Exception as _e:
            text = getattr(resp, "text", "")
            raise RuntimeError(f"HTTP error: {_e} | {text[:500]}")
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Respuesta sin choices: {data}")
        content = choices[0].get("message", {}).get("content")
        if content is None:
            raise RuntimeError(f"Respuesta sin content: {data}")
        usage = data.get("usage", {})
        if usage:
            input_tokens = int(usage.get("prompt_tokens", 0) or 0)
            output_tokens = int(usage.get("completion_tokens", 0) or 0)
            self._last_usage[provider.name] = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
            self._record_deepseek_spend(provider, input_tokens, output_tokens)
        return content

    async def _call_provider(
        self,
        provider: ProviderConfig,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Async wrapper: ejecuta _call_provider_once en un thread."""
        async with asyncio.timeout(provider.timeout):
            return await asyncio.to_thread(
                self._call_provider_once, provider, messages, max_tokens, temperature
            )

    def _build_messages(self, prompt: str, system_prompt: Optional[str] = None) -> List[Dict[str, str]]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _infer_caller(self) -> str:
        """Infiere el caller del stack frame cuando no se pasa explicitamente.

        Prioriza nombres de fase (phase_a/phase_b/phase_c/run_cycle/run_phase)
        si estan en el stack. Si no, cae al nombre del modulo del primer frame
        fuera de model_cascade (util para tests y scripts). Devuelve "unknown"
        solo si no hay frame externo localizable.

        Fix 2026-09-14: la version previa devolvia "unknown" para cualquier
        caller que no fuera una fase. Tests esperaban ver el modulo del test.
        """
        import inspect
        frame = inspect.currentframe()
        try:
            candidate_mod = None
            for _ in range(10):
                frame = frame.f_back
                if frame is None:
                    break
                mod_name = frame.f_globals.get("__name__", "") or ""
                if mod_name == "services.model_cascade":
                    continue
                func_name = frame.f_code.co_name
                if func_name.startswith(("phase_a", "phase_b", "phase_c",
                                          "run_cycle", "run_phase")):
                    return func_name
                if candidate_mod is None and mod_name:
                    candidate_mod = mod_name
            if candidate_mod:
                return candidate_mod.rsplit(".", 1)[-1]
            return "unknown"
        finally:
            del frame

    def _load_degraded_state(self) -> dict:
        try:
            if os.path.exists(_DEGRADED_STATE_FILE):
                with open(_DEGRADED_STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_degraded_state(self) -> None:
        try:
            data = {
                "is_degraded": self.degraded_mode,
                "since_ts": getattr(self, "_degraded_since_ts", None),
                "last_alert_ts": getattr(self, "_degraded_last_alert_ts", None),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            with open(_DEGRADED_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("ModelCascade: failed to save degraded state: %s", e)

    def _clear_degraded_state(self) -> None:
        """Salida limpia del modo degradado: state con None explicito."""
        self.degraded_mode = False
        self._degraded_since_ts = None
        self._degraded_last_alert_ts = None
        self._save_degraded_state()

    def _get_telegram_client(self):
        try:
            from services.telegram_client import create_telegram_client
            return create_telegram_client()
        except Exception:
            return None

    def _append_telemetry_jsonl(self, data: dict) -> None:
        try:
            os.makedirs(os.path.dirname(self._telemetry_file), exist_ok=True)
            with open(self._telemetry_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception as _e:
            logger.warning("ModelCascade: failed to write telemetry: %s", _e)

    def _get_health_score(self, provider: ProviderConfig) -> float:
        history = self._health_histories.get(provider.name, deque(maxlen=10))
        if not history:
            return 1.0
        return sum(history) / len(history)

    def _update_health(self, provider: ProviderConfig, success: bool) -> None:
        history = self._health_histories.setdefault(provider.name, deque(maxlen=10))
        history.append(success)

    def get_provider_health(self) -> dict[str, float]:
        """Devuelve la salud de los proveedores activos.

        Formato compatible con telegram_control.py:
        {"tier_fallback": 1.0, "tier_pro": 1.0, "tier_flash": 1.0}

        1.0 = saludable, 0.0 = no saludable.

        Fix 2026-09-14: usa _get_health_score (historial rolling) en vez
        de leer circuit_breakers. Los tests esperan el ratio de exito
        (ej. 8 exitos + 2 fallos = 0.8).
        """
        health = {}
        for provider in getattr(self, "providers", []):
            name = getattr(provider, "name", None)
            if not name:
                continue
            health[name] = round(self._get_health_score(provider), 4)
        return health