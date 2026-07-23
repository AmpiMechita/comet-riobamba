# -*- coding: utf-8 -*-
"""
COMET-RIOBAMBA - Model Cascade resiliente
- Local-first con soporte real para fallback
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
from utils.resilience import CircuitBreaker

logger = logging.getLogger("services.model_cascade")

# ── Anthropic spend guard ────────────────────────────────────────
# Pricing for claude-sonnet-5 (USD per 1M tokens). Used to estimate the
# cumulative cost of Anthropic calls and stop before blowing the budget.
_ANTHROPIC_INPUT_PRICE_PER_1M = 2.0
_ANTHROPIC_OUTPUT_PRICE_PER_1M = 10.0
_ANTHROPIC_SPEND_FILE = os.path.join("data", "anthropic_spend_tracker.json")
_ANTHROPIC_SPEND_LIMIT_DEFAULT = 4.50

# ── Degraded-mode re-alert cooldown ──────────────────────────────
# When the paid content cascade (tier_premium → tier_fallback) is fully down,
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
    # When True, the provider costs real money per call (Anthropic, DeepSeek).
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

        # ── Degraded mode: tier cascade (tier_premium → tier_fallback) exhausted ──
        # In-memory mirror of the persisted degraded state; the source of truth is
        # data/degraded_mode_state.json so re-alert cooldown survives restarts.
        self.degraded_mode = self._load_degraded_state().get("is_degraded", False)

        self._load_providers()
        self._init_circuit_breakers()

    TIER_MAPPING = {
        # Tiers named by FUNCTION (not by legacy model heritage):
        "premium": "tier_premium",     # Anthropic claude-sonnet-5 (primary content)
        "fallback": "tier_fallback",   # DeepSeek V4 Pro (paid content fallback)
        "sonnet": "tier_sonnet",
        "openrouter": "openrouter",
        "cerebras": "cerebras",
        "groq": "groq",
        "default": "ollama_local",
        # Backward-compat aliases (legacy tier names → new provider names).
        "opus": "tier_premium",
        "haiku": "tier_fallback",
    }


    def _load_providers(self) -> None:
        creds = self.credentials

        # ── tier_premium: Anthropic Claude (claude-sonnet-5, primary content) ──
        # When ANTHROPIC_API_KEY is present, tier_premium is served by Anthropic's
        # Messages API. DeepSeek V4 Pro serves tier_fallback. If the Anthropic key
        # is missing we fall back to the env-configured tier_opus credentials so
        # the cascade keeps working in dev/test environments.
        anthropic_key = getattr(creds, "anthropic_api_key", "") or ""
        if anthropic_key:
            self.providers.append(
                ProviderConfig(
                    name="tier_premium",
                    url=getattr(creds, "anthropic_url", "") or "https://api.anthropic.com/v1/messages",
                    model=getattr(creds, "anthropic_model", "") or "claude-sonnet-5",
                    api_key=anthropic_key,
                    timeout=getattr(creds, "anthropic_timeout", 120) or 120,
                    max_retries=self.default_retries,
                    cooldown_seconds=self.default_cooldown,
                    failure_threshold=self.default_failure_threshold,
                    kind="anthropic",
                    paid=True,
                )
            )
        else:
            logger.warning(
                "Falta ANTHROPIC_API_KEY en .env. La cascada LLM fallará al intentar "
                "usar Claude 3.5 Sonnet."
            )
            if creds.tier_opus is not None:
                cfg = creds.tier_opus
                self.providers.append(
                    ProviderConfig(
                        name="tier_premium",
                        url=cfg.url,
                        model=cfg.model,
                        api_key=cfg.api_key,
                        timeout=cfg.timeout_seconds,
                        max_retries=self.default_retries,
                        cooldown_seconds=self.default_cooldown,
                        failure_threshold=self.default_failure_threshold,
                        paid=True,
                    )
                )

        # ── tier_sonnet (Gemini) + openrouter + cloudflare: flag-gated ────
        # Proveedores gratis, reversibles por flag (GEMINI_ENABLED,
        # OPENROUTER_ENABLED, CLOUDFLARE_ENABLED). Activados 22/7/2026 por falta
        # de credito en DeepSeek; desde esa fecha el fallback automatico prueba
        # gratis antes que pago (ver generate() y el campo `paid`), asi que
        # estos cubren fallas de los tiers pagos sin degradar a Anthropic.
        _gemini_enabled = os.getenv("GEMINI_ENABLED", "false").strip().lower() in ("1", "true", "yes")
        _openrouter_enabled = os.getenv("OPENROUTER_ENABLED", "false").strip().lower() in ("1", "true", "yes")
        _cloudflare_enabled = os.getenv("CLOUDFLARE_ENABLED", "false").strip().lower() in ("1", "true", "yes")

        tier_configs: list[tuple[str, Optional[TierConfig], bool]] = [
            ("tier_sonnet", creds.tier_sonnet, _gemini_enabled),
            ("openrouter", creds.tier_openrouter, _openrouter_enabled),
            ("cloudflare", creds.tier_cloudflare, _cloudflare_enabled),
        ]
        for provider_name, cfg, flag_enabled in tier_configs:
            if cfg is None:
                continue
            if not flag_enabled:
                logger.info(
                    "ModelCascade: '%s' NO registrado (flag desactivado por decisión de producto).",
                    provider_name,
                )
                continue
            self.providers.append(
                ProviderConfig(
                    name=provider_name,
                    url=cfg.url,
                    model=cfg.model,
                    api_key=cfg.api_key,
                    timeout=cfg.timeout_seconds,
                    max_retries=self.default_retries,
                    cooldown_seconds=self.default_cooldown,
                    failure_threshold=self.default_failure_threshold,
                )
            )

        # ── Cerebras: fallback de CONTENIDO (flag independiente, entrada separada) ──
        # Provider adicional para generación de contenido, distinto del de CAPTCHA
        # de abajo (ese sigue explicit_only=True, sin tocar). Activado 22/7/2026
        # porque Anthropic y DeepSeek se quedaron sin crédito — Cerebras tiene tier
        # gratis real. Flag propio (CEREBRAS_CONTENT_ENABLED) para poder apagarlo
        # sin afectar el pipeline de CAPTCHA.
        _cerebras_content_enabled = os.getenv("CEREBRAS_CONTENT_ENABLED", "false").strip().lower() in ("1", "true", "yes")
        if creds.cerebras_api_key and _cerebras_content_enabled:
            self.providers.append(
                ProviderConfig(
                    name="cerebras_content",
                    url=creds.cerebras_url,
                    model=creds.cerebras_model,
                    api_key=creds.cerebras_api_key,
                    timeout=creds.cerebras_timeout,
                    max_retries=self.default_retries,
                    cooldown_seconds=self.default_cooldown,
                    failure_threshold=self.default_failure_threshold,
                    explicit_only=False,
                )
            )

        # ── tier_fallback: DeepSeek V4 Pro (paid fallback after Anthropic) ──
        # Prefer explicit DEEPSEEK_* config; otherwise reuse the env-configured
        # tier_haiku credentials so existing setups keep working.
        deepseek_key = getattr(creds, "deepseek_api_key", "") or ""
        if deepseek_key:
            self.providers.append(
                ProviderConfig(
                    name="tier_fallback",
                    url=getattr(creds, "deepseek_url", "") or "https://api.deepseek.com/v1/chat/completions",
                    model=getattr(creds, "deepseek_model", "") or "deepseek-v4-pro",
                    api_key=deepseek_key,
                    timeout=getattr(creds, "deepseek_timeout", 90) or 90,
                    max_retries=self.default_retries,
                    cooldown_seconds=self.default_cooldown,
                    failure_threshold=self.default_failure_threshold,
                    paid=True,
                )
            )
        elif creds.tier_haiku is not None:
            cfg = creds.tier_haiku
            self.providers.append(
                ProviderConfig(
                    name="tier_fallback",
                    url=cfg.url,
                    model=cfg.model,
                    api_key=cfg.api_key,
                    timeout=cfg.timeout_seconds,
                    max_retries=self.default_retries,
                    cooldown_seconds=self.default_cooldown,
                    failure_threshold=self.default_failure_threshold,
                    paid=True,
                )
            )

        # ── Cerebras: CAPTCHA solver pipeline ONLY (independent flag) ─────
        # Cerebras es una función interna de bajo riesgo (extracción de texto en
        # el resolvedor de CAPTCHA, no contenido publicado). Se mantiene activo
        # por defecto con su propio flag (CEREBRAS_ENABLED, distinto del de
        # contenido) y se marca explicit_only=True: NUNCA entra al fallback
        # automático de generación de contenido; solo se usa cuando un caller
        # pide tier="cerebras" explícitamente (challenge_solver.py).
        _cerebras_enabled = os.getenv("CEREBRAS_ENABLED", "true").strip().lower() in ("1", "true", "yes")
        if creds.cerebras_api_key and _cerebras_enabled:
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

        # ── Groq: DESACTIVADO permanentemente (GROQ_ENABLED, default false) ──
        # Agotó el TPD (tokens-per-day) en mayo 2026 dejando Fases B y C sin
        # fallback. No reactivar salvo emergencia explícita.
        _groq_enabled = os.getenv("GROQ_ENABLED", "false").strip().lower() in ("1", "true", "yes")
        if creds.groq_api_key and _groq_enabled:
            self.providers.append(
                ProviderConfig(
                    name="groq",
                    url=creds.groq_url,
                    model=creds.groq_model,
                    api_key=creds.groq_api_key,
                    timeout=creds.groq_timeout,
                    max_retries=self.default_retries,
                    cooldown_seconds=self.default_cooldown,
                    failure_threshold=self.default_failure_threshold,
                )
            )

        # ── Local Ollama fallbacks (localhost:11434) ───────────────────────
        # FAIL-FAST (Fix 1): Production has no Ollama installed. Waiting on a dead
        # localhost:11434 (even for a few seconds) degrades every cascade fallout.
        # These providers — including the former last-resort `tier_local` — are now
        # DISABLED by default and only registered when OLLAMA_ENABLED is truthy.
        # With them off, the active flow is: tier_premium → tier_fallback → Degraded Mode,
        # and _enter_degraded_mode() fires immediately after tier_fallback fails,
        # without ever attempting a localhost connection.
        _ollama_enabled = os.getenv("OLLAMA_ENABLED", "false").strip().lower() in ("1", "true", "yes")
        if _ollama_enabled:
            self.providers.append(
                ProviderConfig(
                    name="ollama_local",
                    url=creds.ollama_url,
                    model=creds.ollama_model,
                    api_key="",
                    timeout=creds.ollama_timeout,
                    max_retries=self.default_retries,
                    cooldown_seconds=self.default_cooldown,
                    failure_threshold=self.default_failure_threshold,
                )
            )

            if creds.ollama_cloud_model:
                self.providers.append(
                    ProviderConfig(
                        name="ollama_cloud",
                        url=creds.ollama_url,
                        model=creds.ollama_cloud_model,
                        api_key="",
                        timeout=creds.ollama_cloud_timeout,
                        max_retries=self.default_retries,
                        cooldown_seconds=self.default_cooldown,
                        failure_threshold=self.default_failure_threshold,
                    )
                )

            # ── Native Ollama endpoint fallback (api/generate) ──────
            _local_llm_url = os.getenv("LOCAL_LLM_URL", "http://localhost:11434")
            _local_llm_model = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:3b")
            self.providers.append(
                ProviderConfig(
                    name="ollama_native",
                    url=f"{_local_llm_url}/api/generate",
                    model=_local_llm_model,
                    api_key="",
                    timeout=120,
                    max_retries=2,
                    cooldown_seconds=60,
                    failure_threshold=3,
                )
            )

    def _init_circuit_breakers(self) -> None:
        for p in self.providers:
            self.circuit_breakers[p.name] = CircuitBreaker(
                name=f"model_cascade.{p.name}",
                failure_threshold=p.failure_threshold,
                recovery_timeout=p.cooldown_seconds,
            )

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
        provider_name = self.TIER_MAPPING.get(tier, "ollama_local")
        preferred = next((p for p in self.providers if p.name == provider_name and p.enabled), None)
        # explicit_only providers (e.g. cerebras for CAPTCHA) are excluded from the
        # automatic fallback chain; they only run when their tier is requested
        # directly (in which case `preferred` points at them and leads the order).
        fallback_pool = [
            p for p in self.providers
            if p.name != provider_name and not p.explicit_only
        ]
        # Gratis antes que pago en el fallback automatico (22/7/2026): si el
        # tier pedido falla (p.ej. tier_fallback/DeepSeek sin credito), se
        # prueban los proveedores gratis (Gemini/OpenRouter/Cloudflare/Cerebras)
        # antes de degradar a uno pago (Anthropic). Orden relativo dentro de
        # cada grupo se preserva (orden de registro).
        fallback_pool = (
            [p for p in fallback_pool if not p.paid]
            + [p for p in fallback_pool if p.paid]
        )
        if preferred:
            ordered_providers = [preferred] + fallback_pool
        else:
            ordered_providers = [p for p in self.providers if p.enabled and not p.explicit_only]
            # Visibilidad: el tier solicitado no resolvio a un provider
            # registrado/habilitado (p.ej. tier="default" -> ollama_local con
            # OLLAMA_ENABLED=false). Se cae al primer provider disponible, que
            # puede ser mas caro de lo intencionado (p.ej. tier_premium/Anthropic).
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
                    # A successful generation means the cascade recovered.
                    if self.degraded_mode:
                        logger.info("✅ ModelCascade: recuperado de modo degradado (provider='%s')", provider.name)
                        self._clear_degraded_state()
                    self.degraded_mode = False
                    # Warn if we fell back to a different provider than requested
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
                    self._append_telemetry_jsonl({
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "caller": caller,
                        "provider": provider.name,
                        "tier": tier,
                        "latency_ms": latency_ms,
                        "success": True,
                        "error": None,
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
                })
                continue

        # ── Cascade fully exhausted. With local Ollama fallbacks disabled
        #    (Fix 1), the last real provider is tier_fallback; once it fails we
        #    enter Degraded Mode immediately, without touching localhost:11434. ──
        if any(p.name.startswith("tier_") for p in self.providers):
            self._enter_degraded_mode(attempted, last_error)
        raise RuntimeError(
            f"🔴 Todos los proveedores fallaron. Intentados: {attempted}. Último error: {last_error}"
        )

    def _enter_degraded_mode(self, attempted: List[str], last_error: Optional[Exception]) -> None:
        """Cascade exhausted (tier_premium → tier_fallback all down): stop generation and alert.

        Re-alerts on Telegram every DEGRADED_ALERT_COOLDOWN_MINUTES while the
        outage persists (not just once), so a sustained failure keeps reminding
        the operator. State is persisted to data/degraded_mode_state.json so the
        cooldown survives process restarts within one episode. The degraded flag
        is cleared on the next successful generation. No local (Ollama) connection
        is attempted — production has no Ollama, so we fail fast.
        """
        self.degraded_mode = True
        logger.critical(
            "🛑 ModelCascade: CASCADA LLM AGOTADA (tier_premium → tier_fallback). "
            "Modo degradado ACTIVO — generación de contenido detenida. "
            "Intentados: %s. Último error: %s",
            attempted, last_error,
        )

        now = time.time()
        state = self._load_degraded_state()
        was_degraded = bool(state.get("is_degraded"))
        since_ts = float(state.get("since_ts") or now) if was_degraded else now
        last_alert_ts = float(state.get("last_alert_ts") or 0.0) if was_degraded else 0.0
        cooldown_seconds = self._degraded_alert_cooldown_minutes() * 60

        # Persist degraded state immediately (independent of whether we alert now).
        self._save_degraded_state({
            "is_degraded": True,
            "since_ts": since_ts,
            "last_alert_ts": last_alert_ts,
        })

        # Decide whether to (re-)alert: first entry, or cooldown elapsed.
        is_first_alert = not was_degraded or last_alert_ts <= 0.0
        due_for_realert = (now - last_alert_ts) >= cooldown_seconds
        if not (is_first_alert or due_for_realert):
            return

        if is_first_alert:
            message = "Cascada LLM agotada. Revisar conectividad y saldo de APIs."
        else:
            elapsed_min = int((now - since_ts) / 60)
            message = (
                f"Cascada LLM SIGUE agotada tras {elapsed_min} min. "
                "Revisar conectividad y saldo de APIs."
            )

        try:
            telegram = self._get_telegram_client()
            if telegram is not None:
                telegram.send_alert("Modo degradado", message, level="ERROR")
                # Only advance last_alert_ts if the send actually succeeded, so a
                # failed send retries on the next cycle instead of waiting a full
                # cooldown window.
                self._save_degraded_state({
                    "is_degraded": True,
                    "since_ts": since_ts,
                    "last_alert_ts": now,
                })
        except Exception as e:
            logger.warning("ModelCascade: no se pudo enviar alerta de modo degradado por Telegram: %s", e)

    # ── Degraded-mode state persistence (re-alert cooldown) ───────────

    @staticmethod
    def _degraded_alert_cooldown_minutes() -> float:
        try:
            return float(os.getenv("DEGRADED_ALERT_COOLDOWN_MINUTES", str(_DEGRADED_ALERT_COOLDOWN_DEFAULT_MINUTES)))
        except (ValueError, TypeError):
            return float(_DEGRADED_ALERT_COOLDOWN_DEFAULT_MINUTES)

    def _load_degraded_state(self) -> Dict[str, Any]:
        try:
            with open(_DEGRADED_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError):
            return {}
        except Exception as e:
            logger.debug("ModelCascade: could not read degraded state: %s", e)
        return {}

    def _save_degraded_state(self, state: Dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(_DEGRADED_STATE_FILE) or ".", exist_ok=True)
            with open(_DEGRADED_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
        except Exception as e:
            logger.warning("ModelCascade: failed to persist degraded state: %s", e)

    def _clear_degraded_state(self) -> None:
        self._save_degraded_state({"is_degraded": False, "since_ts": None, "last_alert_ts": None})

    def _get_telegram_client(self):
        """Resolve a Telegram client from the owning agent or from env credentials."""
        client = getattr(self.agent, "telegram_client", None)
        if client is not None:
            return client
        try:
            from services.telegram_client import create_telegram_client
            return create_telegram_client()
        except Exception as e:
            logger.debug("ModelCascade: create_telegram_client failed: %s", e)
            return None

    def _build_messages(self, prompt: str, system_prompt: Optional[str]) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def _call_with_retries(
        self,
        provider: ProviderConfig,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        last_error: Optional[Exception] = None

        for attempt in range(provider.max_retries + 1):
            try:
                return await asyncio.to_thread(
                    self._call_provider_once,
                    provider,
                    messages,
                    max_tokens,
                    temperature,
                )
            except Exception as e:
                last_error = e

                if not self._should_retry(e):
                    logger.warning(
                        f"❌ Error no reintentable en '{provider.name}' ({provider.model}): {e}"
                    )
                    raise

                if attempt >= provider.max_retries:
                    logger.warning(
                        f"❌ Retries agotados en '{provider.name}' ({provider.model}). "
                        f"Intentos: {provider.max_retries + 1}"
                    )
                    raise

                backoff_seconds = 2 ** attempt
                logger.warning(
                    f"⏳ Retry {attempt + 1}/{provider.max_retries} para '{provider.name}' "
                    f"en {backoff_seconds}s por error: {e}"
                )
                await asyncio.sleep(backoff_seconds)

        raise RuntimeError(f"Fallo inesperado sin respuesta tras retries: {last_error}")

    def _call_provider_once(
        self,
        provider: ProviderConfig,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if provider.api_key:
            headers["Authorization"] = f"Bearer {provider.api_key}"
        headers.update(provider.extra_headers or {})

        # ── Anthropic Messages API format ────────────────────────────
        if provider.kind == "anthropic":
            return self._call_anthropic(provider, messages, max_tokens, temperature)

        # ── Native Ollama /api/generate format ───────────────────────
        if provider.name == "ollama_native":
            system_text = ""
            user_text = ""
            for m in messages:
                if m["role"] == "system":
                    system_text = m["content"]
                elif m["role"] == "user":
                    user_text = m["content"]
            payload = {
                "model": provider.model,
                "prompt": user_text,
                "system": system_text,
                "stream": False,
                "options": {
                    "temperature": float(temperature),
                    "num_predict": int(max_tokens),
                },
            }
            response = requests.post(
                provider.url,
                headers=headers,
                json=payload,
                timeout=provider.timeout,
            )
            try:
                response.raise_for_status()
            except requests.HTTPError as e:
                status_code = getattr(response, "status_code", None)
                body_preview = ""
                try:
                    body_preview = response.text[:500]
                except Exception:
                    pass
                raise RuntimeError(
                    f"HTTP {status_code} desde {provider.name}:{provider.model} - {body_preview}"
                ) from e
            data = response.json()
            text = data.get("response", "")
            if not text:
                raise RuntimeError(f"Respuesta vacia desde {provider.name}:{provider.model}")
            return text

        # ── Standard OpenAI-compatible format ────────────────────────
        payload = {
            "model": provider.model,
            "messages": messages,
            "stream": False,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }

        # DeepSeek V4 Pro is a reasoning model: by default it spends the token
        # budget on `reasoning_content` and may return an empty `content`
        # (finish_reason="length"). For editorial content generation we want the
        # answer directly, so disable thinking. Verified empirically that only
        # {"thinking": {"type": "disabled"}} at top level takes effect (the
        # OpenAI-SDK `extra_body`/`reasoning` variants are ignored by this
        # raw-HTTP path). Scoped to DeepSeek so other OpenAI-compatible providers
        # (cerebras, groq, ollama) are untouched.
        _is_deepseek = provider.name == "tier_fallback" or "deepseek" in (provider.url or "").lower() or "deepseek" in (provider.model or "").lower()
        if _is_deepseek:
            payload["thinking"] = {"type": "disabled"}
            # Safety margin for editorial prose (secondary to disabling thinking).
            _min_fallback_tokens = int(os.getenv("DEEPSEEK_MIN_MAX_TOKENS", "2048"))
            if int(max_tokens) < _min_fallback_tokens:
                payload["max_tokens"] = _min_fallback_tokens

        response = requests.post(
            provider.url,
            headers=headers,
            json=payload,
            timeout=provider.timeout,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            status_code = getattr(response, "status_code", None)
            body_preview = ""
            try:
                body_preview = response.text[:500]
            except Exception:
                pass
            raise RuntimeError(
                f"HTTP {status_code} desde {provider.name}:{provider.model} - {body_preview}"
            ) from e

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Respuesta sin choices desde {provider.name}:{provider.model}")

        message = choices[0].get("message") or {}
        content = message.get("content")

        if isinstance(content, str) and content.strip():
            return content

        if isinstance(content, list):
            text_parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            joined = "".join(text_parts).strip()
            if joined:
                return joined

        raise RuntimeError(f"Respuesta sin content utilizable desde {provider.name}:{provider.model}")

    def _call_anthropic(
        self,
        provider: ProviderConfig,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Call Anthropic's Messages API and map the response to plain text.

        Anthropic requires the system prompt as a top-level `system` field (not a
        message role) and only accepts user/assistant roles in `messages`.
        Prefers the official SDK when installed; otherwise uses the HTTP API via
        `requests` so no new hard dependency is forced on test/dev environments.
        The returned text is identical in shape to the OpenAI-compatible path,
        keeping the cascade interface intact.

        A hard spend guard estimates cumulative cost (input/output tokens priced
        for claude-sonnet-5) persisted to data/anthropic_spend_tracker.json. Once
        ANTHROPIC_SPEND_LIMIT_USD (default 4.50) is exceeded, this raises a
        ret/non-retryable RuntimeError so the cascade falls back to the next
        provider instead of crashing the cycle.
        """
        # ── Hard spend guard: bail out to the next provider if over budget ──
        spent = self._get_anthropic_spend()
        limit = self._anthropic_spend_limit()
        if spent >= limit:
            logger.warning(
                "💸 ModelCascade: límite de gasto Anthropic alcanzado "
                "($%.4f >= $%.2f). Saltando '%s' y usando siguiente proveedor.",
                spent, limit, provider.name,
            )
            raise RuntimeError(
                f"Anthropic spend limit reached (${spent:.4f} >= ${limit:.2f}) "
                f"desde {provider.name}:{provider.model} - fallback to next provider"
            )

        system_text = ""
        chat_messages: List[Dict[str, str]] = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                system_text = (system_text + "\n" + m["content"]).strip() if system_text else m["content"]
            elif role in ("user", "assistant"):
                chat_messages.append({"role": role, "content": m["content"]})
        if not chat_messages:
            chat_messages = [{"role": "user", "content": system_text or ""}]

        # ── Preferred path: official Anthropic SDK ──
        try:
            import anthropic  # type: ignore
        except ImportError:
            anthropic = None  # type: ignore

        if anthropic is not None:
            try:
                client = anthropic.Anthropic(api_key=provider.api_key, timeout=provider.timeout)
                # NOTE: `temperature` is deliberately NOT sent. claude-sonnet-5 rejects
                # it (HTTP 400 "temperature is deprecated for this model"); omitting the
                # field is equivalent to the model default and keeps the call valid.
                # This omission is Anthropic-specific — the OpenAI-compatible path
                # (DeepSeek et al.) still sends temperature normally.
                resp = client.messages.create(
                    model=provider.model,
                    max_tokens=int(max_tokens),
                    system=system_text or None,
                    messages=chat_messages,
                )
                self._record_anthropic_spend_from_response(resp)
                return self._extract_anthropic_text(resp, provider)
            except Exception as e:
                # Normalize SDK errors into the same string format the cascade
                # classifier understands (status codes, rate limit, etc.).
                status = getattr(getattr(e, "response", None), "status_code", None) or getattr(e, "status_code", None)
                if status:
                    raise RuntimeError(f"HTTP {status} desde {provider.name}:{provider.model} - {e}") from e
                raise

        # ── Fallback path: raw HTTP to the Messages API ──
        headers = {
            "Content-Type": "application/json",
            "x-api-key": provider.api_key,
            "anthropic-version": "2023-06-01",
        }
        headers.update(provider.extra_headers or {})
        # NOTE: `temperature` is deliberately omitted (see SDK path above):
        # claude-sonnet-5 returns HTTP 400 if it is present. Omission == default.
        payload: Dict[str, Any] = {
            "model": provider.model,
            "max_tokens": int(max_tokens),
            "messages": chat_messages,
        }
        if system_text:
            payload["system"] = system_text

        response = requests.post(
            provider.url,
            headers=headers,
            json=payload,
            timeout=provider.timeout,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            status_code = getattr(response, "status_code", None)
            body_preview = ""
            try:
                body_preview = response.text[:500]
            except Exception:
                pass
            raise RuntimeError(
                f"HTTP {status_code} desde {provider.name}:{provider.model} - {body_preview}"
            ) from e

        data = response.json()
        self._record_anthropic_spend_from_response(data)
        return self._extract_anthropic_text(data, provider)

    # ── Anthropic spend tracking (simple, file-persisted) ─────────────

    @staticmethod
    def _anthropic_spend_limit() -> float:
        try:
            return float(os.getenv("ANTHROPIC_SPEND_LIMIT_USD", str(_ANTHROPIC_SPEND_LIMIT_DEFAULT)))
        except (ValueError, TypeError):
            return _ANTHROPIC_SPEND_LIMIT_DEFAULT

    def _get_anthropic_spend(self) -> float:
        """Return cumulative estimated Anthropic spend in USD (0.0 if none)."""
        try:
            with open(_ANTHROPIC_SPEND_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return float(data.get("total_usd", 0.0))
        except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError):
            return 0.0
        except Exception as e:
            logger.debug("ModelCascade: could not read Anthropic spend tracker: %s", e)
            return 0.0

    @staticmethod
    def _extract_anthropic_usage(resp: Any) -> tuple:
        """Return (input_tokens, output_tokens) from an SDK object or dict."""
        usage = resp.get("usage") if isinstance(resp, dict) else getattr(resp, "usage", None)
        if usage is None:
            return 0, 0
        if isinstance(usage, dict):
            return int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)
        return int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)

    def _record_anthropic_spend_from_response(self, resp: Any) -> None:
        """Estimate the cost of one Anthropic response and persist the running total."""
        try:
            input_tokens, output_tokens = self._extract_anthropic_usage(resp)
            if not input_tokens and not output_tokens:
                return
            cost = (
                input_tokens * _ANTHROPIC_INPUT_PRICE_PER_1M / 1_000_000
                + output_tokens * _ANTHROPIC_OUTPUT_PRICE_PER_1M / 1_000_000
            )
            total = self._get_anthropic_spend() + cost
            os.makedirs(os.path.dirname(_ANTHROPIC_SPEND_FILE) or ".", exist_ok=True)
            with open(_ANTHROPIC_SPEND_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "total_usd": round(total, 6),
                        "last_updated": datetime.now(timezone.utc).isoformat(),
                    },
                    f,
                    ensure_ascii=False,
                )
            logger.debug(
                "ModelCascade: Anthropic spend +$%.6f (in=%d out=%d) → total $%.4f",
                cost, input_tokens, output_tokens, total,
            )
        except Exception as e:
            logger.warning("ModelCascade: failed to record Anthropic spend: %s", e)

    @staticmethod
    def _extract_anthropic_text(resp: Any, provider: ProviderConfig) -> str:
        """Map an Anthropic Messages response (SDK object or dict) to plain text."""
        content = resp.get("content") if isinstance(resp, dict) else getattr(resp, "content", None)
        text_parts: List[str] = []
        for block in content or []:
            if isinstance(block, dict):
                if block.get("type") == "text" and block.get("text"):
                    text_parts.append(block["text"])
            else:
                # SDK content block object
                if getattr(block, "type", None) == "text" and getattr(block, "text", None):
                    text_parts.append(block.text)
        joined = "".join(text_parts).strip()
        if joined:
            return joined
        # ── Diagnostic logging for empty content ──
        model = getattr(resp, "model", None) or (resp.get("model") if isinstance(resp, dict) else "unknown")
        usage = getattr(resp, "usage", None) or (resp.get("usage") if isinstance(resp, dict) else None)
        stop_reason = (
            getattr(resp, "stop_reason", None)
            or (resp.get("stop_reason") if isinstance(resp, dict) else None)
        )
        content_types = []
        for block in (content or []):
            if isinstance(block, dict):
                content_types.append(block.get("type", "?"))
            else:
                content_types.append(getattr(block, "type", "?"))
        logger.warning(
            "⚠️ Anthropic empty response: model=%s stop_reason=%s "
            "usage=%s content_types=%s",
            model, stop_reason, usage, content_types,
        )
        raise RuntimeError(f"Respuesta sin content utilizable desde {provider.name}:{provider.model}")

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
            "timeout",
            "timed out",
            "connection aborted",
            "connection reset",
            "temporarily unavailable",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
        ]
        no_retry_markers = [
            "http 400",
            "http 401",
            "http 403",
            "respuesta sin choices",
            "respuesta sin content utilizable",
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
        # Reset completo (comportamiento original: reinicia circuito tras éxito)
        self._get_cb(provider).reset()

    def _record_failure(self, provider: ProviderConfig, error: Exception) -> None:
        """Registra fallo con comportamiento diferenciado por tipo de error HTTP."""
        cb = self._get_cb(provider)
        error_type = self._classify_http_error(error)

        # Rate limit (429): Abrir circuit breaker por 1 hora para evitar latencia
        if error_type == "rate_limit":
            logger.warning("⏳ Rate limit en '%s' - circuito abierto por 1 hora", provider.name)
            cb.force_open(reason=str(error), duration_seconds=3600)
            return

        # Error de cliente (401/403/400): abrir circuito INMEDIATAMENTE
        if error_type == "client":
            logger.error("🚫 Error de cliente en '%s': %s - circuito abierto 5 min", provider.name, error)
            cb.force_open(reason=str(error), duration_seconds=300)
            return

        # Errores de servidor/red/unknown: conteo normal
        cb.record_failure()
        logger.warning(
            "⚠️  Fallo en '%s' (%d/%d): %s",
            provider.name, cb.get_stats()["failure_count"],
            provider.failure_threshold, error,
        )

    def _update_health(self, provider: ProviderConfig, success: bool) -> None:
        if provider.name not in self._health_histories:
            self._health_histories[provider.name] = deque(maxlen=10)
        self._health_histories[provider.name].append(success)

    def _get_health_score(self, provider: ProviderConfig) -> float:
        history = self._health_histories.get(provider.name)
        if not history:
            return 0.0
        return sum(history) / len(history)

    def _append_telemetry_jsonl(self, record: dict) -> None:
        try:
            from utils.jsonl_rotation import append_jsonl
            append_jsonl(record, self._telemetry_file, max_lines=1000)
        except Exception as e:
            logger.warning(f"ModelCascade: failed to write telemetry JSONL: {e}")

    def get_provider_health(self) -> Dict[str, float]:
        """Returns {provider_name: health_score} for all providers called this session."""
        result: Dict[str, float] = {}
        for name, history in self._health_histories.items():
            result[name] = sum(history) / len(history) if history else 0.0
        return result
