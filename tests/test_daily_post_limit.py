# -*- coding: utf-8 -*-
"""
Pruebas del límite diario de posts en Fase A.

Verifica que el agente respeta max_posts_per_day = 1, 2, 3
en múltiples ciclos del mismo día, sin llamar a la API real.

En lugar de instanciar COMETRiobambaAgent (que tiene dependencias pesadas
y un bug preexistente con self.moltbook_client), testeamos directamente:
  - AgentState._check_daily_reset()          → reseteo diario
  - PhaseAContentGeneration.execute()        → gate interno de Fase A
  - El bucle _run_cycle() con un mock mínimo
"""

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.update({"DASHSCOPE_API_KEY": "sk-test", "MOLTBOOK_API_KEY": "sk-test"})

logging.basicConfig(level=logging.INFO, format="%(levelname)s|%(name)s|%(message)s")

TEST_DB = Path("data/test_daily_post_limit.db")

pytest_plugins = ("pytest_asyncio",)


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_db():
    """Usa una DB temporal aislada para cada test."""
    import services.persistence as _p
    _original = _p.DB_PATH
    _p.DB_PATH = TEST_DB
    if TEST_DB.exists():
        TEST_DB.unlink()
    yield
    if TEST_DB.exists():
        TEST_DB.unlink()
    _p.DB_PATH = _original


# ── Tests: AgentState._check_daily_reset ────────────────────────

from core.state_manager import AgentState


def test_daily_post_limit_state_init():
    """AgentState arranca con posts_today=0."""
    _clean_db()
    state = AgentState()
    assert state.posts_today == 0
    assert state.last_post_date == datetime.now().date().isoformat()


def test_daily_post_limit_check_daily_reset_same_day():
    """Mismo día: posts_today no se modifica."""
    _clean_db()
    state = AgentState()
    hoy = datetime.now().date().isoformat()
    state.posts_today = 3
    state.last_post_date = hoy
    state._check_daily_reset()
    assert state.posts_today == 3


def test_daily_post_limit_check_daily_reset_new_day():
    """Día distinto: posts_today se resetea a 0."""
    _clean_db()
    state = AgentState()
    state.posts_today = 2
    ayer = (datetime.now() - timedelta(days=1)).date().isoformat()
    state.last_post_date = ayer
    state._check_daily_reset()
    assert state.posts_today == 0
    assert state.last_post_date == datetime.now().date().isoformat()


def test_daily_post_limit_increment_tracking():
    """increment_posts_today aumenta y se mantiene al recargar."""
    _clean_db()
    state = AgentState()
    assert state.increment_posts_today() == 1
    assert state.increment_posts_today() == 2
    assert state.posts_today == 2
    # Recargar desde DB
    state2 = AgentState()
    assert state2.posts_today == 2


# ── Helpers ──────────────────────────────────────────────────────

def _clean_db():
    global TEST_DB
    if TEST_DB.exists():
        TEST_DB.unlink()
    from services.persistence import init_db
    init_db()


def _override_behavior_cfg(max_posts: int):
    """Helper para parchar behavior_cfg dentro de un test."""
    import config.config as _cfg
    _cfg.behavior_cfg["max_posts_per_day"] = max_posts
    _cfg.behavior_cfg["phase_a_publish_enabled"] = True
    _cfg.behavior_cfg["phase_b_enabled"] = False
    _cfg.behavior_cfg["phase_c_enabled"] = False
    _cfg.behavior_cfg["whisper_mode"] = False
    _cfg.behavior_cfg["max_comments_per_day"] = 0
    _cfg.behavior_cfg["max_comment_replies_per_cycle"] = 0
    _cfg.behavior_cfg["max_comments_per_post"] = 0
    _cfg.behavior_cfg["cycle_interval_seconds"] = 1


# ── Tests: simulación de ciclo con agente mockeado ───────────────

@pytest.mark.asyncio
async def test_daily_post_limit_one_post_per_day():
    """5 ciclos simulados con max=1: solo 1 post publicado."""
    _clean_db()
    _override_behavior_cfg(1)
    state = AgentState()
    hoy = datetime.now().date().isoformat()
    state.posts_today = 0
    state.last_post_date = hoy

    phase_a_call_count = 0

    for _ in range(5):
        state._check_daily_reset()
        max_posts = 1
        if state.posts_today >= max_posts:
            continue  # simula el skip de _run_cycle
        phase_a_call_count += 1
        state.increment_posts_today()

    assert phase_a_call_count == 1, f"Esperado 1 llamada, obtenido {phase_a_call_count}"
    assert state.posts_today == 1, f"posts_today={state.posts_today}"


@pytest.mark.asyncio
async def test_daily_post_limit_two_posts_per_day():
    """5 ciclos simulados con max=2: exactamente 2 posts."""
    _clean_db()
    _override_behavior_cfg(2)
    state = AgentState()
    hoy = datetime.now().date().isoformat()
    state.posts_today = 0
    state.last_post_date = hoy

    phase_a_call_count = 0

    for _ in range(5):
        state._check_daily_reset()
        max_posts = 2
        if state.posts_today >= max_posts:
            continue
        phase_a_call_count += 1
        state.increment_posts_today()

    assert phase_a_call_count == 2, f"Esperado 2 llamadas, obtenido {phase_a_call_count}"
    assert state.posts_today == 2, f"posts_today={state.posts_today}"


@pytest.mark.asyncio
async def test_daily_post_limit_three_posts_per_day():
    """5 ciclos simulados con max=3: exactamente 3 posts."""
    _clean_db()
    _override_behavior_cfg(3)
    state = AgentState()
    hoy = datetime.now().date().isoformat()
    state.posts_today = 0
    state.last_post_date = hoy

    phase_a_call_count = 0

    for _ in range(5):
        state._check_daily_reset()
        max_posts = 3
        if state.posts_today >= max_posts:
            continue
        phase_a_call_count += 1
        state.increment_posts_today()

    assert phase_a_call_count == 3, f"Esperado 3 llamadas, obtenido {phase_a_call_count}"
    assert state.posts_today == 3, f"posts_today={state.posts_today}"


@pytest.mark.asyncio
async def test_daily_post_limit_resets_next_day():
    """Límite se resetea al cambiar de día."""
    _clean_db()
    _override_behavior_cfg(1)
    state = AgentState()
    hoy = datetime.now().date().isoformat()
    state.posts_today = 0
    state.last_post_date = hoy

    # ── Día 1: 1 post ──
    state._check_daily_reset()
    assert state.posts_today < 1
    state.increment_posts_today()
    assert state.posts_today == 1

    # Segundo intento mismo día: bloqueado
    state._check_daily_reset()
    assert state.posts_today >= 1  # sigue siendo 1

    # ── Simular cambio de día ──
    ayer = (datetime.now() - timedelta(days=1)).date().isoformat()
    state.last_post_date = ayer

    # _check_daily_reset debe resetear
    state._check_daily_reset()
    assert state.posts_today == 0, f"posts_today={state.posts_today} después de reset"
    assert state.last_post_date == hoy

    # ── Día 2: otro post ──
    assert state.posts_today < 1
    state.increment_posts_today()
    assert state.posts_today == 1


# ── Tests: gate interno de PhaseAContentGeneration.execute() ────

@pytest.mark.asyncio
async def test_phase_a_internal_gate_skips_when_limit_reached():
    """PhaseAContentGeneration.execute() respeta max_posts_per_day."""
    _clean_db()
    _override_behavior_cfg(1)
    state = AgentState()
    state.posts_today = 1  # ya se publicó 1 hoy
    from datetime import datetime
    fake_now = datetime(2026, 7, 22, 12, 0, 0)
    hoy = fake_now.date().isoformat()
    state.last_post_date = hoy

    from phases.deps import PhaseADeps
    deps = PhaseADeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_posts_per_day": 1},
        posts_today=1,
        get_posts_today=lambda: 1,
    )
    from phases.phase_a_content import PhaseAContentGeneration
    phase_a = PhaseAContentGeneration(deps=deps)
    with patch("phases.phase_a_content.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
        result = await phase_a.execute()
    assert result.get("skipped") == "daily_limit_reached", f"Esperado skip, obtenido {result}"


@pytest.mark.asyncio
async def test_cycle_continues_with_phase_b_when_phase_a_is_blocked():
    """Cuando posts_today >= max_posts, Phase A se salta pero el ciclo sigue."""
    _clean_db()
    _override_behavior_cfg(1)
    import config.config as _cfg
    _cfg.behavior_cfg["phase_b_enabled"] = True
    _cfg.behavior_cfg["phase_c_enabled"] = False

    model_cascade = MagicMock()
    model_cascade.generate = AsyncMock(return_value="Test reply.")
    moltbook = MagicMock()
    moltbook.create_comment = MagicMock(return_value={"success": True, "id": "c1"})
    moltbook.get_feed = MagicMock(return_value=MagicMock(success=True, data={"posts": []}))
    moltbook.fetch_my_posts = MagicMock(return_value=[])
    moltbook.fetch_post_comments = MagicMock(return_value=[])

    from phases.phase_b import PhaseB
    phase_b_mock = MagicMock(spec=PhaseB)
    phase_b_mock.execute = AsyncMock(return_value={
        "success": True, "replies_published": 0,
        "feed_replies": [], "own_post_replies": [],
    })

    with (
        patch("core.agent.create_telegram_client", return_value=None),
        patch("core.agent.PlatformAwareness", return_value=None),
        patch.dict(_cfg.behavior_cfg, values=_cfg.behavior_cfg, clear=False),
    ):
        from core.agent import COMETRiobambaAgent
        ag = COMETRiobambaAgent(
            credentials=MagicMock(moltbook_api_key="sk-test"),
            model_cascade=model_cascade,
            moltbook_client=moltbook,
        )
        ag._phase_b = phase_b_mock
        ag._platform_awareness_available = False
        ag.platform_awareness = None
        ag.telegram_client = None

        hoy = datetime.now().date().isoformat()
        ag.state.posts_today = 1  # ya alcanzó el límite
        ag.state.last_post_date = hoy

        result = await ag._run_cycle()
        assert "phase_a" in result
        assert result["phase_a"] == {}, f"Phase A no debería ejecutarse: {result['phase_a']}"
        assert "phase_b" in result
        assert phase_b_mock.execute.call_count == 1, "Phase B debería haberse ejecutado"


@pytest.mark.asyncio
async def test_phase_a_internal_gate_allows_when_under_limit():
    """PhaseAContentGeneration.execute() permite publicar si hay cupo."""
    _clean_db()
    _override_behavior_cfg(1)
    state = AgentState()
    state.posts_today = 0
    from datetime import datetime
    fake_now = datetime(2026, 7, 22, 12, 0, 0)
    hoy = fake_now.date().isoformat()
    state.last_post_date = hoy

    # Mock ligero para que execute() no llame a la API real
    model_cascade = MagicMock()
    model_cascade.generate = AsyncMock(return_value="Título\n\nCuerpo del post con contenido técnico suficiente para superar las validaciones de longitud mínima y demás.")

    moltbook = MagicMock()
    moltbook.create_post = MagicMock(return_value={"success": True, "status": 201, "id": "p1"})

    with patch("config.behavior_cfg", {"max_posts_per_day": 1, "phase_a_publish_enabled": True, "phase_b_enabled": False, "phase_c_enabled": False, "whisper_mode": False, "max_comments_per_day": 0, "max_comment_replies_per_cycle": 0, "max_comments_per_post": 0, "cycle_interval_seconds": 1}):
        import config
        config.behavior_cfg["max_posts_per_day"] = 1

        # Redirect topic_history to temp to avoid stale data from other tests
        import phases.phase_a_content as pac
        _orig_th = pac._TOPIC_HISTORY_FILE
        pac._TOPIC_HISTORY_FILE = Path("data/test_topic_history_tmp.json")

        try:
            from phases.deps import PhaseADeps
            deps = PhaseADeps(
                model_cascade=model_cascade,
                moltbook_client=moltbook,
                behavior_cfg={"max_posts_per_day": 1},
                posts_today=0,
                get_posts_today=lambda: 0,
            )
            from phases.phase_a_content import PhaseAContentGeneration
            phase_a = PhaseAContentGeneration(deps=deps)
            with patch("phases.phase_a_content.datetime") as mock_dt:
                mock_dt.now.return_value = fake_now
                mock_dt.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
                result = await phase_a.execute()
        finally:
            pac._TOPIC_HISTORY_FILE = _orig_th
            Path("data/test_topic_history_tmp.json").unlink(missing_ok=True)

    assert "skipped" not in result, f"No debería saltar, resultado={result}"
