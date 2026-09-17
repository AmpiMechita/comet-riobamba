# -*- coding: utf-8 -*-
"""
Tests unitarios para lógica core de COMET-RIOBAMBA:
- validate_post_text()
- Relevance scoring y decisiones en Fase B
- _check_daily_reset() en state_manager
- Gates de cuota diarios, por ciclo, por post
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.update({"DASHSCOPE_API_KEY": "sk-test", "MOLTBOOK_API_KEY": "sk-test"})

logging.basicConfig(level=logging.INFO, format="%(levelname)s|%(name)s|%(message)s")
pytest_plugins = ("pytest_asyncio",)

# ── validate_post_text ─────────────────────────────────────────

from phases.phase_a_content import validate_post_text


def test_validate_post_text_empty():
    valid, reason = validate_post_text("")
    assert not valid
    assert reason == "empty_or_invalid"


def test_validate_post_text_too_short():
    valid, reason = validate_post_text("Corto.")
    assert not valid
    assert reason == "too_short"


def test_validate_post_text_too_long():
    long = "A" * 1000
    valid, reason = validate_post_text(long)
    assert not valid
    assert reason == "too_long"


def _long_enough(prefix: str) -> str:
    """Pad to exceed EDITORIAL_CONFIG min_length_chars (300)."""
    body = prefix + "\n\n" + " ".join(["word"] * 150)
    return body


def test_validate_post_text_contains_url():
    text = _long_enough("This is a post about agents. Check https://example.com for more.")
    valid, reason = validate_post_text(text)
    assert not valid
    assert reason == "contains_url"


def test_validate_post_text_contains_code():
    text = _long_enough("We can use def my_function(): to solve this.")
    valid, reason = validate_post_text(text)
    assert not valid
    assert reason == "contains_code"


def test_validate_post_text_contains_bullets():
    text = _long_enough("Here are some points:\n\n- First point\n- Second point")
    valid, reason = validate_post_text(text)
    assert not valid
    assert reason == "contains_bullet_points"


def test_validate_post_text_contains_emoji():
    text = _long_enough("Great post about agents! 👍")
    valid, reason = validate_post_text(text)
    assert not valid
    assert reason == "contains_emoji"


def test_validate_post_text_academic_subtitle():
    text = _long_enough("Abstract\n\nThis paper discusses agent architectures in depth.")
    valid, reason = validate_post_text(text)
    assert not valid
    assert reason == "contains_academic_subtitles"


def test_validate_post_text_filler_start():
    text = _long_enough("In the realm of artificial intelligence, we explore new frontiers.")
    valid, reason = validate_post_text(text)
    assert not valid
    assert reason == "contains_filler_opening"


def test_validate_post_text_single_paragraph():
    text = "This is only one paragraph without any blank line separation." + " " + " ".join(["word"] * 150)
    valid, reason = validate_post_text(text)
    assert not valid
    assert reason == "single_paragraph"


def test_validate_post_text_valid():
    text = "Silent failures in agent loops often go undetected until production.\n\nThis happens because most observability tools assume synchronous execution patterns. Tracing every tool call would reveal the bottleneck.\n\nA simple circuit breaker on each external dependency would catch most of these cases in production environments."
    valid, reason = validate_post_text(text)
    assert valid, f"Expected valid, got reason={reason}"
    assert reason == "ok"


# ── contains_code: vocabulario del niche NO debe marcarse como código ──
# Fix CODE_PATTERN: async/await/class como palabras sueltas de prosa (ingeniería
# de agentes en producción) no son código. Antes daban falsos positivos.

from phases.phase_a_content import CODE_PATTERN

# Prosa legítima del niche que usa async/await/class como lenguaje natural.
NICHE_PROSE_NOT_CODE = [
    "the agent runs async",
    "a new class of failure modes",
    "a class of silent errors that async loops hide",
    "the caller awaits the result",
    "async execution and await semantics",
]

# Código real que SÍ debe seguir siendo rechazado.
REAL_CODE_SNIPPETS = [
    "def foo():",
    "class Bar:",
    "import os",
    "async def handler():",
    "Here is the fix:\n\n```\nx = 1\n```",
]


@pytest.mark.parametrize("prose", NICHE_PROSE_NOT_CODE)
def test_code_pattern_allows_niche_prose(prose):
    assert CODE_PATTERN.search(prose) is None, f"falso positivo de código en prosa: {prose!r}"


@pytest.mark.parametrize("snippet", REAL_CODE_SNIPPETS)
def test_code_pattern_flags_real_code(snippet):
    assert CODE_PATTERN.search(snippet) is not None, f"código real no detectado: {snippet!r}"


@pytest.mark.parametrize("prose", NICHE_PROSE_NOT_CODE)
def test_validate_post_text_niche_prose_not_code(prose):
    valid, reason = validate_post_text(_long_enough(prose))
    assert reason != "contains_code", f"prosa del niche marcada como código: {prose!r}"
    assert valid, f"esperaba válido, reason={reason}"


def test_validate_post_text_real_code_still_rejected():
    text = _long_enough("Here is how you solve it: async def handler(): pass")
    valid, reason = validate_post_text(text)
    assert not valid
    assert reason == "contains_code"


# ── Fix 5: ERROR_PATTERN — "exception" en prosa NO es un error log ──
# La palabra suelta "exception"/"except" es vocabulario del niche; solo debe
# rebotar la FORMA de un log/excepcion (Traceback, raise X, XError:/XException:).

ERROR_PROSE_OK = [
    "we tag every exception handler",
    "with one exception all retries succeeded",
    "the try-except swallowed the failure",
]
ERROR_REAL_REJECT = [
    "Traceback (most recent call last):",
    "raise ValueError",
    "ConnectionError: timeout",
    "ValueError: bad input",
]


@pytest.mark.parametrize("prose", ERROR_PROSE_OK)
def test_validate_post_text_error_prose_ok(prose):
    valid, reason = validate_post_text(_long_enough(prose))
    assert reason != "contains_error_log", f"falso positivo de error log en prosa: {prose!r}"
    assert valid, f"esperaba válido, reason={reason}"


@pytest.mark.parametrize("snippet", ERROR_REAL_REJECT)
def test_validate_post_text_real_error_still_rejected(snippet):
    valid, reason = validate_post_text(_long_enough(snippet))
    assert not valid
    assert reason == "contains_error_log", f"error real no detectado: {snippet!r} -> {reason}"


# ── Fix 5: ACADEMIC_SUBTITLE_PATTERN — dos puntos obligatorio ──
# Prosa que empieza con esas palabras es válida; solo el subtítulo real "X:" rebota.

ACADEMIC_PROSE_OK = [
    "Claim verification in agents is hard.",
    "Discussion threads rarely capture the failure.",
    "Conclusion drift happens when loops never terminate.",
]
ACADEMIC_REAL_REJECT = [
    "Abstract: this paper",
    "Conclusion: the agent failed",
    "Methodology:\nWe ran",
]


@pytest.mark.parametrize("prose", ACADEMIC_PROSE_OK)
def test_validate_post_text_academic_prose_ok(prose):
    valid, reason = validate_post_text(_long_enough(prose))
    assert reason != "contains_academic_subtitles", f"falso positivo de subtítulo académico: {prose!r}"
    assert valid, f"esperaba válido, reason={reason}"


@pytest.mark.parametrize("prose", ACADEMIC_REAL_REJECT)
def test_validate_post_text_real_academic_subtitle_still_rejected(prose):
    valid, reason = validate_post_text(_long_enough(prose))
    assert not valid
    assert reason == "contains_academic_subtitles", f"subtítulo real no detectado: {prose!r} -> {reason}"


# ── _log_rejected_body: persiste texto rechazado para observabilidad (Fix 2) ──

def test_log_rejected_body_writes_valid_json_and_truncates(tmp_path, monkeypatch):
    import phases.phase_a_content as pac

    target = tmp_path / "rejected_posts.jsonl"
    monkeypatch.setattr(pac, "_REJECTED_POSTS_LOG", target)

    long_title = "T" * 300
    long_body = "B" * 1000
    pac._log_rejected_body(
        topic="mi tópico de prueba",
        topic_source="arxiv",
        attempt=2,
        reason="low_quality:below_min_quality_score:0.3:clarification",
        title=long_title,
        body=long_body,
    )

    assert target.exists(), "el archivo de rechazos no se escribió"
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])  # JSON válido
    assert rec["topic"] == "mi tópico de prueba"
    assert rec["topic_source"] == "arxiv"
    assert rec["attempt"] == 2
    assert rec["reason"] == "low_quality:below_min_quality_score:0.3:clarification"
    assert len(rec["title"]) == 200 and rec["title"] == "T" * 200  # truncado a 200
    assert len(rec["body"]) == 800 and rec["body"] == "B" * 800    # truncado a 800
    assert "timestamp" in rec


def test_log_rejected_body_appends(tmp_path, monkeypatch):
    import phases.phase_a_content as pac

    target = tmp_path / "rejected_posts.jsonl"
    monkeypatch.setattr(pac, "_REJECTED_POSTS_LOG", target)

    pac._log_rejected_body("t1", "arxiv", 1, "similar_recent", "title1", "body1")
    pac._log_rejected_body("t2", "rss", 3, "validation_failed:contains_url", "title2", "body2")

    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["topic"] == "t1"
    assert json.loads(lines[1])["reason"] == "validation_failed:contains_url"


# ── Fase B: relevance scoring and decisions ────────────────────

from phases.phase_b import PhaseB, RelevanceDecision
from phases.deps import PhaseBDeps


def _make_comment(content: str, **kw) -> dict:
    c = {"content": content, "id": "c1"}
    c.update(kw)
    return c


def test_compute_relevance_score_question():
    score = PhaseB._compute_relevance_score(_make_comment("How do you handle this kind of situation with the agent tool calls?"))
    assert score >= 30  # relevance_boost_question = 30, no short penalty (>25 chars)


def test_compute_relevance_score_mention():
    score = PhaseB._compute_relevance_score(_make_comment("Hey @comet, what do you think?"))
    assert score >= 40  # relevance_boost_mention = 40


def test_compute_relevance_score_tech_keywords():
    score = PhaseB._compute_relevance_score(_make_comment("My LLM agent pipeline has latency issues with tokens."))
    assert score >= 25  # relevance_boost_tech_keyword = 25


def test_compute_relevance_score_spam_penalty():
    score = PhaseB._compute_relevance_score(_make_comment("gracias thanks jaja 👍"))
    assert score < 30  # penalizado por palabras de agradecimiento/emoji


def test_compute_relevance_score_short_text():
    score = PhaseB._compute_relevance_score(_make_comment("Hi"))
    assert score < 10  # penalizado por muy corto


def test_decide_reply_limit_not_ok():
    decision = PhaseB._decide_reply(_make_comment("Interesting post!"), limit_ok=False)
    assert not decision.should_reply
    assert "limit_reached" in decision.reason


def test_decide_reply_empty():
    decision = PhaseB._decide_reply(_make_comment(""))
    assert not decision.should_reply


def test_decide_reply_direct_mention():
    decision = PhaseB._decide_reply(_make_comment("@comet-riobamba can you help with this?"))
    assert decision.should_reply
    assert decision.reason == "reply_sent"


def test_decide_reply_high_score_auto():
    decision = PhaseB._decide_reply(_make_comment("How do you implement circuit breakers for LLM tool calls in production with error handling and fallback mechanisms and latency monitoring? This is a real challenge for many engineers deploying agents in production environments right now."))
    assert decision.should_reply, f"Expected reply, got {decision}"
    assert decision.reason == "reply_sent"


def test_decide_reply_low_relevance():
    decision = PhaseB._decide_reply(_make_comment("Nice weather today"))
    assert not decision.should_reply


def test_decide_reply_from_post_empty():
    decision = PhaseB._decide_reply_from_post("")
    assert not decision.should_reply


def test_decide_reply_from_post_technical():
    decision = PhaseB._decide_reply_from_post("How do you handle LLM agent pipeline errors and latency issues with tool calls in production?")
    assert decision.should_reply


def test_decide_reply_from_post_low_relevance():
    decision = PhaseB._decide_reply_from_post("Check out my new product at this link!")
    assert not decision.should_reply


# ── State Manager: _check_daily_reset ──────────────────────────

from core.state_manager import AgentState
from services import persistence
from services.persistence import init_db


def _clean_db():
    # Referencia dinamica al modulo (persistence.DB_PATH), NO import por valor:
    # el conftest redirige el atributo del modulo a tmp_path; un nombre copiado
    # en el import quedaria apuntando a la base REAL de data/ y la borraria.
    if persistence.DB_PATH.exists():
        persistence.DB_PATH.unlink()
    init_db()
    _log_path = persistence.DB_PATH.parent / "published_posts.json"
    if _log_path.exists():
        _log_path.unlink()


def test_agent_state_init():
    _clean_db()
    state = AgentState()
    assert state.posts_today == 0
    assert state.comments_today == 0
    assert state.cycle_count == 0
    assert state.consecutive_failures == 0
    assert state.last_value_review is None


def test_check_daily_reset_same_day():
    _clean_db()
    state = AgentState()
    state.posts_today = 3
    state.comments_today = 5
    today = datetime.now().date().isoformat()
    state.last_post_date = today
    state._check_daily_reset()
    assert state.posts_today == 3
    assert state.comments_today == 5


def test_check_daily_reset_new_day():
    _clean_db()
    state = AgentState()
    state.posts_today = 2
    state.comments_today = 1
    yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
    state.last_post_date = yesterday
    state._check_daily_reset()
    assert state.posts_today == 0
    assert state.comments_today == 0
    assert state.last_post_date == datetime.now().date().isoformat()


def test_increment_posts_today():
    _clean_db()
    state = AgentState()
    val = state.increment_posts_today()
    assert val == 1
    assert state.posts_today == 1


def test_increment_comments_today():
    _clean_db()
    state = AgentState()
    val = state.increment_comments_today()
    assert val == 1
    assert state.comments_today == 1


def test_mark_value_review():
    _clean_db()
    state = AgentState()
    state.mark_value_review("reviews/review_001.json")
    assert state.last_value_review is not None


def test_consecutive_failures_persistence():
    _clean_db()
    state = AgentState()
    state.consecutive_failures = 5
    state.save()
    state2 = AgentState()
    assert state2.consecutive_failures == 5


def test_last_value_review_persistence():
    _clean_db()
    state = AgentState()
    state.mark_value_review("reviews/test.json")
    review = state.last_value_review
    state2 = AgentState()
    assert state2.last_value_review == review


# ── Quota gates (Phase B internal) ─────────────────────────────

def test_phase_b_daily_gate():
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_comments_per_day": 3, "max_comment_replies_per_cycle": 5, "max_comments_per_post": 2},
        agent_name="TEST",
        get_comments_today=lambda: 3,
        increment_comments_today=lambda: 4,
    )
    pb = PhaseB(deps=deps)
    assert pb.max_comments_per_day == 3
    assert pb.get_comments_today() == 3


def test_phase_b_init_fallbacks():
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={},
        agent_name="TEST",
    )
    pb = PhaseB(deps=deps)
    assert pb.max_comments_per_day is None  # v5.x: sin limite por defecto
    assert pb.max_comments_per_post is None  # v5.x: sin limite
    assert pb.max_replies_per_cycle is None  # v5.x: sin limite
    assert pb.get_comments_today() == 0  # lambda: 0 fallback


# ── Anti-duplicate guard and style policy ─────────────────────

from phases.phase_b import COMMENT_STYLE_INSTRUCTIONS, is_near_duplicate_reply, is_semantic_duplicate_reply, _safe_truncate


def test_comment_style_instructions_contains_key_phrases():
    assert "COMET-RIOBAMBA" in COMMENT_STYLE_INSTRUCTIONS
    assert "VOICE GUIDELINES" in COMMENT_STYLE_INSTRUCTIONS
    assert "invariant" in COMMENT_STYLE_INSTRUCTIONS
    assert "threshold" in COMMENT_STYLE_INSTRUCTIONS
    assert "No emojis" in COMMENT_STYLE_INSTRUCTIONS


def test_is_near_duplicate_reply_same_text():
    text = "Este es un comentario técnico sobre agentes."
    assert is_near_duplicate_reply(text, text)


def test_is_near_duplicate_reply_very_similar():
    a = "La latencia es un problema común en pipelines de LLM."
    b = "La latencia es un problema muy común en pipelines de LLM."
    assert is_near_duplicate_reply(a, b)


def test_is_near_duplicate_reply_different():
    a = "La latencia es un problema común en pipelines de LLM."
    b = "Recomiendo usar circuit breakers para mejorar la tolerancia a fallos en sistemas distribuidos."
    assert not is_near_duplicate_reply(a, b)


def test_is_near_duplicate_reply_empty():
    assert not is_near_duplicate_reply("", "some text")
    assert not is_near_duplicate_reply("some text", "")
    assert not is_near_duplicate_reply("", "")


def test_is_semantic_duplicate_reply_paraphrase():
    a = "Latency in LLM pipelines is a common problem affecting response times"
    b = "Latency in LLM pipelines is a common problem that affects response times"
    assert is_semantic_duplicate_reply(a, b)


def test_is_semantic_duplicate_reply_different_angle():
    a = "Latency in LLM pipelines is a common problem affecting response times"
    b = "Circuit breakers prevent cascading failures in distributed agent systems"
    assert not is_semantic_duplicate_reply(a, b)


def test_is_semantic_duplicate_reply_empty():
    assert not is_semantic_duplicate_reply("", "some text")
    assert not is_semantic_duplicate_reply("some text", "")
    assert not is_semantic_duplicate_reply("", "")


def test_safe_truncate_short_text():
    text = "Texto corto."
    assert _safe_truncate(text, max_chars=100) == text


def test_safe_truncate_at_boundary():
    text = "Primera oración. Segunda oración. Tercera oración."
    result = _safe_truncate(text, max_chars=25)
    assert result.endswith(".")
    assert len(result) <= 30


def test_safe_truncate_no_boundary():
    text = "A" * 1000
    result = _safe_truncate(text, max_chars=100)
    assert len(result) <= 104  # 100 + "..."


# ── Phase C: cycle gate ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_phase_c_only_runs_every_3_cycles():
    """Phase C solo ejecuta analytics en ciclos múltiplos de 3."""
    from core.agent import COMETRiobambaAgent
    from unittest.mock import AsyncMock

    model_cascade = MagicMock()
    moltbook = MagicMock()
    import config.config as _cfg

    with (
        patch("core.agent.create_telegram_client", return_value=None),
        patch("core.agent.PlatformAwareness", return_value=None),
        patch.dict(_cfg.behavior_cfg, values={
            "phase_c_enabled": True,
            "phase_b_enabled": False,
            "phase_a_publish_enabled": False,
            "whisper_mode": False,
        }, clear=False),
    ):
        ag = COMETRiobambaAgent(
            credentials=MagicMock(moltbook_api_key="sk-test"),
            model_cascade=model_cascade,
            moltbook_client=moltbook,
        )
        ag._phase_c = AsyncMock()
        ag._phase_c.execute = AsyncMock(return_value={
            "analytics_run": True, "insights_generated": 2,
        })

        ag.cycle_count = 1
        r1 = await ag._run_phase_c()
        assert r1.get("skipped") == "phase_c_cycle_gate", f"cycle=1 no debería ejecutar: {r1}"

        ag.cycle_count = 2
        r2 = await ag._run_phase_c()
        assert r2.get("skipped") == "phase_c_cycle_gate", f"cycle=2 no debería ejecutar: {r2}"

        ag.cycle_count = 3
        r3 = await ag._run_phase_c()
        assert r3.get("analytics_run") is True, f"cycle=3 debería ejecutar: {r3}"

        ag.cycle_count = 6
        r6 = await ag._run_phase_c()
        assert r6.get("analytics_run") is True, f"cycle=6 debería ejecutar: {r6}"


@pytest.mark.asyncio
async def test_phase_c_exception_does_not_block_cycle():
    """Una excepción en Phase C no corta el ciclo ni propaga el error."""
    from core.agent import COMETRiobambaAgent
    from unittest.mock import AsyncMock

    model_cascade = MagicMock()
    moltbook = MagicMock()
    import config.config as _cfg

    with (
        patch("core.agent.create_telegram_client", return_value=None),
        patch("core.agent.PlatformAwareness", return_value=None),
        patch.dict(_cfg.behavior_cfg, values={
            "phase_c_enabled": True,
            "phase_b_enabled": False,
            "phase_a_publish_enabled": False,
            "whisper_mode": False,
        }, clear=False),
    ):
        ag = COMETRiobambaAgent(
            credentials=MagicMock(moltbook_api_key="sk-test"),
            model_cascade=model_cascade,
            moltbook_client=moltbook,
        )
        ag._phase_c = AsyncMock()
        ag._phase_c.execute = AsyncMock(side_effect=RuntimeError("phase_c_crash"))

        ag.cycle_count = 3
        result = await ag._run_phase_c()
        assert result.get("analytics_run") is False
        assert "error" in result


# ── Graceful stop via data/stop.flag ────────────────────────────


def _make_agent_for_stopflag(tmp_path):
    from core.agent import COMETRiobambaAgent
    import config.config as _cfg
    with (
        patch("core.agent.create_telegram_client", return_value=None),
        patch("core.agent.PlatformAwareness", return_value=None),
        patch.dict(_cfg.behavior_cfg, values={
            "phase_a_publish_enabled": False,
            "phase_b_enabled": False,
            "phase_c_enabled": False,
            "whisper_mode": False,
        }, clear=False),
    ):
        ag = COMETRiobambaAgent(
            credentials=MagicMock(moltbook_api_key="sk-test"),
            model_cascade=MagicMock(),
            moltbook_client=MagicMock(),
        )
    ag.stop_flag_file = tmp_path / "stop.flag"
    return ag


def test_check_stop_flag_absent_is_noop(tmp_path):
    """No stop.flag → returns False, does not request shutdown."""
    ag = _make_agent_for_stopflag(tmp_path)
    assert ag.shutdown_requested is False
    assert ag._check_stop_flag() is False
    assert ag.shutdown_requested is False


def test_check_stop_flag_detected_sets_shutdown_and_deletes_flag(tmp_path):
    """stop.flag present → returns True, sets shutdown_requested, and removes the flag."""
    ag = _make_agent_for_stopflag(tmp_path)
    ag.stop_flag_file.parent.mkdir(parents=True, exist_ok=True)
    ag.stop_flag_file.write_text("", encoding="utf-8")
    assert ag.stop_flag_file.exists()

    detected = ag._check_stop_flag()

    assert detected is True
    assert ag.shutdown_requested is True
    assert not ag.stop_flag_file.exists(), "stop.flag must be deleted so it does not linger for next startup"


def test_check_stop_flag_not_residual_after_detection(tmp_path):
    """After a detected stop, a fresh check returns False (flag already consumed)."""
    ag = _make_agent_for_stopflag(tmp_path)
    ag.stop_flag_file.parent.mkdir(parents=True, exist_ok=True)
    ag.stop_flag_file.write_text("", encoding="utf-8")

    assert ag._check_stop_flag() is True   # first: detects + deletes
    ag.shutdown_requested = False          # reset only the flag to prove file is gone
    assert ag._check_stop_flag() is False  # second: nothing left to detect


@pytest.mark.asyncio
async def test_run_loop_breaks_on_stop_flag(tmp_path):
    """The main run() loop must detect stop.flag and exit gracefully (state saved),
    without running a cycle, using the 1s-tick check (no real waiting)."""
    ag = _make_agent_for_stopflag(tmp_path)
    # Pre-create the flag so the loop's entry check trips immediately.
    ag.stop_flag_file.parent.mkdir(parents=True, exist_ok=True)
    ag.stop_flag_file.write_text("", encoding="utf-8")

    from unittest.mock import AsyncMock
    ag._run_cycle = AsyncMock(return_value={})
    ag.state = MagicMock()

    with (
        patch("core.agent.should_skip_cycle", return_value=(False, "")),
        patch("core.agent.get_current_interval", return_value=300),
    ):
        await ag.run()

    # Loop exited without running a cycle; flag consumed; state persisted on shutdown.
    ag._run_cycle.assert_not_called()
    assert ag.shutdown_requested is True
    assert not ag.stop_flag_file.exists()
    ag.state.save.assert_called()


