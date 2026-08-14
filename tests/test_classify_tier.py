# -*- coding: utf-8 -*-
"""Tests del tier classify (clasificaciones gratis) y su ruteo."""

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest_plugins = ("pytest_asyncio",)

from services.model_cascade import ModelCascade, ProviderConfig


def _cascade_with_providers():
    """Cascade con un provider gratis (cloudflare) + pago (tier_premium, tier_flash)."""
    m = ModelCascade.__new__(ModelCascade)
    m.providers = [
        ProviderConfig(name="tier_premium", url="x", model="claude", api_key="k",
                       timeout=5, max_retries=0, cooldown_seconds=1, failure_threshold=1,
                       kind="anthropic", paid=True),
        ProviderConfig(name="tier_flash", url="x", model="deepseek", api_key="k",
                       timeout=5, max_retries=0, cooldown_seconds=1, failure_threshold=1,
                       paid=True),
        ProviderConfig(name="tier_quality", url="x", model="minimax", api_key="k",
                       timeout=5, max_retries=0, cooldown_seconds=1, failure_threshold=1,
                       paid=True, explicit_only=True),
        ProviderConfig(name="cloudflare", url="x", model="llama-3.3-70b", api_key="k",
                       timeout=5, max_retries=0, cooldown_seconds=1, failure_threshold=1),
    ]
    m.circuit_breakers = {}
    m._health_histories = {}
    m._tier_stats = {}
    m.degraded_mode = False
    return m


class TestClassifyTier:
    def test_tier_mapping_points_to_cloudflare(self):
        assert ModelCascade.TIER_MAPPING["classify"] == "cloudflare"

    @pytest.mark.asyncio
    async def test_classify_uses_free_provider_first_and_never_anthropic(self):
        """Con cloudflare saludable, classify lo usa; la cadena de fallback
        NUNCA incluye Anthropic ni tier_quality."""
        m = _cascade_with_providers()
        calls = []

        async def fake_call(provider, messages, max_tokens, temperature):
            calls.append(provider.name)
            if provider.name == "cloudflare":
                return "ok"
            raise RuntimeError("no")

        m._call_with_retries = fake_call
        m._record_success = MagicMock()
        m._update_health = MagicMock()
        m._clear_degraded_state = MagicMock()
        m._append_telemetry_jsonl = MagicMock()
        m._is_circuit_open = MagicMock(return_value=False)
        m._last_usage = {}

        result = await m.generate(prompt="classify this", tier="classify", max_tokens=50)

        assert result == "ok"
        assert calls == ["cloudflare"], f"solo el gratis, got {calls}"
        assert m.get_tier_stats("classify")["calls"] == 1
        assert m.get_tier_stats("classify")["cost"] == 0.0

    @pytest.mark.asyncio
    async def test_classify_fallback_chain_never_reaches_anthropic(self):
        """Si todos los gratis fallan, el fallback llega a tier_flash (pago
        barato) pero NUNCA a tier_premium (Anthropic)."""
        m = _cascade_with_providers()
        calls = []

        async def fake_call(provider, messages, max_tokens, temperature):
            calls.append(provider.name)
            raise RuntimeError("todos fallan")

        m._call_with_retries = fake_call
        m._record_success = MagicMock()
        m._update_health = MagicMock()
        m._clear_degraded_state = MagicMock()
        m._append_telemetry_jsonl = MagicMock()
        m._is_circuit_open = MagicMock(return_value=False)
        m._get_cb = MagicMock(return_value=MagicMock(can_execute=MagicMock(return_value=True)))
        m._last_usage = {}

        with pytest.raises(RuntimeError):
            await m.generate(prompt="x", tier="classify", max_tokens=50)

        assert "tier_premium" not in calls, "Anthropic nunca en la cadena classify"
        assert "tier_quality" not in calls, "tier_quality nunca en la cadena classify"
        assert calls and calls[-1] == "tier_flash", f"el ultimo recurso es tier_flash, got {calls}"


class TestClassifyRouting:
    def test_claim_checker_defaults_to_flash(self):
        """claim_checker NO migra (acuerdo valido 5/5 pero 15/20 sin JSON
        parseable): queda en flash, no en classify."""
        import inspect
        from services.claim_checker import extract_claim, check_claim
        assert inspect.signature(extract_claim).parameters["tier"].default == "flash"
        assert inspect.signature(check_claim).parameters["tier"].default == "flash"

    def test_value_log_uses_classify(self):
        import inspect
        from phases.phase_b.value_log_utils import _classify_and_log_value
        src = inspect.getsource(_classify_and_log_value)
        assert 'tier="classify"' in src

    def test_bestof_judge_uses_classify(self):
        from phases.phase_a_content import _pick_best_post
        src = inspect.getsource(_pick_best_post)
        assert 'tier="classify"' in src

    def test_captcha_fallback_uses_classify_then_flash(self):
        import inspect
        from services.challenge_solver import ChallengeSolver
        src = inspect.getsource(ChallengeSolver._generate_with_captcha_fallback)
        assert '["classify", "flash"]' in src
        assert "premium" not in src
