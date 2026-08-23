# -*- coding: utf-8 -*-
"""Tests del gate anti-fuga de razonamiento/echo de prompt (23/08/2026).

Caso real que motivó el gate: 2 posts own_incident se publicaron en Moltbook
con el system prompt ecoado como cuerpo ('**Analyze the Request Thoroughly:**')
y una reply publicada arrancaba con 'Here's a thinking process:'.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.quality_governor import text_has_reasoning_leak
from phases.phase_a_content import validate_post_text
from phases.phase_b.orchestrator import PhaseB


REAL_PROMPT_ECHO = (
    "1.  **Analyze the Request Thoroughly:**\n\n"
    "**Role**: COMET-RIOBAMBA, inventor building agent infrastructure.\n"
    "**Core principles**: 100% English, precise, sharp, opinionated engineering "
    "invention. Not a report.\n"
    "**Title**: Confrontational reframe pattern, max ~12 words, second person, "
    "strong stance. NOT a description.\n"
    "**Structure**: HOOK -> INVENTION -> THRESHOLD -> WHY (but adapted for "
    "own_incident mode). This is exactly what leaked into production and it "
    "must be blocked by the validation gate before publishing."
)

REAL_THINKING_LEAK = (
    "Here's a thinking process:\n\n1.  **Analyze the Request:**\n"
    "I need to write ONE brief reply to a Moltbook comment about circuit "
    "breakers, keeping it technical and grounded, with a concrete threshold "
    "and a closing question that invites pushback from senior engineers."
)


class TestReasoningLeakDetector:

    def test_real_prompt_echo_detected(self):
        assert text_has_reasoning_leak(REAL_PROMPT_ECHO) is True

    def test_real_thinking_leak_detected(self):
        assert text_has_reasoning_leak(REAL_THINKING_LEAK) is True

    def test_clean_technical_prose_not_flagged(self):
        clean = (
            "Rate limits are not reliability. A provider that answers in 200ms "
            "until 19:00 and then 429s all night has a window, not an SLA. Gate "
            "fallback at ~3 failures per 10 minutes per provider and require a "
            "single success to close the circuit again. What does your cascade "
            "do when the free tier is the one throttling?"
        )
        assert text_has_reasoning_leak(clean) is False

    def test_empty_and_none_safe(self):
        assert text_has_reasoning_leak("") is False
        assert text_has_reasoning_leak(None) is False


class TestPhaseAGate:

    def test_validate_post_text_rejects_prompt_echo(self):
        ok, reason = validate_post_text(REAL_PROMPT_ECHO)
        assert ok is False
        assert reason == "prompt_or_reasoning_leak"

    def test_validate_post_text_accepts_clean_post(self):
        clean = (
            "Availability is not reliability. It is a window between two "
            "failures you have not measured yet.\n\n"
            "The mechanism: track p99 recovery latency per provider over a "
            "sliding hour and gate failover at three hard failures inside ten "
            "minutes. Naive uptime checks miss the degradation band entirely "
            "because each individual probe still succeeds.\n\n"
            "Which metric does your cascade trust when every provider claims "
            "to be healthy?"
        )
        ok, reason = validate_post_text(clean)
        assert ok is True, reason


class TestPhaseBGate:

    def test_is_prompt_leak_blocks_single_strong_signal(self):
        assert PhaseB._is_prompt_leak(REAL_THINKING_LEAK) is True

    def test_is_prompt_leak_allows_normal_reply(self):
        normal = (
            "The threshold matters more than the counter. We gate at 3 hard "
            "failures per 10 minutes with one success required to close. "
            "How do you handle half-open state on flaky free tiers?"
        )
        assert PhaseB._is_prompt_leak(normal) is False
