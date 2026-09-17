# -*- coding: utf-8 -*-
"""Tests del gate de TITULOS con scaffold interno (24/08/2026).

Casos reales publicados en Moltbook que motivan el gate:
  - 'Here's a thinking process:' (x2, 23/08)
  - 'We need to critique the draft and then return an improved rewrite' (23/08)
  - 'Critique:** The invention is strong — decision spans plus replay
    fidelity as a health metric is a...' (24/08, DESPUES del gate original:
    el titulo nunca pasaba por text_has_reasoning_leak).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.quality_governor import title_has_scaffold, text_has_reasoning_leak


# ── Titulos reales filtrados: DEBEN bloquearse ────────────────────


class TestRealLeakedTitles:

    def test_thinking_process_title(self):
        assert title_has_scaffold("Here's a thinking process:") is True

    def test_critique_bold_residue(self):
        assert title_has_scaffold(
            "Critique:** The invention is strong — decision spans plus replay "
            "fidelity as a health metric is a"
        ) is True

    def test_critique_the_draft_instruction(self):
        assert title_has_scaffold(
            "We need to critique the draft and then return an improved rewrite"
        ) is True

    def test_numbered_list_item_as_title(self):
        assert title_has_scaffold("1. **Analyze the Request Thoroughly:**") is True

    def test_role_label_line(self):
        assert title_has_scaffold("Role: COMET-RIOBAMBA, inventor building agent infrastructure") is True

    def test_empty_and_none_safe(self):
        assert title_has_scaffold("") is False
        assert title_has_scaffold(None) is False


# ── Titulos legitimos reales: NO deben bloquearse ─────────────────


class TestLegitTitlesPass:

    @pytest.mark.parametrize("title", [
        "Circuit Breakers Should Ignore Benign 404s",
        "Your circuit breaker is just a threshold. It is not a policy.",
        "Exit code zero means success — except under PowerShell",
        "Sandbox designs often boil down to 'strong state checks'",
        "Technical debt in automation pipelines doesn't announce itself",
        "Agents that keep every observation in a single store decay fast?",
        "What does your cascade do when the free tier throttles?",
    ])
    def test_real_publishable_titles(self, title):
        assert title_has_scaffold(title) is False, title


# ── Body: variantes ampliadas del detector compartido ─────────────


class TestExpandedBodyPatterns:

    def test_hr_separator_detected(self):
        body = "---\n\nTITLE: Your trace is not a record.\n\nEvery tracing standard inherits."
        assert text_has_reasoning_leak(body) is True

    def test_meta_role_label_detected(self):
        body = "**Role**: COMET-RIOBAMBA, inventor building agent infrastructure."
        assert text_has_reasoning_leak(body) is True

    def test_paragraph_reference_detected(self):
        body = ("Paragraph 1 (INCIDENT): must include at least 2 of the verified "
                "figures verbatim: '1,035', '0'.")
        assert text_has_reasoning_leak(body) is True

    def test_hook_arrow_scaffold_detected(self):
        body = "**Structure**: HOOK -> INVENTION -> THRESHOLD -> WHY"
        assert text_has_reasoning_leak(body) is True

    def test_clean_prose_with_numbers_not_flagged(self):
        clean = (
            "Gate every agent-invoked shell behind a fixed prelude and score "
            "verified-effect rate, not commands run: the share of calls whose "
            "post-state assertion confirms the intended change. Gate dry runs "
            "at 98% verified effects before any mutation. Which side of the "
            "wrapper would you enforce it on?"
        )
        assert text_has_reasoning_leak(clean) is False

    def test_em_dash_prose_not_flagged(self):
        clean = (
            "Availability is not reliability — it is a window between two "
            "failures you have not measured yet.\n\nTrack p99 recovery latency "
            "per provider and gate failover at three hard failures inside ten "
            "minutes. What does your cascade trust?"
        )
        assert text_has_reasoning_leak(clean) is False
