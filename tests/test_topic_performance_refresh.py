# -*- coding: utf-8 -*-
"""Tests de services/topic_performance_refresh.py — ventana, backup y guard
de frecuencia (guard calcado de tests/test_arxiv_topic_source.py)."""

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from services.topic_performance_refresh import (
    refresh_topic_performance,
    refresh_topic_performance_guarded,
)

UUID_RECENT = "42958c4c-7c0d-45f2-9c3b-7f229036bb6a"
UUID_OLD = "78bc54ad-59c2-4d2d-be5c-d3f4d3811854"


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _write_jsonl(path, records):
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8",
    )


def _make_client(score=5, comment_count=2):
    client = MagicMock()
    client.get_post.return_value = {"score": score, "comment_count": comment_count}
    return client


@pytest.fixture
def data_path(monkeypatch, tmp_path):
    path = tmp_path / "topic_performance.jsonl"
    monkeypatch.setattr("services.topic_performance_refresh.DATA_PATH", path)
    return path


# ── Ventana de refresh ────────────────────────────────────────────


def test_window_refreshes_recent_and_skips_old(data_path):
    """Post de 2 dias se refresca; post de 20 dias no y NO llama a get_post."""
    _write_jsonl(data_path, [
        {"post_id": UUID_RECENT, "topic": "reciente", "published_at": _iso_days_ago(2)},
        {"post_id": UUID_OLD, "topic": "viejo", "published_at": _iso_days_ago(20)},
    ])
    client = _make_client(score=7, comment_count=3)

    result = refresh_topic_performance(window_days=14, client=client, sleep_seconds=0)

    assert result["checked"] == 1
    assert result["skipped_window"] == 1
    client.get_post.assert_called_once_with(UUID_RECENT)

    records = [json.loads(l) for l in data_path.read_text(encoding="utf-8").splitlines()]
    recent = next(r for r in records if r["post_id"] == UUID_RECENT)
    old = next(r for r in records if r["post_id"] == UUID_OLD)
    assert recent["score"] == 7
    assert recent["comment_count"] == 3
    assert recent["score_checked"] is True
    assert "score_checked" not in old  # fuera de ventana: registro intacto


def test_window_none_refreshes_everything(data_path):
    """window_days=None (uso manual del script) refresca todos los registros."""
    _write_jsonl(data_path, [
        {"post_id": UUID_RECENT, "topic": "reciente", "published_at": _iso_days_ago(2)},
        {"post_id": UUID_OLD, "topic": "viejo", "published_at": _iso_days_ago(20)},
    ])
    client = _make_client()

    result = refresh_topic_performance(window_days=None, client=client, sleep_seconds=0)

    assert result["checked"] == 2
    assert result["skipped_window"] == 0
    assert client.get_post.call_count == 2


def test_invalid_and_dry_run_ids_are_skipped(data_path):
    """post_id invalido o dry-run no llama a la API (mismo filtro del script)."""
    _write_jsonl(data_path, [
        {"post_id": "dry-run-post-simulated", "topic": "simulado", "published_at": _iso_days_ago(1)},
        {"post_id": "post-0", "topic": "invalido", "published_at": _iso_days_ago(1)},
        {"post_id": UUID_RECENT, "topic": "real", "published_at": _iso_days_ago(1)},
    ])
    client = _make_client()

    result = refresh_topic_performance(window_days=14, client=client, sleep_seconds=0)

    assert result["checked"] == 1
    client.get_post.assert_called_once_with(UUID_RECENT)


def test_missing_file_is_noop(data_path):
    """Sin topic_performance.jsonl no rompe ni crea backup."""
    client = _make_client()
    result = refresh_topic_performance(window_days=14, client=client, sleep_seconds=0)
    assert result == {"records": 0, "checked": 0, "failed": 0, "skipped_window": 0, "backup": None}
    client.get_post.assert_not_called()


# ── Backup ────────────────────────────────────────────────────────


def test_backup_created_before_write(data_path):
    """Se crea un backup con timestamp con el contenido ORIGINAL antes de escribir."""
    _write_jsonl(data_path, [
        {"post_id": UUID_RECENT, "topic": "t", "published_at": _iso_days_ago(1)},
    ])
    original_content = data_path.read_text(encoding="utf-8")

    result = refresh_topic_performance(window_days=14, client=_make_client(), sleep_seconds=0)

    backup = result["backup"]
    assert backup is not None
    backup_path = Path(backup)
    assert backup_path.exists()
    assert ".jsonl.bak." in backup_path.name
    assert backup_path.read_text(encoding="utf-8") == original_content
    # y el archivo principal si cambio (score refrescado)
    assert data_path.read_text(encoding="utf-8") != original_content


# ── Guard de frecuencia (calcado de test_arxiv_topic_source.py) ────


def test_guarded_refresh_skips_within_interval(monkeypatch, tmp_path):
    state_path = tmp_path / "topic_performance_refresh_last_run.json"
    state_path.write_text(json.dumps({"last_refreshed_at": time.time()}), encoding="utf-8")
    monkeypatch.setattr("services.topic_performance_refresh.REFRESH_STATE_PATH", state_path)

    called = []
    monkeypatch.setattr(
        "services.topic_performance_refresh.refresh_topic_performance",
        lambda **kw: called.append(1) or {"checked": 5},
    )

    result = refresh_topic_performance_guarded(interval_hours=24)

    assert result == {"skipped": True, "checked": 0}
    assert called == []  # no debe llamar a la API si esta dentro del intervalo


def test_guarded_refresh_runs_when_no_prior_state(monkeypatch, tmp_path):
    state_path = tmp_path / "topic_performance_refresh_last_run.json"  # no existe
    monkeypatch.setattr("services.topic_performance_refresh.REFRESH_STATE_PATH", state_path)
    monkeypatch.setattr(
        "services.topic_performance_refresh.refresh_topic_performance",
        lambda **kw: {"records": 3, "checked": 3, "failed": 0, "skipped_window": 0, "backup": "x"},
    )

    result = refresh_topic_performance_guarded(interval_hours=24)

    assert result["skipped"] is False
    assert result["checked"] == 3
    assert json.loads(state_path.read_text())["last_refreshed_at"] > 0


def test_guarded_refresh_force_ignores_interval(monkeypatch, tmp_path):
    state_path = tmp_path / "topic_performance_refresh_last_run.json"
    state_path.write_text(json.dumps({"last_refreshed_at": time.time()}), encoding="utf-8")
    monkeypatch.setattr("services.topic_performance_refresh.REFRESH_STATE_PATH", state_path)
    monkeypatch.setattr(
        "services.topic_performance_refresh.refresh_topic_performance",
        lambda **kw: {"records": 2, "checked": 2, "failed": 0, "skipped_window": 0, "backup": "x"},
    )

    result = refresh_topic_performance_guarded(respect_interval=False)

    assert result["skipped"] is False
    assert result["checked"] == 2
