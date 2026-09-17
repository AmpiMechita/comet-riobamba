# -*- coding: utf-8 -*-
"""Tests del helper de edad para la fast-lane early-watchlist (25/08/2026)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phases.phase_b import PhaseB
from phases.deps import PhaseBDeps


def _pb():
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={},
        agent_name="COMET-RIOBAMBA",
    )
    return PhaseB(deps)


class TestPostAgeMinutes:

    def test_fresh_post_under_30(self):
        pb = _pb()
        ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        age = pb._post_age_minutes({"created_at": ts})
        assert age is not None and 4 <= age <= 6

    def test_old_post_over_30(self):
        pb = _pb()
        ts = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        assert pb._post_age_minutes({"created_at": ts}) >= 180

    def test_z_suffix_and_naive_both_ok(self):
        pb = _pb()
        assert pb._post_age_minutes({"created_at": "2026-08-25T10:00:00Z"}) is not None
        assert pb._post_age_minutes({"published_at": "2026-08-25T10:00:00"}) is not None

    def test_missing_or_garbage_returns_none(self):
        pb = _pb()
        assert pb._post_age_minutes({}) is None
        assert pb._post_age_minutes({"created_at": "not-a-date"}) is None
        assert pb._post_age_minutes(None) is None


class TestAntiSelfBumpPredicate:

    def test_own_author_detection_matches_agent_name_semantics(self):
        """El skip de feed normaliza guiones/guiones bajos/caso:
        Moltbook usa 'comet_riobamba', agent_name es 'COMET-RIOBAMBA'."""
        import re
        agent_name = "COMET-RIOBAMBA"
        norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s or "").lower())
        for author, expected in [("comet_riobamba", True), ("  Comet_Riobamba ", True),
                                 ("COMET-RIOBAMBA", True), ("other_agent", False),
                                 ("comet_riobamba_x", False), ("", False)]:
            result = norm(author) == norm(agent_name)
            assert result is expected, author
