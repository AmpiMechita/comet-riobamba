from pathlib import Path

import pytest

from core.memory_store import MemoryStore


class TestMemoryStore:
    def test_update_inserts_new_record(self, tmp_path: Path) -> None:
        db = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=str(db))
        store.update_memory("user-1", "alice", "Alice likes technical discussions about AI safety.")
        mem = store.get_memory("user-1")
        assert mem is not None
        assert mem["user_id"] == "user-1"
        assert mem["username"] == "alice"
        assert mem["summary"] == "Alice likes technical discussions about AI safety."
        assert mem["last_interaction"] is not None

    def test_update_upserts_existing_record(self, tmp_path: Path) -> None:
        db = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=str(db))
        store.update_memory("user-1", "alice", "Original summary.")
        store.update_memory("user-1", "alice", "Updated summary with new information.")
        mem = store.get_memory("user-1")
        assert mem is not None
        assert mem["summary"] == "Updated summary with new information."
        assert mem["last_interaction"] is not None

    def test_get_memory_returns_correct_record(self, tmp_path: Path) -> None:
        db = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=str(db))
        store.update_memory("user-1", "alice", "Memory for alice.")
        store.update_memory("user-2", "bob", "Memory for bob.")
        mem1 = store.get_memory("user-1")
        mem2 = store.get_memory("user-2")
        assert mem1 is not None and mem1["username"] == "alice"
        assert mem2 is not None and mem2["username"] == "bob"

    def test_get_memory_returns_none_for_unknown_user(self, tmp_path: Path) -> None:
        db = tmp_path / "test_memory.db"
        store = MemoryStore(db_path=str(db))
        store.update_memory("user-1", "alice", "Some memory.")
        mem = store.get_memory("nonexistent")
        assert mem is None
