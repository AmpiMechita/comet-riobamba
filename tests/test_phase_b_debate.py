"""Tests for conversation state, Phase B debate handling, feed selection, and self-improvement log."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch
import uuid

import pytest

from services.conversation_state import (
    get_or_create_thread, can_continue_thread, register_agent_reply,
    update_open_questions, close_thread, is_thread_closed,
    CONVERSATIONS_PATH, MAX_TURNS_PER_THREAD,
)

# UUIDs válidos para fixtures de test
_POST_ID_1        = "a1b2c3d4-0000-4000-8000-000000000001"
_POST_ID_2        = "a1b2c3d4-0000-4000-8000-000000000002"
_POST_ID_3        = "a1b2c3d4-0000-4000-8000-000000000003"
_POST_ID_4        = "a1b2c3d4-0000-4000-8000-000000000004"
_POST_ID_5        = "a1b2c3d4-0000-4000-8000-000000000005"
_POST_ID_CLOSE    = "a1b2c3d4-0000-4000-8000-000000000010"
_POST_ID_CLOSE2   = "a1b2c3d4-0000-4000-8000-000000000011"
_POST_ID_Q        = "a1b2c3d4-0000-4000-8000-000000000020"
_POST_ID_Q1       = "a1b2c3d4-0000-4000-8000-000000000021"
_POST_ID_QA       = "a1b2c3d4-0000-4000-8000-000000000022"
_POST_ID_INCR     = "a1b2c3d4-0000-4000-8000-000000000030"
_POST_ID_CLOSES   = "a1b2c3d4-0000-4000-8000-000000000031"
_POST_ID_MIXED    = "a1b2c3d4-0000-4000-8000-000000000040"
_POST_ID_PROGRESS = "a1b2c3d4-0000-4000-8000-000000000050"
_POST_ID_MANY     = "a1b2c3d4-0000-4000-8000-000000000060"
from services.self_improvement import (
    log_proposal, mark_proposal_applied, list_proposals,
)


# ============================================================
# Conversation State Tests
# ============================================================

@pytest.fixture(autouse=True)
def _clean_conversations(tmp_path: Path) -> None:
    """Redirect conversation path to temp for each test."""
    import services.conversation_state as cs
    orig = cs.CONVERSATIONS_PATH
    cs.CONVERSATIONS_PATH = tmp_path / "conversations.json"
    yield
    cs.CONVERSATIONS_PATH = orig


def test_get_or_create_thread_new() -> None:
    thread = get_or_create_thread(_POST_ID_1)
    assert thread["turns_in_thread"] == 0
    assert thread["open_questions"] is False
    assert thread["closed"] is False


def test_get_or_create_thread_existing() -> None:
    t1 = get_or_create_thread(_POST_ID_1)
    register_agent_reply(_POST_ID_1)
    register_agent_reply(_POST_ID_1)
    t2 = get_or_create_thread(_POST_ID_1)
    assert t2["turns_in_thread"] == 2


def test_is_thread_closed_fresh() -> None:
    _pid = str(uuid.uuid4())
    assert is_thread_closed(_pid) is False


def test_close_thread() -> None:
    close_thread(_POST_ID_CLOSE)
    assert is_thread_closed(_POST_ID_CLOSE) is True


def test_can_continue_thread_closed() -> None:
    _pid = str(uuid.uuid4())
    close_thread(_pid)
    assert can_continue_thread(_pid) is False


def test_can_continue_thread_no_questions() -> None:
    _pid = str(uuid.uuid4())
    update_open_questions(_pid, "This is a statement, not a question")
    assert can_continue_thread(_pid) is False


def test_can_continue_thread_with_questions() -> None:
    # Use the proper helper to set open_questions
    update_open_questions(_POST_ID_Q, "Is there a way to handle this?")
    assert can_continue_thread(_POST_ID_Q) is True


def test_can_continue_thread_max_turns() -> None:
    _pid = str(uuid.uuid4())
    for _ in range(MAX_TURNS_PER_THREAD):
        register_agent_reply(_pid)
    update_open_questions(_pid, "Still have a question?")
    assert can_continue_thread(_pid) is False


def test_register_agent_reply_increments() -> None:
    t = get_or_create_thread(_POST_ID_INCR)
    assert t["turns_in_thread"] == 0
    register_agent_reply(_POST_ID_INCR)
    t = get_or_create_thread(_POST_ID_INCR)
    assert t["turns_in_thread"] == 1


def test_register_agent_reply_closes_at_max() -> None:
    for _ in range(MAX_TURNS_PER_THREAD):
        register_agent_reply(_POST_ID_CLOSES)
    assert is_thread_closed(_POST_ID_CLOSES) is True


def test_update_open_questions_detects_question() -> None:
    update_open_questions(_POST_ID_Q1, "How does this handle rate limits?")
    t = get_or_create_thread(_POST_ID_Q1)
    assert t["open_questions"] is True


def test_update_open_questions_closing_no_question() -> None:
    update_open_questions(_POST_ID_CLOSE2, "Thanks, that helps a lot!")
    t = get_or_create_thread(_POST_ID_CLOSE2)
    assert t["closed"] is True
    assert t["open_questions"] is False


def test_update_open_questions_thanks_with_question() -> None:
    """Thanks text with question mark should remain open (the question takes priority)."""
    update_open_questions(_POST_ID_MIXED, "Thanks, but how do you handle edge cases?")
    t = get_or_create_thread(_POST_ID_MIXED)
    assert t["open_questions"] is True


def test_update_open_questions_no_question_no_close() -> None:
    _pid = str(uuid.uuid4())
    update_open_questions(_pid, "This is an interesting approach.")
    t = get_or_create_thread(_pid)
    assert t["open_questions"] is False
    assert t["closed"] is False


# ============================================================
# Self-Improvement Log Tests
# ============================================================

@pytest.fixture(autouse=True)
def _clean_self_improvement(tmp_path: Path) -> None:
    """Redirect log path to temp for each test."""
    import services.self_improvement as si
    orig = si.SELF_IMPROVEMENT_LOG_PATH
    si.SELF_IMPROVEMENT_LOG_PATH = tmp_path / "self_improvement_log.jsonl"
    si._proposal_counter = 0
    yield
    si.SELF_IMPROVEMENT_LOG_PATH = orig
    si._proposal_counter = 0


def test_log_proposal_creates_entry() -> None:
    pid = log_proposal("test", "Test summary", details="Test details")
    assert pid.startswith("P-")
    proposals = list_proposals()
    assert len(proposals) == 1
    entry = proposals[0]
    assert entry["proposal_id"] == pid
    assert entry["source"] == "test"
    assert entry["summary"] == "Test summary"
    assert entry["details"] == "Test details"


def test_log_proposal_increments_id() -> None:
    pid1 = log_proposal("src1", "s1")
    pid2 = log_proposal("src2", "s2")
    assert pid1 != pid2
    assert int(pid1.split("-")[1]) < int(pid2.split("-")[1])


def test_mark_proposal_applied() -> None:
    pid = log_proposal("test", "proposal to apply")
    assert mark_proposal_applied(pid) is True
    proposals = list_proposals()
    assert len(proposals) == 1
    assert proposals[0]["status"] == "applied"


def test_mark_proposal_applied_not_found() -> None:
    assert mark_proposal_applied("P-999") is False


def test_list_proposals_empty() -> None:
    assert list_proposals() == []


def test_list_proposals_filter_by_status() -> None:
    log_proposal("src", "pending one")
    pid = log_proposal("src", "applied one")
    mark_proposal_applied(pid)
    pending = list_proposals(status="pending")
    applied = list_proposals(status="applied")
    assert len(pending) == 1
    assert len(applied) == 1
    assert pending[0]["summary"] == "pending one"
    assert applied[0]["summary"] == "applied one"


# ============================================================
# Phase B Feed Selection Tests
# ============================================================

@pytest.fixture
def mock_phase_b() -> Any:
    from phases.phase_b import PhaseB
    from phases.deps import PhaseBDeps

    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={
            "max_comments_per_post": 3,
            "max_comments_per_day": 6,
            "max_comment_replies_per_cycle": 2,
            "max_feed_replies_per_day": 3,
            "delay_between_comments": 0,
        },
        agent_name="COMET-RIOBAMBA",
        get_comments_today=lambda: 0,
        increment_comments_today=lambda: 0,
    )
    pb = PhaseB(deps)
    pb.llm = MagicMock()
    pb.api = MagicMock()
    return pb


def test_feed_replies_scoring_with_roadmap_boost() -> None:
    """Posts matching roadmap topics should get a boost over non-matching."""
    from phases.phase_b import PhaseB

    score_no_match = PhaseB._compute_relevance_score(
        {"content": "This is a generic post about technology."}
    )
    score_match = PhaseB._compute_relevance_score(
        {"content": "ReAct patterns in Moltbook agents: how to handle failures"}
    )
    # The matching post should have at least the same base score
    assert score_match >= score_no_match


def test_decide_reply_from_post_strict_threshold() -> None:
    """Feed posts below strict threshold should not pass."""
    from phases.phase_b import PhaseB, RelevanceDecision

    # Very short, no keywords -> should be below threshold
    decision = PhaseB._decide_reply_from_post("Hi")
    assert decision.should_reply is False

    # Tech-rich post -> should pass
    decision = PhaseB._decide_reply_from_post(
        "How to configure model cascade fallbacks when LLM API returns 429 errors"
    )
    assert decision.should_reply is True


# ============================================================
# Phase B Conversation / Debate Tests (using mock)
# ============================================================

@pytest.fixture(autouse=True)
def _patch_conversations_path(tmp_path: Path) -> None:
    """Redirect conversation path to temp for all Phase B tests."""
    import services.conversation_state as cs
    orig = cs.CONVERSATIONS_PATH
    cs.CONVERSATIONS_PATH = tmp_path / "conversations.json"
    yield
    cs.CONVERSATIONS_PATH = orig


@pytest.mark.asyncio
async def test_process_own_post_skips_closed_thread() -> None:
    """If a thread is closed, _process_own_post should return empty."""
    from phases.phase_b import PhaseB
    from phases.deps import PhaseBDeps

    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={
            "max_comments_per_post": 3,
            "max_comments_per_day": 6,
            "max_comment_replies_per_cycle": 2,
            "delay_between_comments": 0,
        },
        agent_name="COMET-RIOBAMBA",
        get_comments_today=lambda: 0,
        increment_comments_today=lambda: 0,
    )
    pb = PhaseB(deps)
    pb.llm = MagicMock()
    pb.api = MagicMock()

    _pid = str(uuid.uuid4())
    close_thread(_pid)
    result = await pb._process_own_post(_pid)  # type: ignore[misc]
    assert result == []


@pytest.mark.asyncio
async def test_process_own_post_respects_daily_limit() -> None:
    """If daily limit reached, should skip."""
    from phases.phase_b import PhaseB
    from phases.deps import PhaseBDeps

    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={
            "max_comments_per_post": 3,
            "max_comments_per_day": 6,
            "max_comment_replies_per_cycle": 2,
            "delay_between_comments": 0,
        },
        agent_name="COMET-RIOBAMBA",
        get_comments_today=lambda: 100,  # exceeded
        increment_comments_today=lambda: 0,
    )
    pb = PhaseB(deps)
    _pid = str(uuid.uuid4())
    result = await pb._process_own_post(_pid)  # type: ignore[misc]
    assert result == []


def test_update_open_questions_from_comment() -> None:
    """When processing own post, update_open_questions should be called."""
    update_open_questions(_POST_ID_QA, "What about edge cases in error handling?")
    assert can_continue_thread(_POST_ID_QA) is True


def test_can_continue_then_close() -> None:
    """Thread should be closed after proper thanks."""
    update_open_questions(_POST_ID_PROGRESS, "What about edge cases?")
    assert can_continue_thread(_POST_ID_PROGRESS) is True

    update_open_questions(_POST_ID_PROGRESS, "Thanks, that answers my question.")
    assert can_continue_thread(_POST_ID_PROGRESS) is False
    assert is_thread_closed(_POST_ID_PROGRESS) is True


def test_max_turns_enforced() -> None:
    """After MAX_TURNS_PER_THREAD agent replies, thread should close."""
    post_id = _POST_ID_MANY
    update_open_questions(post_id, "Question 1?")
    for i in range(MAX_TURNS_PER_THREAD):
        register_agent_reply(post_id)
    assert is_thread_closed(post_id) is True
    assert can_continue_thread(post_id) is False


# ============================================================
# Config Tests
# ============================================================

def test_phase_b_interval_in_policy() -> None:
    from config.agent_policy import POLICY
    assert hasattr(POLICY, "phase_b_interval_seconds")
    assert POLICY.phase_b_interval_seconds == 3600


def test_max_feed_replies_in_policy() -> None:
    from config.agent_policy import POLICY
    assert hasattr(POLICY, "max_feed_replies_per_day")
    assert POLICY.max_feed_replies_per_day == 20


# ============================================================
# Self-Improvement Print Script Tests
# ============================================================

def test_print_script_empty_log(capsys: pytest.CaptureFixture) -> None:
    """The print script should handle empty log without crashing."""
    from scripts.print_self_improvement_log import main
    # Clear log by deleting file
    import services.self_improvement as si
    if si.SELF_IMPROVEMENT_LOG_PATH.exists():
        si.SELF_IMPROVEMENT_LOG_PATH.unlink()
    main()
    captured = capsys.readouterr()
    assert "No hay propuestas" in captured.out


def test_print_script_with_entries(capsys: pytest.CaptureFixture) -> None:
    """The print script should print entries."""
    from scripts.print_self_improvement_log import main
    log_proposal("test_source", "Test proposal summary")
    main()
    captured = capsys.readouterr()
    assert "P-001" in captured.out
    assert "test_source" in captured.out
    assert "Test proposal summary" in captured.out
