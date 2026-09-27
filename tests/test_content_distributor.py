# -*- coding: utf-8 -*-
"""Tests para services.content_distributor (P-118).

Verifica que el throttle de 20h (_save_state) NO se activa cuando el pipeline
falla (errors != []) o cuando no se encolo nada (enqueued == 0). Cubre el bug
de P-118: antes _save_state se llamaba incondicionalmente al final de
run_distribution() y en la rama "no posts qualify".
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import services.content_distributor as cd


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    """Aisla STATE_FILE/PUBLISHED_POSTS_FILE y cwd a tmp_path."""
    monkeypatch.chdir(tmp_path)
    state = tmp_path / "data" / "content_distributor_state.json"
    posts = tmp_path / "data" / "published_posts.json"
    monkeypatch.setattr(cd, "STATE_FILE", state)
    monkeypatch.setattr(cd, "PUBLISHED_POSTS_FILE", posts)
    return state


def _fake_subprocess(returncode=0, stderr=""):
    def _run(*args, **kwargs):
        return SimpleNamespace(returncode=returncode, stderr=stderr, stdout="")
    return _run


def test_no_posts_does_not_save_state(isolated_state, monkeypatch):
    monkeypatch.setattr(cd, "select_best_posts", lambda top_n=3: [])
    result = cd.run_distribution()
    assert result == {"selected": 0, "enqueued": 0, "errors": []}
    assert not isolated_state.exists()


def test_repurposer_errors_does_not_save_state(isolated_state, monkeypatch):
    monkeypatch.setattr(cd, "select_best_posts", lambda top_n=3: [{"topic": "x"}])
    monkeypatch.setattr(
        cd, "subprocess",
        SimpleNamespace(run=_fake_subprocess(returncode=2, stderr="boom")),
    )
    result = cd.run_distribution()
    assert result["enqueued"] == 0
    assert result["errors"], "se esperaba error no vacio"
    assert not isolated_state.exists()


def test_enqueued_zero_does_not_save_state(isolated_state, monkeypatch):
    monkeypatch.setattr(cd, "select_best_posts", lambda top_n=3: [{"topic": "x"}])
    monkeypatch.setattr(
        cd, "subprocess",
        SimpleNamespace(run=_fake_subprocess(returncode=0, stderr="nothing")),
    )
    result = cd.run_distribution()
    assert result["enqueued"] == 0
    assert result["errors"] == []
    assert not isolated_state.exists()


def test_successful_enqueue_saves_state(isolated_state, monkeypatch):
    monkeypatch.setattr(cd, "select_best_posts", lambda top_n=3: [{"topic": "x"}])
    monkeypatch.setattr(
        cd, "subprocess",
        SimpleNamespace(run=_fake_subprocess(returncode=0, stderr="Enqueued 2 jobs\n")),
    )
    result = cd.run_distribution()
    assert result["enqueued"] == 2
    assert result["errors"] == []
    assert isolated_state.exists()
    data = json.loads(isolated_state.read_text(encoding="utf-8"))
    assert "last_run" in data
