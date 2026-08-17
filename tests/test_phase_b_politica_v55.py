"""Tests de la politica vigente de respuestas (v5.5):
- Solo comentarios con referencia al tema del post se atienden (off-topic skip).
- Comentarios con cifras activan block_ungrounded (respuesta 100% verificable).
- Limite FIJO de 4 interacciones por conversacion (sin extension a 8).
"""
import pytest
from phases.phase_b import PhaseB
from phases.deps import PhaseBDeps
from unittest.mock import MagicMock
from phases.phase_b.scoring import comment_off_topic, text_exposes_figures


def _pb():
    deps = PhaseBDeps(
        model_cascade=MagicMock(),
        moltbook_client=MagicMock(),
        behavior_cfg={
            "max_comments_per_post": 10,
            "max_comments_per_day": 10,
            "max_comment_replies_per_cycle": 5,
            "max_feed_replies_per_day": 3,
            "delay_between_comments": 0,
        },
        agent_name="COMET-RIOBAMBA",
        get_comments_today=lambda: 0,
        increment_comments_today=lambda: 0,
    )
    pb = PhaseB(deps)
    pb.api = MagicMock()
    return pb


class TestTopicGate:
    def test_on_topic_comment_passes(self):
        pb = _pb()
        decision = pb._decide_reply(
            {"id": "x", "content": "How do capacity planning agents handle scale?"},
            is_own_post_reply=True,
            post_text="Capacity planning agents and scale design",
        )
        assert decision.should_reply

    def test_off_topic_comment_skipped_even_on_own_post(self):
        pb = _pb()
        decision = pb._decide_reply(
            {"id": "x", "content": "Nice weather today, how is the garden?"},
            is_own_post_reply=True,
            post_text="Capacity planning agents and scale design",
        )
        assert not decision.should_reply
        assert decision.reason == "reply_skipped_off_topic"

    def test_public_politica_no_divulgacion_se_mantiene(self):
        pb = _pb()
        decision = pb._decide_reply(
            {"id": "x", "content": "Join my project and win prizes!"},
            is_own_post_reply=True,
            post_text="Capacity planning agents and scale design",
        )
        assert not decision.should_reply


class TestFiguresGuard:
    def test_text_exposes_figures_detects_units(self):
        assert text_exposes_figures("we saw 30% improvement")
        assert text_exposes_figures("latency is 250 ms")
        assert not text_exposes_figures("can you explain the design?")


class TestFixedFourTurns:
    def _comments(self, chain):
        return [{"id": cid, "parent_id": pid, "content": t}
                for cid, pid, t in chain]

    def test_watchlist_capped_at_four(self):
        pb = PhaseB(MagicMock())
        comments = self._comments([
            ("c1", None, "About retries"),
            ("c2", "c1", "Question about scaling?"),
            ("c3", "c2", "Answers with new claim"),
        ])
        limit, reason = pb._thread_depth_limit(comments[2], comments, "wl", True)
        assert limit == 4
        assert reason is None

    def test_plain_author_capped_at_four(self):
        pb = PhaseB(MagicMock())
        comments = self._comments([
            ("c1", None, "About retries"),
            ("c2", "c1", "Question?"),
        ])
        limit, _ = pb._thread_depth_limit(comments[1], comments, "user", False)
        assert limit == 4
