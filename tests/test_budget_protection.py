# -*- coding: utf-8 -*-
"""Tests de proteccion presupuestal de la cascada (25/08/2026).

Hallazgo: durante un flap free (zen 80 fallos + openrouter 429s), las
replies/classify escalaban a DeepSeek pago y quemaron el cap diario en
medio dia -> cascada entera bloqueada -> rafaga 'fuera de rotacion'.
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.model_cascade import ModelCascade
from config.credentials import Credentials


def _add(cascade, name, paid=False):
    from services.model_cascade import ProviderConfig
    from utils.resilience import CircuitBreaker
    cascade.providers.append(ProviderConfig(name=name, url="http://x", model="m", paid=paid))
    cascade.circuit_breakers[name] = CircuitBreaker(name=f"model_cascade.{name}", failure_threshold=3, recovery_timeout=60)


def _cascade():
    c = MagicMock(spec=Credentials)
    c.ollama_url = "http://x"; c.ollama_model = "m"; c.ollama_timeout = 5
    c.ollama_cloud_model = None; c.tier_opus = None; c.tier_sonnet = None
    c.tier_haiku = None; c.tier_openrouter = None; c.cerebras_api_key = ""
    c.groq_api_key = ""
    with patch("services.model_cascade.Credentials.from_env", return_value=c):
        mc = ModelCascade()
    mc.providers = []
    mc.circuit_breakers = {}
    mc._append_telemetry_jsonl = lambda r: None
    return mc


class TestNoPaidOverflowOnLowValueTiers:

    @pytest.mark.asyncio
    async def test_quality_still_reaches_paid(self):
        """tier=quality (watchlist/V4 Pro): el pago SI es el preferred."""
        mc = _cascade()
        _add(mc, "tier_fallback", paid=True)
        attempted = []

        async def call(provider, messages, max_tokens, temperature):
            attempted.append(provider.name)
            return "ok"

        with patch.object(mc, "_is_circuit_open", return_value=False), \
             patch.object(mc, "_call_with_retries", side_effect=call):
            result = await mc.generate(prompt="x", tier="quality")
        assert result == "ok"
        assert attempted == ["tier_fallback"]

    @pytest.mark.asyncio
    async def test_tier_flash_allowed_as_last_resort(self):
        """V4 Flash (barato) queda permitido como ultimo recurso de flash."""
        mc = _cascade()
        _add(mc, "openrouter")
        _add(mc, "tier_flash", paid=True)
        attempted = []

        async def call(provider, messages, max_tokens, temperature):
            attempted.append(provider.name)
            if provider.name == "openrouter":
                raise RuntimeError("fail")
            return "ok"

        with patch.object(mc, "_is_circuit_open", return_value=False), \
             patch.object(mc, "_call_with_retries", side_effect=call):
            result = await mc.generate(prompt="x", tier="flash")
        assert result == "ok"
        assert attempted[-1] == "tier_flash"


class TestAnthropicZeroLimitSkip:

    def test_zero_limit_never_registers_anthropic(self):
        creds = MagicMock(spec=Credentials)
        creds.ollama_url = "http://x"; creds.ollama_model = "m"; creds.ollama_timeout = 5
        creds.ollama_cloud_model = None; creds.tier_opus = None; creds.tier_sonnet = None
        creds.tier_haiku = None; creds.tier_openrouter = None; creds.tier_cloudflare = None
        creds.cerebras_api_key = ""; creds.groq_api_key = ""
        creds.anthropic_api_key = "sk-ant-present"
        creds.anthropic_url = "https://api.anthropic.com/v1/messages"
        creds.anthropic_model = "claude-sonnet-5"
        creds.anthropic_timeout = 120
        creds.deepseek_api_key = ""
        env = {
            "MODEL_CASCADE_PREFER_FREE": "",
            "ANTHROPIC_SPEND_LIMIT_USD": "0.00",
            "ZEN_ENABLED": "", "CEREBRAS_ENABLED": "false",
            "GEMINI_ENABLED": "false", "OPENROUTER_ENABLED": "false",
            "CLOUDFLARE_ENABLED": "false",
        }
        with patch.dict(os.environ, env):
            mc = ModelCascade(credentials=creds)
        names = [p.name for p in mc.providers]
        assert "tier_premium" not in names, "limit=0 debe impedir registro Anthropic"
        assert "tier_premium_opus" not in names
