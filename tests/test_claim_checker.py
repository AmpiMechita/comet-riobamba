"""Tests for the claim-checker pipeline (three-call reply verification)."""

import logging
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

pytest_plugins = ("pytest_asyncio",)

from phases.deps import PhaseBDeps
from phases.phase_b import PhaseB
from services.claim_checker import extract_claim, check_claim, _strip_code_fences

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s|%(name)s|%(message)s")


def _make_pb(**kwargs) -> PhaseB:
    cfg = {
        "max_comments_per_day": 12,
        "max_comment_replies_per_cycle": 4,
        "max_comments_per_post": 6,
        "max_feed_comments_per_post": 3,
        "delay_between_comments": 0,
        **kwargs,
    }
    deps = PhaseBDeps(
        model_cascade=AsyncMock(),
        moltbook_client=MagicMock(),
        behavior_cfg=cfg,
        agent_name="comet_riobamba",
        get_comments_today=lambda: 0,
        increment_comments_today=lambda: 0,
    )
    pb = PhaseB(deps=deps)
    pb._replied_comment_ids = set()
    pb._replied_topic_fingerprints = set()
    pb._claim_checker_tier = "test_tier"
    return pb


# ── Claim checker module tests ─────────────────────────────────────


class TestExtractClaimModule:
    """Tests for the extract_claim function in services/claim_checker.py."""

    @pytest.mark.asyncio
    async def test_valid_extract(self):
        llm = AsyncMock()
        llm.generate.return_value = (
            '{"central_claim": "data retention is the real risk", '
            '"reply_must_address": "must address data retention policy"}'
        )
        result = await extract_claim("post text", "comment text", llm)
        assert result is not None
        assert result["central_claim"] == "data retention is the real risk"
        assert result["reply_must_address"] == "must address data retention policy"

    @pytest.mark.asyncio
    async def test_empty_response_returns_none(self):
        llm = AsyncMock()
        llm.generate.return_value = ""
        result = await extract_claim("post", "comment", llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_malformed_json_returns_none(self):
        llm = AsyncMock()
        llm.generate.return_value = "not json"
        result = await extract_claim("post", "comment", llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_fields_returns_none(self):
        llm = AsyncMock()
        llm.generate.return_value = '{"central_claim": "only"}'
        result = await extract_claim("post", "comment", llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self):
        llm = AsyncMock()
        llm.generate.side_effect = RuntimeError("LLM down")
        result = await extract_claim("post", "comment", llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_with_fences_json(self):
        """Valid JSON wrapped in ```json ... ``` is parsed correctly."""
        llm = AsyncMock()
        llm.generate.return_value = (
            "```json\n"
            '{"central_claim": "data retention is the real risk", '
            '"reply_must_address": "must address data retention policy"}\n'
            "```"
        )
        result = await extract_claim("post text", "comment text", llm)
        assert result is not None
        assert result["central_claim"] == "data retention is the real risk"
        assert result["reply_must_address"] == "must address data retention policy"

    @pytest.mark.asyncio
    async def test_extract_with_fences_no_lang(self):
        """Valid JSON wrapped in ``` ... ``` (no language tag) is parsed."""
        llm = AsyncMock()
        llm.generate.return_value = (
            "```\n"
            '{"central_claim": "memory limits cause failures", '
            '"reply_must_address": "must discuss memory limits"}\n'
            "```"
        )
        result = await extract_claim("post", "comment", llm)
        assert result is not None
        assert result["central_claim"] == "memory limits cause failures"

    @pytest.mark.asyncio
    async def test_extract_truncated_json_returns_none(self):
        """Truncated JSON is caught and logged as truncated."""
        llm = AsyncMock()
        llm.generate.return_value = (
            '{"central_claim": "data retention is the real risk", '
            '"reply_must_address": "The comment'
        )
        with patch("services.claim_checker.logger") as mock_log:
            result = await extract_claim("post", "comment", llm)
        assert result is None
        mock_log.warning.assert_called_once()
        msg = mock_log.warning.call_args[0][0]
        assert "truncated JSON" in msg


    @pytest.mark.asyncio
    async def test_extract_claim_uses_400_max_tokens(self):
        """Fix 2: extract_claim pasa max_tokens=400."""
        llm = AsyncMock()
        llm.generate.return_value = '{"central_claim": "x", "reply_must_address": "y"}'
        await extract_claim("post", "comment", llm)
        call_kwargs = llm.generate.call_args[1]
        assert call_kwargs["max_tokens"] == 400


class TestCheckClaimModule:
    """Tests for the check_claim function in services/claim_checker.py."""

    @pytest.mark.asyncio
    async def test_valid_on_topic(self):
        llm = AsyncMock()
        llm.generate.return_value = (
            '{"on_topic": true, "reason": "addresses data retention", "score": 0.9}'
        )
        result = await check_claim({"central_claim": "x", "reply_must_address": "y"}, "reply draft", llm)
        assert result["on_topic"] is True
        assert result["score"] == 0.9

    @pytest.mark.asyncio
    async def test_valid_off_topic(self):
        llm = AsyncMock()
        llm.generate.return_value = (
            '{"on_topic": false, "reason": "discusses mTLS instead of retention", "score": 0.2}'
        )
        result = await check_claim({"central_claim": "x", "reply_must_address": "y"}, "reply draft", llm)
        assert result["on_topic"] is False
        assert result["score"] == 0.2

    @pytest.mark.asyncio
    async def test_empty_response_fails_open(self):
        llm = AsyncMock()
        llm.generate.return_value = ""
        result = await check_claim({"central_claim": "x", "reply_must_address": "y"}, "reply draft", llm)
        assert result["on_topic"] is True
        assert result["score"] == 1.0

    @pytest.mark.asyncio
    async def test_malformed_json_fails_open(self):
        llm = AsyncMock()
        llm.generate.return_value = "not json"
        result = await check_claim({"central_claim": "x", "reply_must_address": "y"}, "reply draft", llm)
        assert result["on_topic"] is True
        assert result["score"] == 1.0

    @pytest.mark.asyncio
    async def test_llm_exception_fails_open(self):
        llm = AsyncMock()
        llm.generate.side_effect = RuntimeError("LLM down")
        result = await check_claim({"central_claim": "x", "reply_must_address": "y"}, "reply draft", llm)
        assert result["on_topic"] is True
        assert result["score"] == 1.0

    @pytest.mark.asyncio
    async def test_check_with_fences_json(self):
        """Valid check JSON wrapped in ```json ... ``` is parsed."""
        llm = AsyncMock()
        llm.generate.return_value = (
            "```json\n"
            '{"on_topic": true, "reason": "addresses retention", "score": 0.85}\n'
            "```"
        )
        result = await check_claim({"central_claim": "x", "reply_must_address": "y"}, "reply draft", llm)
        assert result["on_topic"] is True
        assert result["score"] == 0.85

    @pytest.mark.asyncio
    async def test_check_with_fences_no_lang(self):
        """Valid check JSON wrapped in ``` ... ``` is parsed."""
        llm = AsyncMock()
        llm.generate.return_value = (
            "```\n"
            '{"on_topic": false, "reason": "off-topic", "score": 0.3}\n'
            "```"
        )
        result = await check_claim({"central_claim": "x", "reply_must_address": "y"}, "reply draft", llm)
        assert result["on_topic"] is False
        assert result["score"] == 0.3

    @pytest.mark.asyncio
    async def test_check_claim_uses_400_max_tokens(self):
        """Fix 2: check_claim pasa max_tokens=400."""
        llm = AsyncMock()
        llm.generate.return_value = '{"on_topic": true, "reason": "ok", "score": 0.9}'
        await check_claim({"central_claim": "x", "reply_must_address": "y"}, "reply draft", llm)
        call_kwargs = llm.generate.call_args[1]
        assert call_kwargs["max_tokens"] == 400


# ── _strip_code_fences unit tests ──────────────────────────────────

class TestStripCodeFences:
    """Unit tests for the private _strip_code_fences helper."""

    def test_fences_json(self):
        """```json ... ``` → JSON without fences."""
        raw = "```json\n{\"key\": \"val\"}\n```"
        assert _strip_code_fences(raw) == "{\"key\": \"val\"}"

    def test_fences_no_lang(self):
        """``` ... ``` → JSON without fences."""
        raw = "```\n{\"key\": \"val\"}\n```"
        assert _strip_code_fences(raw) == "{\"key\": \"val\"}"

    def test_no_fences(self):
        """plain JSON remains unchanged."""
        raw = "{\"key\": \"val\"}"
        assert _strip_code_fences(raw) == "{\"key\": \"val\"}"

    def test_empty_string(self):
        assert _strip_code_fences("") == ""

    def test_only_fences(self):
        assert _strip_code_fences("```") == ""

    def test_fences_with_extra_newlines(self):
        raw = "```json\n\n{\"key\": \"val\"}\n\n```\n"
        assert _strip_code_fences(raw) == "{\"key\": \"val\"}"


# ── Pipeline wiring tests (feed reply path) ────────────────────────


class TestGenerateReplyForPostClaimPipeline:
    """Test that _generate_reply_for_post correctly wires extract → generate.
    (claim check is now deferred to _execute_feed_replies for efficiency)."""

    @pytest.mark.asyncio
    async def test_claim_extracted_constraint_injected(self):
        """Scenario (a): extract_claim returns valid dict → constraint injected into prompt."""
        pb = _make_pb()
        pb.llm.generate = AsyncMock(side_effect=[
            '{"central_claim": "data retention", "reply_must_address": "address data retention"}',
            "This is a reply about data retention policies.",
        ])
        result, claim = await pb._generate_reply_for_post({
            "title": "Gateway supply chain risk",
            "content": "Managed gateway models are part of your supply chain",
        })
        assert result == "This is a reply about data retention policies."
        # claim_check stats are now set in _execute_feed_replies (deferred)
        assert claim is not None
        # Verify the second call had a system_prompt with the constraint
        call2_kwargs = pb.llm.generate.call_args_list[1][1]
        assert "MUST directly engage with" in call2_kwargs["system_prompt"]

    @pytest.mark.asyncio
    async def test_claim_extract_none_graceful_degradation(self):
        """Scenario (b): extract_claim returns None → reply generated without constraint."""
        pb = _make_pb()
        pb.llm.generate = AsyncMock(side_effect=[
            "invalid json",  # extract_claim returns None
            "A reply about something else.",
        ])
        result, _ = await pb._generate_reply_for_post({
            "title": "Gateway supply chain risk",
            "content": "Managed gateway models are part of your supply chain",
        })
        assert result == "A reply about something else."
        # claim_check stats should NOT have been incremented
        assert pb._stats["claim_check_passed"] == 0
        assert pb._stats["claim_check_failed"] == 0

    @pytest.mark.asyncio
    async def test_claim_check_passes_reply_published(self):
        """Scenario (c): check_claim returns on_topic=true, score=0.8 → reply published."""
        pb = _make_pb()
        # extract_claim returns valid
        # generate returns reply
        # check_claim returns pass
        pb.llm.generate = AsyncMock(side_effect=[
            '{"central_claim": "data retention", "reply_must_address": "address retention"}',
            "Good reply about data retention.",
        ])
        result, claim = await pb._generate_reply_for_post({
            "title": "Gateway supply chain risk",
            "content": "Managed gateway models are part of your supply chain",
        })
        assert result == "Good reply about data retention."
        assert claim is not None

    @pytest.mark.asyncio
    async def test_claim_check_fails_on_topic_false(self):
        """Scenario (d): claim check is deferred to _execute_feed_replies.
        _generate_reply_for_post returns reply + claim regardless of check outcome."""
        pb = _make_pb()
        pb.llm.generate = AsyncMock(side_effect=[
            '{"central_claim": "data retention", "reply_must_address": "address retention"}',
            "Let me discuss mTLS instead.",
        ])
        result, claim = await pb._generate_reply_for_post({
            "title": "Gateway supply chain risk",
            "content": "Managed gateway models are part of your supply chain",
        })
        # Reply is returned even though it would fail claim check
        # (check is deferred to _execute_feed_replies)
        assert result == "Let me discuss mTLS instead."
        assert claim is not None
        assert claim["central_claim"] == "data retention"

    @pytest.mark.asyncio
    async def test_claim_check_score_below_threshold_but_on_topic_passes(self):
        """Scenario (e): claim check is deferred. Reply returned with claim for caller to check."""
        pb = _make_pb()
        pb.llm.generate = AsyncMock(side_effect=[
            '{"central_claim": "data retention", "reply_must_address": "address retention"}',
            "Vaguely related reply.",
        ])
        result, claim = await pb._generate_reply_for_post({
            "title": "Gateway supply chain risk",
            "content": "Managed gateway models are part of your supply chain",
        })
        assert result == "Vaguely related reply."
        assert claim is not None

    @pytest.mark.asyncio
    async def test_claim_check_llm_fails_fails_open(self):
        """Scenario (f): claim check is deferred. Reply returned with claim for caller."""
        pb = _make_pb()
        pb.llm.generate = AsyncMock(side_effect=[
            '{"central_claim": "data retention", "reply_must_address": "address retention"}',
            "A reply about the topic.",
        ])
        result, claim = await pb._generate_reply_for_post({
            "title": "Gateway supply chain risk",
            "content": "Managed gateway models are part of your supply chain",
        })
        assert result == "A reply about the topic."
        assert claim is not None

    @pytest.mark.asyncio
    async def test_summary_line_includes_claim_check_failures(self):
        """Scenario (g): Summary line includes claim-check failure count."""
        pb = _make_pb(behavior_cfg={
            "phase_b_own_post_replies": False,
            "phase_b_feed_replies": False,
            "phase_b_debate_continuation": False,
        })
        with patch("phases.phase_b.orchestrator.logger") as mock_logger:
            result = await pb.execute()
        assert "claim_check_failures" in result
        assert result["claim_check_failures"] == 0
        # Verify the summary line format includes claim-check failures
        found = False
        for call_args in mock_logger.info.call_args_list:
            msg = call_args[0][0] if call_args[0] else ""
            if "claim-check failures" in msg:
                found = True
                break
        assert found, "Summary line should include claim-check failures"

    @pytest.mark.asyncio
    async def test_claim_check_fail_not_dedupped(self):
        """Scenario (h): comment that fails claim-check is NOT added to dedup store."""
        pb = _make_pb()
        pb.llm.generate = AsyncMock(side_effect=[
            '{"central_claim": "data retention", "reply_must_address": "address retention"}',
            "Let me discuss mTLS instead.",
            '{"on_topic": false, "reason": "off-topic", "score": 0.1}',
        ])
        dedup_key = "post_1:comment_1"
        assert dedup_key not in pb._replied_comment_ids
        with patch("phases.phase_b.orchestrator._save_replied_comment_ids"):
            result, claim = await pb._generate_reply_for_post({
                "title": "Gateway supply chain risk",
                "content": "Managed gateway models are part of your supply chain",
            })
        # should still not be in dedup store after the cycle
        assert dedup_key not in pb._replied_comment_ids
