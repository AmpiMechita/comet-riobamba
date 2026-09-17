# -*- coding: utf-8 -*-
"""Tests del segundo modelo :free con bucket propio (25/08/2026).

Problema: nemotron-super como primario UNICO recibia classify+contenido y
sumaba 19 rate-limits (429) en un dia -> circuitos abiertos 1h -> ciclos de
26+ min. Solucion: openrouter_2 (lightning) DEDICADO a classify.
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.model_cascade import ModelCascade
from config.credentials import Credentials


def _creds():
    c = MagicMock(spec=Credentials)
    c.ollama_url = "http://x"; c.ollama_model = "m"; c.ollama_timeout = 5
    c.ollama_cloud_model = None; c.tier_opus = None; c.tier_sonnet = None
    c.tier_haiku = None; c.tier_cloudflare = None
    c.cerebras_api_key = ""; c.groq_api_key = ""
    c.anthropic_api_key = ""
    c.deepseek_api_key = ""
    or_tier = MagicMock()
    or_tier.url = "https://openrouter.ai/api/v1/chat/completions"
    or_tier.api_key = "sk-or-test"
    or_tier.timeout_seconds = 60
    c.tier_openrouter = or_tier
    return c


class TestOpenRouter2:

    @pytest.mark.asyncio
    async def test_pool_order_super_then_lightning_then_zen_cloudflare(self):
        mc = _cascade()
        _add(mc, "openrouter")
        _add(mc, "openrouter_2")
        _add(mc, "zen")
        _add(mc, "cloudflare")
        attempted = []

        async def call(provider, messages, max_tokens, temperature):
            attempted.append(provider.name)
            raise RuntimeError("fail")

        with patch.object(mc, "_is_circuit_open", return_value=False), \
             patch.object(mc, "_call_with_retries", side_effect=call):
            with pytest.raises(RuntimeError, match="Todos los proveedores fallaron"):
                await mc.generate(prompt="x", tier="flash")
        assert attempted == ["openrouter", "openrouter_2", "zen", "cloudflare"], attempted

def _cascade():
    with patch("services.model_cascade.Credentials.from_env", return_value=_creds()):
        mc = ModelCascade()
    mc.providers = []
    mc.circuit_breakers = {}
    mc._append_telemetry_jsonl = lambda r: None
    return mc


def _add(cascade, name):
    from services.model_cascade import ProviderConfig
    from utils.resilience import CircuitBreaker
    cascade.providers.append(ProviderConfig(name=name, url="http://x", model="m"))
    cascade.circuit_breakers[name] = CircuitBreaker(
        name=f"model_cascade.{name}", failure_threshold=3, recovery_timeout=60)
