"""Tests for the AGENT_FLASH_ONLY kill-switch (06/08/2026).

Con AGENT_FLASH_ONLY=1 toda generación pagada (premium / premium_opus /
opus / sonnet / fallback / haiku) se fuerza a 'flash' — desde ETAPA 1
(20/08/2026) mapeado a cloudflare llama-3.3-70b (working-free, el
proveedor de contenido verificado) —, protegiendo el saldo Anthropic
(reservado para el asesor). Reversible quitando el env. Sin el env, el
comportamiento previo se conserva.
"""

import pytest

from unittest.mock import MagicMock, patch

from services.model_cascade import ModelCascade, ProviderConfig
from config.credentials import Credentials
from utils.resilience import CircuitBreaker


def _add_provider(cascade, name, model="test-model"):
    p = ProviderConfig(name=name, url="http://test.local", model=model)
    cascade.providers.append(p)
    cascade.circuit_breakers[name] = CircuitBreaker(
        name=f"model_cascade.{name}",
        failure_threshold=3,
        recovery_timeout=60,
    )


@pytest.fixture
def mock_credentials():
    c = MagicMock(spec=Credentials)
    c.ollama_url = "http://localhost:11434/v1"
    c.ollama_model = "qwen2.5:1.5b"
    c.ollama_timeout = 60
    c.ollama_cloud_model = None
    c.tier_opus = None
    c.tier_sonnet = None
    c.tier_haiku = None
    c.tier_openrouter = None
    c.cerebras_api_key = ""
    return c


@pytest.fixture
def cascade(mock_credentials):
    with patch("services.model_cascade.Credentials.from_env", return_value=mock_credentials):
        c = ModelCascade()
    c.providers = []
    c.circuit_breakers = {}
    c._append_telemetry_jsonl = lambda record: None
    return c


@pytest.mark.asyncio
async def test_flash_only_forces_paid_tiers_to_working_free(cascade, monkeypatch):
    """AGENT_FLASH_ONLY=1: premium/premium_opus/fallback sirven por cloudflare
    (working-free, el target de tier='flash' desde ETAPA 1)."""
    monkeypatch.setenv("AGENT_FLASH_ONLY", "1")
    _add_provider(cascade, "tier_premium", model="claude-sonnet-5")
    _add_provider(cascade, "tier_premium_opus", model="claude-opus-4-8")
    _add_provider(cascade, "tier_fallback", model="deepseek-v4-pro")
    _add_provider(cascade, "cloudflare", model="llama-3.3-70b")

    captured = []

    async def _fake_call(provider, messages, max_tokens, temperature):
        captured.append(provider.name)
        return "ok"

    with patch.object(cascade, "_call_with_retries", side_effect=_fake_call):
        for tier in ("premium_opus", "premium", "fallback"):
            result = await cascade.generate(prompt="hello", tier=tier)
            assert result == "ok"

    assert captured == ["cloudflare", "cloudflare", "cloudflare"], \
        f"FLASH-ONLY debió servir todos por cloudflare, capturado: {captured}"


@pytest.mark.asyncio
async def test_flash_only_resolves_flash_to_working_free(cascade, monkeypatch):
    """AGENT_FLASH_ONLY=1: tier='flash' resuelve a cloudflare (working-free) —
    sin doble log/rewrite."""
    monkeypatch.setenv("AGENT_FLASH_ONLY", "1")
    _add_provider(cascade, "tier_flash", model="deepseek-v4-flash")
    _add_provider(cascade, "cloudflare", model="llama-3.3-70b")

    captured = []

    async def _fake_call(provider, messages, max_tokens, temperature):
        captured.append(provider.name)
        return "ok"

    with patch.object(cascade, "_call_with_retries", side_effect=_fake_call):
        result = await cascade.generate(prompt="hello", tier="flash")
    assert result == "ok"
    assert captured == ["cloudflare"]


@pytest.mark.asyncio
async def test_without_env_premium_resolves_to_tier_premium(cascade, monkeypatch):
    """Sin AGENT_FLASH_ONLY, tier='premium' sigue resolviendo a tier_premium."""
    monkeypatch.delenv("AGENT_FLASH_ONLY", raising=False)
    _add_provider(cascade, "tier_premium", model="claude-sonnet-5")
    _add_provider(cascade, "tier_flash", model="deepseek-v4-flash")

    captured = []

    async def _fake_call(provider, messages, max_tokens, temperature):
        captured.append(provider.name)
        return "ok"

    with patch.object(cascade, "_call_with_retries", side_effect=_fake_call):
        result = await cascade.generate(prompt="hello", tier="premium")
    assert result == "ok"
    assert captured == ["tier_premium"], \
        f"Sin env, premium debe ir a tier_premium, capturado: {captured}"
