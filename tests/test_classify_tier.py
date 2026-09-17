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
        assert '["classify", "flash", "pro"]' in src
        assert "premium" not in src