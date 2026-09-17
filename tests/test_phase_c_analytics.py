import sys
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phases.phase_c_analytics import PhaseCAnalytics
from phases.deps import PhaseCDeps


@pytest.fixture
def deps():
    return PhaseCDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        write_policy=MagicMock(),
        behavior_cfg={
            "phase_c_analytics_interval": 0,
            "TELEGRAM_DAILY_REPORT": False,
        },
        get_comments_today=lambda: 0,
        increment_comments_today=lambda: None,
    )


class TestPhaseCStrategyState:

    @staticmethod
    def _make_analytics(deps):
        """Create PhaseCAnalytics instance with analytics interval forced to 0."""
        analytics = PhaseCAnalytics(deps)
        analytics.analytics_interval = 0
        return analytics

    @pytest.mark.asyncio
    async def test_strategy_state_saved_on_analytics_run(self, deps):
        """StrategyState.save is called with expected keys when analytics runs."""
        analytics = self._make_analytics(deps)
        with self._mock_own_metrics(analytics, [
            {"score": 3, "comment_count": 1, "title": "Agent architecture", "content": "agent llm scaling"},
        ]), patch("phases.phase_c_analytics.StrategyState") as MockSS:
            instance = MockSS.return_value
            result = await analytics.execute()

        assert result["analytics_run"] is True
        instance.save.assert_called_once()
        call_kwargs = instance.save.call_args[0][0]
        assert "top_topics" in call_kwargs
        assert "avoid_topics" in call_kwargs
        assert "best_tone" in call_kwargs
        assert "last_updated" in call_kwargs
        assert call_kwargs["best_tone"] == "neutral"

    @pytest.mark.asyncio
    async def test_top_topics_extracted_from_metrics(self, deps):
        """Top-performing topic names appear in strategy state."""
        analytics = self._make_analytics(deps)
        with self._mock_own_metrics(analytics, [
            {"score": 5, "comment_count": 2, "title": "LLM scaling", "content": "llm scaling agent architecture"},
            {"score": 3, "comment_count": 0, "title": "Agent loops", "content": "agent loops security"},
        ]), patch("phases.phase_c_analytics.StrategyState") as MockSS:
            instance = MockSS.return_value
            await analytics.execute()

        saved = instance.save.call_args[0][0]
        assert len(saved["top_topics"]) > 0

    @pytest.mark.asyncio
    async def test_avoid_topics_empty_when_engagement_positive(self, deps):
        """When engagement > 0, avoid_topics should be empty."""
        analytics = self._make_analytics(deps)
        with self._mock_own_metrics(analytics, [
            {"score": 2, "comment_count": 1, "title": "ML ops", "content": "mlops deployment"},
        ]), patch("phases.phase_c_analytics.StrategyState") as MockSS:
            instance = MockSS.return_value
            await analytics.execute()

        saved = instance.save.call_args[0][0]
        assert saved["avoid_topics"] == []

    @pytest.mark.asyncio
    async def test_avoid_topics_filled_when_zero_engagement(self, deps):
        """When posts exist but engagement is 0, those topics go to avoid_topics."""
        analytics = self._make_analytics(deps)
        with self._mock_own_metrics(analytics, [
            {"score": 0, "comment_count": 0, "title": "Security fail", "content": "security agent architecture tanked"},
        ], posts_published_24h=2), patch("phases.phase_c_analytics.StrategyState") as MockSS:
            instance = MockSS.return_value
            await analytics.execute()

        saved = instance.save.call_args[0][0]
        assert len(saved["avoid_topics"]) > 0

    @staticmethod
    def _mock_own_metrics(analytics, live_posts, posts_published_24h=1):
        """Context manager: mete las métricas por la vía NUEVA (actividad propia):
        own_post_store + get_post() por post. Sustituye al antiguo mock de
        fetch_posts (feed global), que medía actividad ajena — ver fix L3,
        auditoría 22/08/2026. Uso:
            with self._mock_own_metrics(a, [...]), patch(StrategyState) as m: ..."""
        stack = ExitStack()
        stack.enter_context(patch(
            "services.own_post_store.load_own_posts",
            return_value=[{"id": f"pid-{i}"} for i in range(len(live_posts))],
        ))
        stack.enter_context(patch(
            "services.own_post_store.count_posts_since",
            return_value=posts_published_24h,
        ))
        analytics.moltbook.get_post.side_effect = list(live_posts)
        return stack

    @pytest.mark.asyncio
    async def test_strategy_state_skipped_when_analytics_skipped(self, deps):
        """StrategyState.save should NOT be called when analytics gate prevents run."""
        analytics = self._make_analytics(deps)
        analytics.analytics_interval = 86400 * 365
        analytics._load_state = MagicMock(return_value={
            "last_analytics_run": datetime.now().isoformat(),
            "insights_applied": [],
            "metrics_history": [],
        })

        with patch("phases.phase_c_analytics.StrategyState") as MockSS:
            instance = MockSS.return_value
            await analytics.execute()

        instance.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_last_updated_is_utc_isoformat(self, deps):
        """last_updated is a valid UTC ISO-8601 string."""
        analytics = self._make_analytics(deps)
        analytics.moltbook.fetch_posts.return_value = [
            {"likes": 1, "comments_count": 0, "title": "Test", "body": "test"},
        ]

        with patch("phases.phase_c_analytics.StrategyState") as MockSS:
            instance = MockSS.return_value
            await analytics.execute()

        saved = instance.save.call_args[0][0]
        ts = saved["last_updated"]
        assert ts is not None
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None


class TestEnergyIntelCadence:

    def test_energy_intel_disabled_by_config_skips_import(self, deps):
        """Con energy_intel_enabled=False el hook no importa ni corre el ingest."""
        analytics = PhaseCAnalytics(deps)
        analytics.telegram = MagicMock()
        analytics.telegram.enabled = True
        with patch("phases.phase_c_analytics.behavior_cfg",
                   {"energy_intel_enabled": False}) as mock_cfg, \
             patch("services.energy_intel_telegram.run_energy_intel_with_alerts") as mock_run:
            analytics._maybe_run_energy_intel()
        mock_run.assert_not_called()

    def test_energy_intel_runs_ingest_without_telegram(self, deps):
        """Sin telegram, el ingest corre (info al research_agenda);
        solo las alertas Telegram quedan off (diseño v5.x)."""
        analytics = PhaseCAnalytics(deps)
        analytics.telegram = None
        with patch("phases.phase_c_analytics.behavior_cfg",
                   {"energy_intel_enabled": True}), \
             patch("services.energy_intel_telegram.should_run_energy_intel", return_value=True), \
             patch("services.energy_intel_telegram.run_energy_intel_with_alerts") as mock_run:
            analytics._maybe_run_energy_intel()
        # ingest corre con telegram=None (no crashea)
        mock_run.assert_called_once_with(None)
    @pytest.mark.asyncio
    async def test_energy_intel_runs_even_when_analytics_gated(self, deps):
        """P3: el hook de Energy Intel corre ANTES del gate de analytics de 24h
        (con su propio throttle de 60 min). Analytics gateado => EIN igual corre."""
        analytics = PhaseCAnalytics(deps)
        analytics.analytics_interval = 86400 * 365
        analytics.telegram = MagicMock()
        analytics.telegram.enabled = True
        analytics._load_state = MagicMock(return_value={
            "last_analytics_run": datetime.now().isoformat(),
            "insights_applied": [],
            "metrics_history": [],
        })
        with patch("phases.phase_c_analytics.behavior_cfg",
                   {"energy_intel_enabled": True}), \
             patch.object(analytics, "_maybe_run_energy_intel",
                          wraps=analytics._maybe_run_energy_intel) as spy, \
             patch("phases.phase_c_analytics.StrategyState") as MockSS, \
             patch("services.energy_intel_telegram.should_run_energy_intel", return_value=False) as mock_throttle:
            result = await analytics.execute()

        assert result["analytics_run"] is False
        spy.assert_called_once()
        mock_throttle.assert_called_once()
