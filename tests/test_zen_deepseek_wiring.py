# -*- coding: utf-8 -*-
"""Tests del cableado DeepSeek-via-Zen (24/08/2026).

Escenario: operador financia OpenCode Zen (no DeepSeek directo, saldo
negativo) y los tiers editoriales pagos (tier_fallback=V4 Pro,
tier_flash=V4 Flash) se sirven por el endpoint Zen con la MISMA key que los
modelos :free. Gated por ZEN_SERVE_DEEPSEEK + PREFER_FREE.
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.model_cascade import ModelCascade
from config.credentials import Credentials

ZEN_URL = "https://opencode.ai/zen/v1/chat/completions"


def _creds():
    c = MagicMock(spec=Credentials)
    c.ollama_url = "http://localhost:11434/v1"
    c.ollama_model = "qwen2.5:1.5b"
    c.ollama_timeout = 60
    c.ollama_cloud_model = None
    c.tier_opus = None
    c.tier_sonnet = None
    c.tier_haiku = None
    c.tier_openrouter = None
    c.tier_cloudflare = None
    c.cerebras_api_key = ""
    c.groq_api_key = ""
    c.anthropic_api_key = ""
    c.deepseek_api_key = "sk-ds-broke"          # saldo negativo, no importa
    c.deepseek_url = "https://api.deepseek.com/v1/chat/completions"
    c.deepseek_model = "deepseek-v4-pro"
    c.deepseek_timeout = 90
    return c


def _cascade(env_overrides):
    env = {
        "ZEN_ENABLED": "true",
        "MODEL_TIER_ZEN_API_KEY": "sk-zen-test",
        "ZEN_SERVE_DEEPSEEK": "true",
        "MODEL_CASCADE_PREFER_FREE": "",   # ausente -> falsy
        "CEREBRAS_ENABLED": "false",
        "GEMINI_ENABLED": "false",
        "OPENROUTER_ENABLED": "false",
        "CLOUDFLARE_ENABLED": "false",
    }
    env.update(env_overrides)
    with patch.dict(os.environ, env, clear=False):
        return ModelCascade(credentials=_creds())


class TestZenDeepSeekWiring:

    def test_flag_off_falls_back_to_direct_deepseek(self):
        mc = _cascade({"ZEN_SERVE_DEEPSEEK": "false"})
        fb = [p for p in mc.providers if p.name == "tier_fallback"]
        assert len(fb) == 1
        assert fb[0].url.startswith("https://api.deepseek.com")
        assert fb[0].api_key == "sk-ds-broke"


class TestZenCostEstimation:

    def test_free_zen_models_cost_zero(self):
        from services.model_cascade import _estimate_cost_usd
        # x-preview-f-free via proveedor 'zen' (sin entrada en tabla) -> 0
        assert _estimate_cost_usd("zen", 100000, 50000) == 0.0

    def test_paid_via_zen_priced_by_provider_name(self, monkeypatch):
        from services.model_cascade import _estimate_cost_usd
        # Forzar hora PICO para que el calculo no dependa de la hora UTC.
        # (Antes asumia peak, fallaba en horas valle por el descuento 50%).
        monkeypatch.setattr(
            "services.model_cascade._is_deepseek_peak_hour",
            lambda: True,
        )
        cost = _estimate_cost_usd("tier_fallback", 1_000_000, 1_000_000)
        assert cost == pytest.approx(1.32 + 3.96)
        assert cost == pytest.approx(1.32 + 3.96)
