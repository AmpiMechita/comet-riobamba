# -*- coding: utf-8 -*-
"""Tests: eco de instrucciones de debate (leak real 25/08/2026).

El modelo papagayeó DEBATE_CONTINUATION_TEMPLATE como si fuera la reply:
'We need to respond to infoscout's latest message. He gave observed kill
rates... We need to acknowledge specific points and not repeat previous
arguments.' Publicado en Moltbook (comment ac96a9e9).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.quality_governor import text_has_reasoning_leak


REAL_LEAK = (
    "We need to respond to infoscout's latest message. He gave observed kill "
    "rates: 40-60% PIT kill rate at >80% line coverage; branch-targeted "
    "mutation lifts 10-20 points. We need to acknowledge specific points and "
    "not repeat previous arguments."
)


class TestInstructionEchoLeak:

    def test_real_leak_detected(self):
        assert text_has_reasoning_leak(REAL_LEAK) is True

    def test_spanish_planning_variant_detected(self):
        es = ("Necesitamos responder al último mensaje de infoscout. Dio tasas "
              "de eliminación observadas y debemos reconocer puntos específicos.")
        assert text_has_reasoning_leak(es) is True

    @pytest.mark.parametrize("clean", [
        "Gate merges at zero observed conflicts over a rolling window of 500 calls.",
        "We need to answer the deeper question: what does the read-set gap imply for retries?",
        "Kill rates of 40-60% at that coverage level match what PIT reports on Java services.",
    ])
    def test_legit_technical_prose_not_flagged(self, clean):
        assert text_has_reasoning_leak(clean) is False

class TestFeedEchoLeak:

    def test_real_feed_echo_detected(self):
        echo = ("We need to produce a reply 80-400 chars, as an engineer, "
                "addressing the specific claim in the post.")
        assert text_has_reasoning_leak(echo) is True

    def test_persona_directive_leak_detected(self):
        assert text_has_reasoning_leak(
            "Must be in historian mode: open by naming a specific past system.") is True

    def test_clean_technical_reply_passes(self):
        clean = ("Shadow buffers turn write-write races into detectable merges. "
                 "What breaks when two buffers commit the same key in one window?")
        assert text_has_reasoning_leak(clean) is False
