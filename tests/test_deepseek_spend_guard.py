# -*- coding: utf-8 -*-
"""Tests del spend guard de DeepSeek directo (24/08/2026).

Saldo real recargado: $8.58. El cap diario (DEEPSEEK_SPEND_LIMIT_USD,
default $0.50 con precios PEAK como cota) garantiza >= 17 dias de pista
aun en el peor caso contable.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import services.model_cascade as mc_module
from services.model_cascade import ModelCascade, ProviderConfig


@pytest.fixture
def ds_provider():
    return ProviderConfig(
        name="tier_fallback",
        url="https://api.deepseek.com/v1/chat/completions",
        model="deepseek-v4-pro",
        api_key="sk-ds",
        paid=True,
    )


@pytest.fixture
def zen_ds_provider():
    # V4 Pro servido VIA ZEN: otro saldo, fuera del tracker directo
    return ProviderConfig(
        name="tier_fallback",
        url="https://opencode.ai/zen/v1/chat/completions",
        model="deepseek-v4-pro",
        api_key="sk-zen",
        paid=True,
    )


def _bare_cascade() -> ModelCascade:
    """Instancia sin __init__: solo los attrs que toca el path bajo test."""
    c = ModelCascade.__new__(ModelCascade)
    c._last_usage = {}
    return c


class TestDeepSeekSpendGuard:

    def test_is_deepseek_direct(self, ds_provider, zen_ds_provider):
        assert ModelCascade._is_deepseek_direct(ds_provider) is True
        assert ModelCascade._is_deepseek_direct(zen_ds_provider) is False

    def test_daily_reset(self, tmp_path, monkeypatch):
        tracker = tmp_path / "deepseek_spend_tracker.json"
        yesterday = "2026-01-01"
        tracker.write_text(json.dumps({"date": yesterday, "total_usd": 9.99}), encoding="utf-8")
        monkeypatch.setattr(mc_module, "_DEEPSEEK_SPEND_FILE", str(tracker))
        cascade = _bare_cascade()
        assert cascade._get_deepseek_spend() == 0.0  # dia viejo -> reset implicito

    def test_record_accumulates_same_day(self, tmp_path, monkeypatch, ds_provider):
        tracker = tmp_path / "deepseek_spend_tracker.json"
        monkeypatch.setattr(mc_module, "_DEEPSEEK_SPEND_FILE", str(tracker))
        cascade = _bare_cascade()
        cascade._record_deepseek_spend(ds_provider, 1_000_000, 1_000_000)
        cascade._record_deepseek_spend(ds_provider, 100_000, 0)
        total = json.loads(tracker.read_text(encoding="utf-8"))
        # peak pricing tier_fallback: (1.32+3.96) por 1M + 100k input x 1.32/M
        assert total["total_usd"] == pytest.approx(5.28 + 0.132, rel=1e-4)

    def test_gate_blocks_over_limit_and_falls_through(self, tmp_path, monkeypatch, ds_provider):
        tracker = tmp_path / "deepseek_spend_tracker.json"
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        tracker.write_text(json.dumps({"date": today, "total_usd": 0.60}), encoding="utf-8")
        monkeypatch.setattr(mc_module, "_DEEPSEEK_SPEND_FILE", str(tracker))
        cascade = _bare_cascade()
        with patch.object(ModelCascade, "_deepseek_spend_limit", return_value=0.50), \
             patch("services.model_cascade.requests.post") as post_mock:
            with pytest.raises(RuntimeError, match="DAILY spend limit"):
                cascade._call_provider_once(ds_provider, [{"role": "user", "content": "x"}], 128, 0.7)
            post_mock.assert_not_called()  # NUNCA toco la API con el cap agotado

    def test_under_limit_calls_api(self, tmp_path, monkeypatch, ds_provider):
        tracker = tmp_path / "deepseek_spend_tracker.json"
        monkeypatch.setattr(mc_module, "_DEEPSEEK_SPEND_FILE", str(tracker))
        cascade = _bare_cascade()
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }
        with patch.object(ModelCascade, "_deepseek_spend_limit", return_value=0.50), \
             patch("services.model_cascade.requests.post", return_value=resp) as post_mock:
            out = cascade._call_provider_once(ds_provider, [{"role": "user", "content": "x"}], 128, 0.7)
            assert out == "ok"
            post_mock.assert_called_once()
