import json
from pathlib import Path

import pytest

from core.strategy_state import StrategyState, get_default_state


class TestStrategyState:
    def test_load_returns_default_when_file_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "strategy_state.json"
        assert not path.exists()
        ss = StrategyState(path)
        state = ss.load()
        assert state == get_default_state()

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "strategy_state.json"
        ss = StrategyState(path)

        saved = {
            "top_topics": ["ai", "ml"],
            "avoid_topics": ["politics"],
            "best_tone": "technical",
            "last_updated": "2026-06-18T12:00:00",
        }
        ss.save(saved)
        assert path.exists()

        loaded = ss.load()
        assert loaded == saved

    def test_save_and_load_partial_update(self, tmp_path: Path) -> None:
        path = tmp_path / "strategy_state.json"
        ss = StrategyState(path)

        ss.save({"best_tone": "casual"})
        loaded = ss.load()
        assert loaded["best_tone"] == "casual"
        assert loaded["top_topics"] == []
        assert loaded["avoid_topics"] == []
        assert loaded["last_updated"] is None

    def test_save_uses_atomic_write(self, tmp_path: Path) -> None:
        path = tmp_path / "strategy_state.json"
        ss = StrategyState(path)
        ss.save(get_default_state())
        assert path.exists()
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_corrupted_file_returns_default(self, tmp_path: Path) -> None:
        path = tmp_path / "strategy_state.json"
        path.write_text("{invalid json", encoding="utf-8")

        ss = StrategyState(path)
        state = ss.load()
        assert state == get_default_state()

    def test_custom_path(self) -> None:
        ss = StrategyState(Path("custom", "path.json"))
        assert ss._path == Path("custom", "path.json")

    def test_default_path(self) -> None:
        ss = StrategyState()
        assert ss._path == Path("data", "strategy_state.json")
