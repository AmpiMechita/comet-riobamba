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
        self.degraded_mode = self._load_degraded_state().get("is_degraded", False)

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
                    paid=False,
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
            if p.name == "tier_fallback":
                return 0
            if p.name == "tier_pro":
                return 1
            if p.name == "tier_flash":
                return 2
            if not p.paid:
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
            ordered_providers = sorted(_auto_candidates, key=lambda p: (p.paid, p.name))
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
            notify_model_event(
                event="activated",
                provider=provider,
                model="",
                tier="",
                reason="Circuit breaker recovery: attempting recovery (HALF_OPEN)",
            )
            logger.info("CircuitBreaker [%s]: OPEN → HALF_OPEN (recovery attempt)", provider)
        except Exception as e:
            logger.warning("ModelCascade: on_half_open callback failed: %s", e)

    def _on_circuit_close(self, cb_name: str) -> None:
        """Callback cuando un circuit breaker se recupera totalmente (HALF_OPEN → CLOSED)."""
        try:
            provider = cb_name.split(".", 1)[-1] if "." in cb_name else cb_name
            notify_model_event(
                event="activated",
                provider=provider,
                model="",
                tier="",
                reason="Circuit breaker recovered: back in rotation (CLOSED)",
            )
            logger.info("CircuitBreaker [%s]: HALF_OPEN → CLOSED (fully recovered)", provider)
        except Exception as e:
            logger.warning("ModelCascade: on_close callback failed: %s", e)

    def _enter_degraded_mode(self, attempted: List[str], last_error: Optional[Exception]) -> None:
        """Cascade exhausted (tier_fallback → tier_pro exhausted): stop generation and alert."""
        self.degraded_mode = True
        logger.critical(
            "🛑 ModelCascade: CASCADA LLM AGOTADA (tier_fallback → tier_pro). "
            "Modo degradado ACTIVO — generación de contenido detenida. "
            "Intentados: %s. Último error: %s",
            attempted, last_error,
        )
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

    async def _call_provider(
        self,
        provider: ProviderConfig,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Llama al endpoint del proveedor y devuelve el contenido de la respuesta."""
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
        async with asyncio.timeout(provider.timeout):
            resp = await asyncio.to_thread(
                requests.post, provider.url, headers=headers, json=payload, timeout=provider.timeout
            )
        if resp.status_code != 200:
            error_msg = f"HTTP {resp.status_code}: {resp.text[:500]}"
            raise RuntimeError(error_msg)
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Respuesta sin choices: {data}")
        content = choices[0].get("message", {}).get("content")
        if content is None:
            raise RuntimeError(f"Respuesta sin content: {data}")
        # Track token usage
        usage = data.get("usage", {})
        if usage:
            self._last_usage[provider.name] = {
                "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "output_tokens": int(usage.get("completion_tokens", 0) or 0),
            }
        return content

    def _build_messages(self, prompt: str, system_prompt: Optional[str] = None) -> List[Dict[str, str]]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _infer_caller(self) -> str:
        import inspect
        frame = inspect.currentframe()
        try:
            for _ in range(5):
                frame = frame.f_back
                if frame is None:
                    break
                name = frame.f_code.co_name
                if name.startswith(("phase_a", "phase_b", "phase_c", "run_cycle", "run_phase")):
                    return name
        finally:
            del frame
        return "unknown"

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
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            with open(_DEGRADED_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("ModelCascade: failed to save degraded state: %s", e)

    def _clear_degraded_state(self) -> None:
        self.degraded_mode = False
        try:
            if os.path.exists(_DEGRADED_STATE_FILE):
                os.remove(_DEGRADED_STATE_FILE)
        except Exception:
            pass

    def _is_deepseek_direct(self, provider: ProviderConfig) -> bool:
        return provider.name in ("tier_fallback", "tier_pro", "tier_flash")

    def _get_telegram_client(self):
        try:
            from services.telegram_client import TelegramClient
            return TelegramClient()
        except Exception:
            return None

    def _append_telemetry_jsonl(self, data: dict) -> None:
        try:
            os.makedirs(os.path.dirname(self._telemetry_file), exist_ok=True)
            with open(self._telemetry_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _get_health_score(self, provider: ProviderConfig) -> float:
        history = self._health_histories.get(provider.name, deque(maxlen=100))
        if not history:
            return 1.0
        return sum(history) / len(history)

    def _update_health(self, provider: ProviderConfig, success: bool) -> None:
        history = self._health_histories.setdefault(provider.name, deque(maxlen=100))
        history.append(success)

    def get_provider_health(self) -> dict[str, float]:
        """
        Devuelve la salud de los proveedores activos.

        Formato compatible con telegram_control.py:
        {
            "tier_fallback": 1.0,
            "tier_pro": 1.0,
            "tier_flash": 1.0
        }

        1.0 = saludable
        0.0 = no saludable
        """
        health = {}

        for provider in getattr(self, "providers", []):
            name = getattr(provider, "name", None)
            if not name:
                continue

            breaker = getattr(self, "circuit_breakers", {}).get(name)

            if breaker is None:
                breaker = getattr(self, "circuitbreakers", {}).get(name)

            if breaker is None:
                health[name] = 1.0
                continue

            state = getattr(breaker, "state", None)

            if state is None:
                is_open = getattr(breaker, "is_open", False)
                health[name] = 0.0 if is_open else 1.0
                continue

            state_text = str(state).upper()
            health[name] = 0.0 if state_text == "OPEN" else 1.0

        return health