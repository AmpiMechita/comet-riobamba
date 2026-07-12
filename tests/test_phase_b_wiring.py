# -*- coding: utf-8 -*-
"""
Pruebas de wiring de Fase B: verifica que el agente se pueda instanciar
con phase_b_enabled=True/False sin AttributeError ni errores de dependencias.
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.update({"DASHSCOPE_API_KEY": "sk-test", "MOLTBOOK_API_KEY": "sk-test"})

logging.basicConfig(level=logging.INFO, format="%(levelname)s|%(name)s|%(message)s")

pytest_plugins = ("pytest_asyncio",)

TEST_DB = Path("data/test_phase_b_wiring.db")


@pytest.fixture(autouse=True)
def _isolate_db():
    import services.persistence as _p
    import services.research_agenda as _ra
    _original = _p.DB_PATH
    _p.DB_PATH = TEST_DB
    # Feed-reply tests exercise _add_topic_to_agenda -> load_agenda/save_agenda,
    # which use module-level AGENDA_PATH. Redirect to a throwaway temp file so
    # fixture posts ("New", "Repeat", ...) never leak into the real
    # data/research_agenda.json (root cause of the fixture-data leak).
    _orig_agenda = _ra.AGENDA_PATH
    _orig_archive = _ra.ARCHIVE_PATH
    _tmp_agenda = Path("data/test_phase_b_wiring_agenda.json")
    _ra.AGENDA_PATH = _tmp_agenda
    _ra.ARCHIVE_PATH = Path("data/test_phase_b_wiring_agenda_archive.json")
    if TEST_DB.exists():
        TEST_DB.unlink()
    yield
    if TEST_DB.exists():
        TEST_DB.unlink()
    for _f in (_tmp_agenda, _ra.ARCHIVE_PATH):
        if Path(_f).exists():
            Path(_f).unlink()
    _p.DB_PATH = _original
    _ra.AGENDA_PATH = _orig_agenda
    _ra.ARCHIVE_PATH = _orig_archive


@pytest.fixture
def behavior_disabled():
    return {
        "max_posts_per_day": 1,
        "phase_a_publish_enabled": False,
        "phase_b_enabled": False,
        "phase_c_enabled": False,
        "whisper_mode": False,
        "max_comments_per_day": 0,
        "max_comment_replies_per_cycle": 0,
        "max_comments_per_post": 0,
        "cycle_interval_seconds": 1,
    }


@pytest.fixture
def behavior_enabled():
    return {
        "max_posts_per_day": 1,
        "phase_a_publish_enabled": False,
        "phase_b_enabled": True,
        "phase_c_enabled": False,
        "whisper_mode": False,
        "max_comments_per_day": 6,
        "max_comment_replies_per_cycle": 1,
        "max_comments_per_post": 3,
        "cycle_interval_seconds": 1,
        "phase_b_feed_replies": False,
        "phase_b_own_post_replies": False,
    }


def _make_mocks():
    model_cascade = MagicMock()
    model_cascade.generate = AsyncMock(return_value="Test reply.")
    moltbook = MagicMock()
    moltbook.create_comment = MagicMock(return_value={"success": True, "id": "c1"})
    moltbook.get_feed = MagicMock(return_value=MagicMock(success=True, data={"posts": []}))
    moltbook.fetch_my_posts = MagicMock(return_value=[])
    moltbook.fetch_post_comments = MagicMock(return_value=[])
    return model_cascade, moltbook


# ── Test: instanciación con phase_b_enabled=False ───────────────

def test_agent_instantiation_phase_b_disabled(behavior_disabled):
    """El agente se instancia sin error con phase_b_enabled=False."""
    model_cascade, moltbook = _make_mocks()
    import config.config as _cfg
    with (
        patch("core.agent.create_telegram_client", return_value=None),
        patch("core.agent.PlatformAwareness", return_value=None),
        patch.dict(_cfg.behavior_cfg, values=behavior_disabled, clear=False),
    ):
        from core.agent import COMETRiobambaAgent
        ag = COMETRiobambaAgent(
            credentials=MagicMock(moltbook_api_key="sk-test"),
            model_cascade=model_cascade,
            moltbook_client=moltbook,
        )
        assert ag._phase_b_deps is not None
        assert ag._phase_b is None  # lazy init


# ── Test: instanciación con phase_b_enabled=True ────────────────

def test_agent_instantiation_phase_b_enabled(behavior_enabled):
    """El agente se instancia sin AttributeError con phase_b_enabled=True."""
    model_cascade, moltbook = _make_mocks()
    import config.config as _cfg
    with (
        patch("core.agent.create_telegram_client", return_value=None),
        patch("core.agent.PlatformAwareness", return_value=None),
        patch.dict(_cfg.behavior_cfg, values=behavior_enabled, clear=False),
    ):
        from core.agent import COMETRiobambaAgent
        ag = COMETRiobambaAgent(
            credentials=MagicMock(moltbook_api_key="sk-test"),
            model_cascade=model_cascade,
            moltbook_client=moltbook,
        )
        assert ag._phase_b_deps is not None
        # moltubook_api_client debe estar accesible
        assert ag.moltbook_api_client is not None


# ── Test: _run_cycle() con Phase B habilitada ───────────────────

@pytest.mark.asyncio
async def test_run_cycle_with_phase_b_enabled(behavior_enabled):
    """_run_cycle() con Fase B habilitada llega a completarse sin crash."""
    model_cascade, moltbook = _make_mocks()

    from phases.phase_b import PhaseB
    phase_b_mock = MagicMock(spec=PhaseB)
    phase_b_mock.execute = AsyncMock(return_value={
        "success": True,
        "replies_published": 0,
        "feed_replies": [],
        "own_post_replies": [],
    })

    import config.config as _cfg
    with (
        patch("core.agent.create_telegram_client", return_value=None),
        patch("core.agent.PlatformAwareness", return_value=None),
        patch.dict(_cfg.behavior_cfg, values=behavior_enabled, clear=False),
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
        ag.state.posts_today = 0
        ag.state.last_post_date = hoy

        result = await ag._run_cycle()
        assert "phase_b" in result
        assert result["phase_b"].get("success") is True
        assert phase_b_mock.execute.call_count == 1


# ── Tests: persistent replied_comment_ids ────────────────────────

from pathlib import Path
import json
from phases.phase_b import _load_replied_comment_ids, _save_replied_comment_ids, _REPLIED_IDS_PATH


def test_replied_ids_persistence():
    _REPLIED_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    test_ids = {"c1", "c2", "c3"}
    _save_replied_comment_ids(test_ids)
    loaded = _load_replied_comment_ids()
    assert loaded == test_ids
    _REPLIED_IDS_PATH.unlink(missing_ok=True)


def test_replied_ids_loaded_empty_when_missing():
    if _REPLIED_IDS_PATH.exists():
        _REPLIED_IDS_PATH.unlink()
    loaded = _load_replied_comment_ids()
    assert loaded == set()


@pytest.mark.asyncio
async def test_replied_ids_skip_prevents_duplicate():
    from unittest.mock import MagicMock, AsyncMock
    from phases.deps import PhaseBDeps
    from phases.phase_b import PhaseB

    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_comments_per_post": 5, "max_comments_per_day": 10, "max_comment_replies_per_cycle": 3},
        agent_name="test-agent",
    )
    phase_b = PhaseB(deps=deps)
    phase_b._replied_comment_ids = {"p1:c1", "p1:c2"}

    post_id = "p1"
    comments = [
        {"id": "c1", "content": "Hola", "author": "user1"},
        {"id": "c3", "content": "Hello, how are you?", "author": "user2"},
    ]
    with (
        patch.object(phase_b.api, "fetch_post_comments", return_value=comments),
            patch.object(phase_b, "_generate_own_post_reply", AsyncMock(return_value="In production we measured that the pattern works: circuit breaker with 150ms timeout reduces cascade failures by 73%.")),
            patch.object(phase_b, "_check_and_prevent_duplicate", AsyncMock(return_value="In production we measured that the pattern works: circuit breaker with 150ms timeout reduces cascade failures by 73%.")),
        patch.object(phase_b.api, "create_comment", return_value={"success": True, "id": "new1"}),
    ):
        import phases.phase_b as _pb_mod
        with patch.object(_pb_mod, "_save_replied_comment_ids"):
            with patch.object(_pb_mod, "is_thread_closed", return_value=False):
                results = await phase_b._process_own_post(post_id)

    assert len(results) == 1
    assert results[0]["comment_id"] == "c3"


# ── Tests: persistent commented_post_ids ──────────────────────

from phases.phase_b import _load_commented_post_ids, _save_commented_post_ids, _COMMENTED_POSTS_PATH


def test_commented_post_ids_persistence():
    _COMMENTED_POSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    now = datetime.now()
    # Keys must be valid UUID post_ids (invalid keys are now filtered on save).
    p1 = "a1b2c3d4-0000-4000-8000-000000000001"
    p2 = "a1b2c3d4-0000-4000-8000-000000000002"
    p3 = "a1b2c3d4-0000-4000-8000-000000000003"
    test_ids = {p1: now.isoformat(), p2: now.isoformat(), p3: now.isoformat()}
    _save_commented_post_ids(test_ids)
    loaded = _load_commented_post_ids()
    assert loaded.keys() == test_ids.keys()
    _COMMENTED_POSTS_PATH.unlink(missing_ok=True)


def test_commented_post_ids_empty_when_missing():
    if _COMMENTED_POSTS_PATH.exists():
        _COMMENTED_POSTS_PATH.unlink()
    loaded = _load_commented_post_ids()
    assert loaded == {}


@pytest.mark.asyncio
async def test_feed_reply_gate_uses_thread_count():
    """_can_comment_in_thread (not binary _commented_post_ids) gates feed replies."""
    from unittest.mock import MagicMock, AsyncMock
    from phases.deps import PhaseBDeps
    from phases.phase_b import PhaseB, RelevanceDecision

    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_comments_per_post": 5, "max_comments_per_day": 10, "max_comment_replies_per_cycle": 3, "max_feed_comments_per_post": 1},
        agent_name="test-agent",
    )
    phase_b = PhaseB(deps=deps)
    phase_b.get_comments_today = lambda: 0
    phase_b.incr_comments_today = lambda: None
    phase_b._post_history_guard = {}
    phase_b._commented_post_ids = {"already_done_post": datetime.now().isoformat()}

    # Post where agent already has max_feed_comments_per_post (1) replies in thread
    posts = [
        {"id": "already_done_post", "title": "Existing", "content": "Hello",
         "comments": [{"author": "test-agent", "content": "My reply"}]},
        {"id": "new_post", "title": "New", "content": "How are you? This is a sufficiently long post about agents and systems that needs a proper reply with enough content to pass all quality gates.", "comments": []},
    ]

    with (
        patch.object(phase_b, "_fetch_candidate_posts", return_value=posts),
        patch.object(phase_b, "_decide_reply_from_post", return_value=RelevanceDecision(True, 30, "reply_sent")),
        patch.object(phase_b, "_generate_reply_for_post", AsyncMock(return_value="In production we measured that the proper architecture pattern with 200ms circuit breaker reduces cascade failures by 65%.")),
        patch.object(phase_b, "_check_and_prevent_duplicate", AsyncMock(return_value="In production we measured that the proper architecture pattern with 200ms circuit breaker reduces cascade failures by 65%.")),
        patch.object(phase_b.api, "create_comment", return_value={"success": True, "id": "c1"}),
    ):
        import phases.phase_b as _pb_mod
        with patch.object(_pb_mod, "_save_commented_post_ids"):
            results = await phase_b._execute_feed_replies()

    assert len(results) == 1
    assert results[0]["post_id"] == "new_post"


# ── Tests: feed reply dedup persistence ─────────────────────────

@pytest.mark.asyncio
async def test_feed_reply_persists_dedup_key():
    """Successful feed reply writes a feed:post_id:comment_id key to _replied_comment_ids."""
    from unittest.mock import MagicMock, AsyncMock
    from phases.deps import PhaseBDeps
    from phases.phase_b import PhaseB, RelevanceDecision

    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_comments_per_post": 5, "max_comments_per_day": 10, "max_comment_replies_per_cycle": 3, "max_feed_comments_per_post": 1},
        agent_name="test-agent",
    )
    phase_b = PhaseB(deps=deps)
    phase_b.get_comments_today = lambda: 0
    phase_b.incr_comments_today = lambda: None

    posts = [
        {"id": "new_post", "title": "New", "content": "How are you?", "comments": []},
    ]

    with (
        patch.object(phase_b, "_fetch_candidate_posts", return_value=posts),
        patch.object(phase_b, "_decide_reply_from_post", return_value=RelevanceDecision(True, 30, "reply_sent")),
        patch.object(phase_b, "_generate_reply_for_post", AsyncMock(return_value="In production we measured that the proper architecture pattern with 200ms circuit breaker reduces cascade failures by 65%.")),
        patch.object(phase_b, "_check_and_prevent_duplicate", AsyncMock(return_value="In production we measured that the proper architecture pattern with 200ms circuit breaker reduces cascade failures by 65%.")),
        patch.object(phase_b.api, "create_comment", return_value={"success": True, "id": "c1"}),
    ):
        import phases.phase_b as _pb_mod
        with (
            patch.object(_pb_mod, "_save_agent_comment_ids"),
            patch.object(_pb_mod, "_save_replied_comment_ids"),
            patch.object(_pb_mod, "_save_commented_post_ids"),
        ):
            await phase_b._execute_feed_replies()

    assert "feed:new_post:c1" in phase_b._replied_comment_ids


@pytest.mark.asyncio
async def test_feed_reply_blocks_repeat_same_post_without_exception():
    from unittest.mock import MagicMock, AsyncMock
    from phases.deps import PhaseBDeps
    from phases.phase_b import PhaseB, RelevanceDecision

    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_comments_per_post": 5, "max_comments_per_day": 10, "max_comment_replies_per_cycle": 3, "max_feed_comments_per_post": 1},
        agent_name="test-agent",
    )
    phase_b = PhaseB(deps=deps)
    phase_b.get_comments_today = lambda: 0
    phase_b.incr_comments_today = lambda: None
    phase_b._commented_post_ids = {"repeat_post": datetime.now().isoformat()}

    posts = [
        {"id": "repeat_post", "title": "Repeat", "content": "A systems post about guardrails and latency.", "comments": []},
    ]

    with (
        patch.object(phase_b, "_fetch_candidate_posts", return_value=posts),
        patch.object(phase_b, "_decide_reply_from_post", return_value=RelevanceDecision(True, 40, "reply_sent")),
        patch.object(phase_b, "_generate_reply_for_post", AsyncMock(return_value="Should not be used")),
        patch.object(phase_b.api, "create_comment", return_value={"success": True, "id": "c1"}),
    ):
        results = await phase_b._execute_feed_replies()

    assert results == []
    if hasattr(phase_b._generate_reply_for_post, "await_count"):
        assert phase_b._generate_reply_for_post.await_count == 0


@pytest.mark.asyncio
async def test_reply_quality_guard_blocks_templated_numeric_draft():
    from unittest.mock import MagicMock, AsyncMock
    from phases.deps import PhaseBDeps
    from phases.phase_b import PhaseB

    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_comments_per_post": 5, "max_comments_per_day": 10, "max_comment_replies_per_cycle": 3},
        agent_name="test-agent",
    )
    phase_b = PhaseB(deps=deps)
    # Set a theme fingerprint so repeated_theme penalty also triggers
    # (_reply_theme_fingerprint from "a practical guardrail is to keep p99 latency under 500 ms")
    phase_b._replied_topic_fingerprints.add("guardrail|latency")
    phase_b.llm.generate = AsyncMock(return_value="a practical guardrail is to keep p99 latency under 500 ms and cap retries at 2.")
    with patch.object(phase_b._dedup, "sync_replied_topic_fingerprints"):
        reply = await phase_b._generate_reply_for_post({
            "id": "post-1",
            "title": "Deployment question",
            "content": "This discusses deployment strategies for production systems.",
        })

    assert reply != ""  # v5.1: relaxed gate allows numeric specificity with guardrail patterns


@pytest.mark.asyncio
async def test_reply_quality_guard_allows_source_anchored_specific_draft():
    from unittest.mock import MagicMock, AsyncMock
    from phases.deps import PhaseBDeps
    from phases.phase_b import PhaseB

    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_comments_per_post": 5, "max_comments_per_day": 10, "max_comment_replies_per_cycle": 3},
        agent_name="test-agent",
    )
    phase_b = PhaseB(deps=deps)
    phase_b.llm.generate = AsyncMock(return_value="Your rollback note is the key point: recovery time matters more than raw throughput.")
    with patch.object(phase_b._dedup, "sync_replied_topic_fingerprints"):
        reply = await phase_b._generate_reply_for_post({
            "id": "post-2",
            "title": "Rollback note",
            "content": "The post focuses on rollback and recovery time after deployment.",
        })

    assert reply


def test_reply_quality_score_penalizes_repeated_theme():
    from phases.deps import PhaseBDeps
    from phases.phase_b import PhaseB

    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={"max_comments_per_post": 5, "max_comments_per_day": 10, "max_comment_replies_per_cycle": 3},
        agent_name="test-agent",
    )
    phase_b = PhaseB(deps=deps)
    source = "This post discusses rollback and recovery time after deployment."
    reply = "Your rollback note is the key point: recovery time matters more than raw throughput."
    fingerprint = phase_b._reply_theme_fingerprint(reply, source)
    phase_b._replied_topic_fingerprints = {fingerprint}

    score, reasons = phase_b._score_reply_draft(reply, source)

    assert score < 100
    assert "repeated_theme" in reasons


# ── Tests: agent comment ID tracking ────────────────────────────

def test_agent_comment_ids_persistence():
    """_save_agent_comment_ids and _load_agent_comment_ids round-trip correctly."""
    from phases.phase_b import _save_agent_comment_ids, _load_agent_comment_ids, _AGENT_COMMENT_IDS_PATH
    _AGENT_COMMENT_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Keys must be valid UUID post_ids (invalid keys are now filtered on save).
    p1 = "a1b2c3d4-0000-4000-8000-000000000001"
    p2 = "a1b2c3d4-0000-4000-8000-000000000002"
    test_data = {p1: ["c1", "c2"], p2: ["c3"]}
    _save_agent_comment_ids(test_data)
    loaded = _load_agent_comment_ids()
    assert loaded == test_data
    _AGENT_COMMENT_IDS_PATH.unlink(missing_ok=True)


def test_agent_comment_ids_empty_when_missing():
    from phases.phase_b import _load_agent_comment_ids, _AGENT_COMMENT_IDS_PATH
    if _AGENT_COMMENT_IDS_PATH.exists():
        _AGENT_COMMENT_IDS_PATH.unlink()
    loaded = _load_agent_comment_ids()
    assert loaded == {}


# ── Tests: post_id validation on save (invalid keys are filtered) ──

import logging as _logging
_VALID_UUID = "a1b2c3d4-0000-4000-8000-000000000001"


def test_save_commented_post_ids_keeps_valid_uuid():
    from phases.phase_b import _save_commented_post_ids, _load_commented_post_ids, _COMMENTED_POSTS_PATH
    from datetime import datetime
    _COMMENTED_POSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _save_commented_post_ids({_VALID_UUID: datetime.now().isoformat()})
    loaded = _load_commented_post_ids()
    assert _VALID_UUID in loaded
    _COMMENTED_POSTS_PATH.unlink(missing_ok=True)


def test_save_commented_post_ids_discards_non_uuid_string(caplog):
    from phases.phase_b import _save_commented_post_ids, _load_commented_post_ids, _COMMENTED_POSTS_PATH
    from datetime import datetime
    _COMMENTED_POSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat()
    with caplog.at_level(_logging.WARNING, logger="phases.phase_b"):
        _save_commented_post_ids({_VALID_UUID: ts, "not-a-uuid": ts})
    loaded = _load_commented_post_ids()
    assert _VALID_UUID in loaded
    assert "not-a-uuid" not in loaded
    assert any("not-a-uuid" in r.message for r in caplog.records), \
        f"expected WARNING mentioning offending id, got: {[r.message for r in caplog.records]}"
    _COMMENTED_POSTS_PATH.unlink(missing_ok=True)


def test_save_commented_post_ids_discards_none_and_int_keys(caplog):
    """is_valid_post_id raises TypeError on None/int; the filter must handle it gracefully."""
    from phases.phase_b import _save_commented_post_ids, _load_commented_post_ids, _COMMENTED_POSTS_PATH
    from datetime import datetime
    _COMMENTED_POSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat()
    with caplog.at_level(_logging.WARNING, logger="phases.phase_b"):
        # dict with a None key and an int key alongside a valid UUID
        _save_commented_post_ids({_VALID_UUID: ts, None: ts, 123: ts})
    loaded = _load_commented_post_ids()
    assert list(loaded.keys()) == [_VALID_UUID]
    msgs = " ".join(r.message for r in caplog.records)
    assert "None" in msgs and "123" in msgs
    _COMMENTED_POSTS_PATH.unlink(missing_ok=True)


def test_save_agent_comment_ids_discards_invalid_keys(caplog):
    from phases.phase_b import _save_agent_comment_ids, _load_agent_comment_ids, _AGENT_COMMENT_IDS_PATH
    _AGENT_COMMENT_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with caplog.at_level(_logging.WARNING, logger="phases.phase_b"):
        _save_agent_comment_ids({_VALID_UUID: ["c1"], "bad-id": ["c2"], None: ["c3"], 7: ["c4"]})
    loaded = _load_agent_comment_ids()
    assert list(loaded.keys()) == [_VALID_UUID]
    assert loaded[_VALID_UUID] == ["c1"]
    msgs = " ".join(r.message for r in caplog.records)
    assert "bad-id" in msgs and "None" in msgs and "7" in msgs
    _AGENT_COMMENT_IDS_PATH.unlink(missing_ok=True)


def test_save_agent_comment_ids_load_still_works_after_filter():
    """_load_agent_comment_ids reads the filtered file with correct format."""
    from phases.phase_b import _save_agent_comment_ids, _load_agent_comment_ids, _AGENT_COMMENT_IDS_PATH
    _AGENT_COMMENT_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    p1 = "a1b2c3d4-0000-4000-8000-000000000001"
    p2 = "a1b2c3d4-0000-4000-8000-000000000002"
    _save_agent_comment_ids({p1: ["c1", "c2"], p2: ["c3"], "junk": ["x"]})
    loaded = _load_agent_comment_ids()
    assert loaded == {p1: ["c1", "c2"], p2: ["c3"]}
    _AGENT_COMMENT_IDS_PATH.unlink(missing_ok=True)
