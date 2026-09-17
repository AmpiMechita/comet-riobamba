# -*- coding: utf-8 -*-
"""Tests del modulo de auditoria editorial propia (24/08/2026).

Helpers puros: sin IO ni red. El corpus sintetico replica los hallazgos
reales de la auditoria manual (coletilla 'a defensible starting point,
calibrate against your own baseline' repetida entre posts).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.editorial_self_audit import (
    _analyze_corpus,
    _analyze_votes,
)


def _post(body: str, hours_ago: float = 48) -> dict:
    from datetime import datetime, timedelta, timezone
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {"body": body, "published_at": ts}


CLEAN_POST = (
    "Rate limits are not reliability. A provider that answers in 200ms until "
    "19:00 and then 429s all night has a window, not an SLA.\n\nGate fallback "
    "at 3 failures per 10 minutes per provider and require a single success "
    "to close the circuit again.\n\nWhat does your cascade do when the free "
    "tier is the one throttling at 10000 neurons daily?"
)
FATIGUED_TAIL = (
    " Gate the rollout at 0.9 as a defensible starting point, calibrate "
    "against your own baseline."
)


class TestAnalyzeCorpus:

    def test_empty_corpus_safe(self):
        assert _analyze_corpus([]) == {"posts_analyzed": 0}

    def test_cta_rate_and_specificity(self):
        posts = [_post(CLEAN_POST), _post(CLEAN_POST.replace("Gate fallback", "Extra verified context. Gate fallback"))]
        r = _analyze_corpus(posts)
        # ambos cierran con pregunta que nombra numero/umbral
        assert r["cta_rate_pct"] == 100
        assert r["cta_specific_pct"] == 100

    def test_generic_question_not_specific(self):
        body = (
            "Something something agents and production deployments everywhere "
            "across the board with plenty of filler material to reach the "
            "minimum length requirement for publication on the network today."
            "\n\nWhat do you think?"
        )
        r = _analyze_corpus([_post(body)])
        assert r["cta_rate_pct"] == 100
        assert r["cta_specific_pct"] == 0

    def test_template_fatigue_detected(self):
        posts = [_post(("Mechanism %d. " % i) + CLEAN_POST + FATIGUED_TAIL) for i in range(6)]
        r = _analyze_corpus(posts, window=50)
        assert r["template_fatigue_pct"] >= 80, r
        assert r["top_tetragram"]["count"] >= 4

    def test_no_fatigue_in_diverse_corpus(self):
        closers = [
            "Which threshold would you gate at 3 failures?",
            "Where does your rollback line sit at 10% drift?",
            "How do you cap retries at 2 attempts without stalls?",
            "What budget do you assign per 1000 calls today?",
            "Which signal closes your circuit at 1 success?",
            "What ratio of verified effects do you require?",
            "How tight is your window for 5 minute detection?",
            "Where do you place the floor for 90% coverage?",
        ]
        openers = [
            "Retry storms punish queues hardest when idempotency keys rotate.",
            "Provenance ledgers beat audit trails because replays expose intent.",
            "Sandbox escapes begin where state assumptions meet untrusted input.",
            "Backpressure is a contract, not a queue depth alarm firing late.",
            "Shadow traffic reveals the degradation band uptime checks miss.",
            "Leases expire faster than consensus rounds under clock skew.",
            "Compaction loses obligation metadata before it loses facts.",
            "Fan-out amplifies silent failures across every retry boundary.",
        ]
        middles = [
            "Idempotency keys rotate per attempt so duplicates slip past dedup.",
            "Replay fidelity measures whether branches survive the span cut.",
            "Untrusted input crosses the boundary exactly where checks end.",
            "Queue depth alarms fire after the latency budget already broke.",
            "Each probe succeeds while the provider degrades under load.",
            "Clock skew turns lease renewal into a race between nodes.",
            "Obligation metadata dies first during aggressive compaction.",
            "Every retry multiplies the blast radius of one bad deploy.",
        ]
        bridges = [
            "Half-open probes need jitter before they earn trust back.",
            "Shadow traffic costs less than a rollback after midnight.",
            "Deterministic seeds make flaky suites honest witnesses.",
            "Backpressure belongs in the protocol, not the dashboard.",
            "Degradation bands hide between two green dashboards.",
            "Renewal races are lost in milliseconds nobody logs.",
            "Facts survive compression; promises rarely do.",
            "Blast radius grows quietly until the first page.",
        ]
        bodies = [
            "%s %s\n\n%s\n\n%s" % (openers[i], middles[i], bridges[i], closers[i])
            for i in range(8)
        ]
        r = _analyze_corpus([_post(b) for b in bodies])
        assert r["template_fatigue_pct"] <= 25, r

    def test_opener_diversity(self):
        posts = [_post(CLEAN_POST)] * 10  # misma apertura x10 -> diversidad minima
        r = _analyze_corpus(posts)
        assert r["opener_diversity_pct"] == round(100 / 10)

    def test_cadence_by_age(self):
        posts = [_post(CLEAN_POST, hours_ago=h) for h in (2, 10, 30, 72, 200)]
        r = _analyze_corpus(posts)
        assert r["posts_last_24h"] == 2
        assert r["posts_last_7d"] == 4


class TestAnalyzeVotes:

    def test_calibration_holds_when_higher_score_wins(self):
        votes = ([{"date": "2026-08-20", "value_score": 0.2, "upvotes": 0}] * 90
                 + [{"date": "2026-08-20", "value_score": 0.2, "upvotes": 1}] * 10
                 + [{"date": "2026-08-20", "value_score": 0.9, "upvotes": 1}] * 30
                 + [{"date": "2026-08-20", "value_score": 0.9, "upvotes": 0}] * 10)
        r = _analyze_votes(votes)
        assert r["<=0.3"]["upvote_rate_pct"] == 10
        assert r[">0.5"]["upvote_rate_pct"] == 75
        assert r["calibrated"] is True

    def test_uncalibrated_mirror_real_world(self):
        # Hallazgo real 24/08: score alto NO predice upvotes (3% < 5%).
        votes = ([{"date": "2026-08-20", "value_score": 0.2, "upvotes": 1}] * 5
                 + [{"date": "2026-08-20", "value_score": 0.2, "upvotes": 0}] * 95
                 + [{"date": "2026-08-20", "value_score": 0.9, "upvotes": 1}] * 3
                 + [{"date": "2026-08-20", "value_score": 0.9, "upvotes": 0}] * 97)
        r = _analyze_votes(votes)
        assert r["calibrated"] is False

    def test_old_records_ignored(self):
        votes = [{"date": "2026-01-01", "value_score": 0.9, "upvotes": 1}]
        r = _analyze_votes(votes, days=30)
        assert r.get(">0.5") is None
        assert r["overall_upvote_rate_pct"] is None
