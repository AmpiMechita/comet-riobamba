import json
from datetime import datetime, timedelta

import pytest
import services.post_history_guard as phg


@pytest.fixture(autouse=True)
def _isolate_history(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.post_history_guard.HISTORY_PATH",
        tmp_path / "post_history_guard.json",
    )


def _path():
    return phg.HISTORY_PATH


def _read():
    p = _path()
    if not p.exists():
        return {"posts": []}
    return json.loads(p.read_text(encoding="utf-8-sig"))


# ── Caso A: post permitido ─────────────────────────────────

class TestAllowPost:

    def test_empty_history_allows_post(self):
        assert phg.can_post_in_submolt("m/agents", 3, 24) is True

    def test_under_limit_allows_post(self):
        phg.register_post("P1", "m/test")
        phg.register_post("P2", "m/test")
        assert phg.can_post_in_submolt("m/test", 3, 24) is True

    def test_new_title_not_duplicate(self):
        phg.register_post("Primer Post", "m/agents")
        assert phg.is_title_duplicate("Algo Diferente") is False


# ── Caso B: post bloqueado por repetición ──────────────────

class TestBlockDuplicate:

    def test_exact_title_blocks(self):
        phg.register_post("Hello World", "m/agents")
        assert phg.is_title_duplicate("Hello World") is True

    def test_case_insensitive_match(self):
        phg.register_post("Único Título", "m/agents")
        assert phg.is_title_duplicate("único título") is True

    def test_high_similarity_blocks(self):
        phg.register_post("Células solares de perovskita", "m/agents")
        assert phg.is_title_duplicate(
            "células solares de perovskita"
        ) is True

    def test_empty_title_not_blocked(self):
        phg.register_post("Something", "m/agents")
        assert phg.is_title_duplicate("") is False


# ── Caso C: límite de ventana temporal ────────────────────

class TestWindowLimit:

    def test_exact_limit_reached(self):
        phg.register_post("A", "m/limit")
        phg.register_post("B", "m/limit")
        phg.register_post("C", "m/limit")
        assert phg.can_post_in_submolt("m/limit", 3, 24) is False

    def test_below_limit_after_one_slot_frees(self):
        phg.register_post("A", "m/limit")
        phg.register_post("B", "m/limit")
        phg.register_post("C", "m/limit")
        assert phg.can_post_in_submolt("m/limit", 4, 24) is True

    def test_different_submolt_unaffected(self):
        phg.register_post("A", "m/a")
        phg.register_post("B", "m/a")
        phg.register_post("C", "m/a")
        assert phg.can_post_in_submolt("m/b", 3, 24) is True

    def test_old_posts_outside_window_ignored(self):
        now = datetime.utcnow()
        old = (now - timedelta(hours=25)).isoformat()
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({
                "posts": [
                    {"title": "Old", "submolt": "m/test",
                     "created_at": old},
                ]
            }),
            encoding="utf-8-sig",
        )
        assert phg.can_post_in_submolt("m/test", 1, 24) is True


# ── register_post — integridad del historial ──────────────

class TestRegisterPost:

    def test_appends_and_persists(self):
        phg.register_post("New Post", "m/test")
        state = _read()
        assert len(state["posts"]) == 1
        assert state["posts"][0]["title"] == "New Post"
        assert state["posts"][0]["submolt"] == "m/test"

    def test_none_submolt_defaults_to_m_agents(self):
        phg.register_post("Test", None)
        state = _read()
        assert state["posts"][0]["submolt"] == "m/agents"

    def test_prunes_entries_older_than_14_days(self):
        old = (datetime.utcnow() - timedelta(days=15)).isoformat()
        recent = datetime.utcnow().isoformat()
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({
                "posts": [
                    {"title": "Expired", "submolt": "m/agents",
                     "created_at": old},
                    {"title": "Keep", "submolt": "m/agents",
                     "created_at": recent},
                ]
            }),
            encoding="utf-8-sig",
        )
        phg.register_post("Fresh", "m/agents")
        state = _read()
        titles = [e["title"] for e in state["posts"]]
        assert "Expired" not in titles
        assert "Keep" in titles
        assert "Fresh" in titles
