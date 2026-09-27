import sqlite3
from pathlib import Path

import pytest

from services.energy_knowledge_base import EnergyKnowledgeBase

SAMPLE_ROWS = [
    {
        "id": "claim_001",
        "technology": "perovskite-solar",
        "claim_text": "Perovskite cells reached 26% efficiency in lab.",
        "metric_value": 26.0,
        "metric_unit": "percent",
        "status": "claimed",
        "date_pub": "2026-06-01",
        "source_type": "paper",
    },
    {
        "id": "claim_002",
        "technology": "solid-state-battery",
        "claim_text": "Solid-state battery achieved 500 Wh/kg.",
        "metric_value": 500.0,
        "metric_unit": "Wh/kg",
        "status": "disputed",
        "date_pub": "2026-05-15",
        "source_type": "press_release",
    },
]


def _create_test_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE claims (
            id TEXT PRIMARY KEY,
            technology TEXT,
            claim_text TEXT,
            metric_value REAL,
            metric_unit TEXT,
            status TEXT,
            date_pub TEXT,
            source_type TEXT
        )
        """
    )
    for row in SAMPLE_ROWS:
        conn.execute(
            "INSERT INTO claims (id, technology, claim_text, metric_value, metric_unit, status, date_pub, source_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (row["id"], row["technology"], row["claim_text"],
             row["metric_value"], row["metric_unit"],
             row["status"], row["date_pub"], row["source_type"]),
        )
    conn.execute("PRAGMA user_version=1")
    conn.commit()
    conn.close()


def test_db_not_found():
    kb = EnergyKnowledgeBase(Path("C:/nonexistent/path/db.sqlite"))
    assert kb.available is False
    assert kb.get_recent_claims() == []
    assert kb.get_claims_by_technology("perovskite-solar") == []
    assert kb.update_claim_status("claim_001", "disputed") is False


def test_read_and_update(tmp_path: Path):
    db_path = tmp_path / "test_energy.db"
    _create_test_db(db_path)

    kb = EnergyKnowledgeBase(db_path)
    assert kb.available is True

    recent = kb.get_recent_claims(limit=5)
    assert len(recent) == 2
    assert recent[0]["id"] == "claim_001"
    assert recent[0]["technology"] == "perovskite-solar"
    assert recent[1]["id"] == "claim_002"

    by_tech = kb.get_claims_by_technology("solid-state-battery")
    assert len(by_tech) == 1
    assert by_tech[0]["claim_text"] == SAMPLE_ROWS[1]["claim_text"]

    updated = kb.update_claim_status("claim_002", "debunked")
    assert updated is True

    by_tech_after = kb.get_claims_by_technology("solid-state-battery")
    assert by_tech_after[0]["status"] == "debunked"

    not_found = kb.update_claim_status("does_not_exist", "claimed")
    assert not_found is False


def test_unavailable_when_schema_version_too_low(tmp_path: Path):
    db_path = tmp_path / "test_energy_uv0.db"
    _create_test_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA user_version=0")
    conn.commit()
    conn.close()

    kb = EnergyKnowledgeBase(db_path)
    assert kb.available is False
    assert kb.get_recent_claims() == []
    assert kb.update_claim_status("claim_001", "disputed") is False
