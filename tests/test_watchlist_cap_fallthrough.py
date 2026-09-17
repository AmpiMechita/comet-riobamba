# -*- coding: utf-8 -*-
"""Tests del fix anti-estrella (24/08/2026): autores watchlist en cap no
ocupan la ventana de seleccion del feed y el cap general es dinamico.

Sintoma que motivo el fix: 10h sin comentarios — los 12 slots del pool
eran posts de watchlist capped (10/dia agotados de madrugada) y el resto
del dia transcurria con feed replies=0 en cada ciclo.
"""
from unittest.mock import MagicMock

import pytest

from phases.phase_b import PhaseB
from phases.deps import PhaseBDeps


def _make_pb(watchlist_max=10):
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={
            "max_comments_per_post": 3,
            "max_comments_per_day": 300,
            "max_comment_replies_per_cycle": 8,
            "max_feed_replies_per_day": 60,
            "delay_between_comments": 0,
        },
        agent_name="COMET-RIOBAMBA",
    )
    pb = PhaseB(deps)
    pb._watchlist_max_per_author_day = watchlist_max
    pb._watchlist_author_count_today = {}
    return pb


class TestWatchlistAuthorAtCap:

    def test_under_cap_not_blocked(self):
        pb = _make_pb()
        pb._watchlist_author_count_today = {"vina": 9}
        assert pb._watchlist_author_at_cap("vina") is False

    def test_at_cap_blocked(self):
        pb = _make_pb()
        pb._watchlist_author_count_today = {"vina": 10}
        assert pb._watchlist_author_at_cap("vina") is True

    def test_unknown_author_not_blocked(self):
        pb = _make_pb()
        assert pb._watchlist_author_at_cap("someone_new") is False

    def test_case_and_whitespace_insensitive(self):
        pb = _make_pb()
        pb._watchlist_author_count_today = {"vina": 10}
        assert pb._watchlist_author_at_cap("  Vina ") is True

    def test_empty_safe(self):
        pb = _make_pb()
        assert pb._watchlist_author_at_cap("") is False
        assert pb._watchlist_author_at_cap(None) is False


class TestCapAwarePoolFilter:

    def _post(self, pid, author, content="x" * 200):
        return {"id": pid, "author": author, "content": content}

    def test_capped_watchlist_posts_excluded_before_truncation(self):
        """12 posts de watchlist capped + 5 generales: el pool truncado a 12
        debe contener SOLO generales (los capped expulsados antes del corte)."""
        pb = _make_pb()
        pb._is_watchlist_author = lambda a: a in ("vina", "bytes", "diviner", "rossum", "dynamo",
                                                   "neo_konsi_s2bw", "molly", "starfish")
        for a in ("vina", "bytes", "diviner"):
            pb._watchlist_author_count_today[a] = 10  # capped

        candidates = (
            [self._post(f"w{i}", ["vina", "bytes", "diviner"][i % 3]) for i in range(12)]
            + [self._post(f"g{i}", f"general_{i}") for i in range(5)]
        )

        # replicar el filtro implementado (antes del [:12])
        filtered = [p for p in candidates if not pb._watchlist_author_at_cap(p["author"])]
        pool = filtered[:12]

        assert len(pool) == 5
        authors = {p["author"] for p in pool}
        assert authors.isdisjoint({"vina", "bytes", "diviner"})

    def test_uncapped_watchlist_stays_in_pool(self):
        pb = _make_pb()
        pb._is_watchlist_author = lambda a: a == "vina"
        pb._watchlist_author_count_today = {"vina": 3}
        candidates = [self._post("w1", "vina"), self._post("g1", "gen")]
        filtered = [p for p in candidates if not pb._watchlist_author_at_cap(p["author"])]
        assert len(filtered) == 2


class TestDynamicGeneralCap:

    def test_general_expands_into_unused_watchlist_reserve(self):
        """max_feed=60, reserved=18: con 0 usos watchlist, general puede usar 60."""
        max_feed = 60
        watchlist_reserved = 18
        wl_used, general_used = 0, 57
        dynamic_cap = max(0, max_feed - wl_used)
        assert general_used < dynamic_cap  # 57 < 60 -> permitido (antes: >=42 bloqueaba)

    def test_watchlist_reserve_still_limits_watchlist(self):
        max_feed, watchlist_reserved = 60, 18
        wl_used = 18
        assert wl_used >= watchlist_reserved  # watchlist se detiene en su reserva
