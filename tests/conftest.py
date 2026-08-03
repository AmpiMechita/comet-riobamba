# -*- coding: utf-8 -*-
"""Centralised test isolation: redirects production data/traces paths to
throwaway temp directories so that no test can read-write the real
runtime state of the agent.

This fixture is autouse at function scope — every test in tests/ gets it
without any explicit request.  File-local fixtures (e.g. _iso_db in
test_phase_b_wiring) can still override individual paths when stricter
isolation is needed.

Notable uncovered paths (documented, not handled here):
  - dedup_store._JSON_NAMESPACES  (tuple list, immutable elements; the
    list IS mutable but the json migration only runs when the SQLite db
    is empty, and that db is already redirected by _iso_db / _redirect_paths)
  - core/agent.py instance attributes (state_file, health_file, diag_path)
    — the Agent class is not instantiated during unit tests
  - telegram_client.py hardcoded 'data/comet_state.db' string literals
    — same db as services.persistence.DB_PATH
  - dry-run flags (data/phase_a_dry_run.flag, data/phase_b_dry_run.flag)
    — gated by instance attrs in PhaseA/PhaseB; the fallback Path(...)
    call cannot be monkeypatched without replacing pathlib.Path globally
  - phase_a_content.py inline Path("data/topic_matrix_state.json")
    — local expression, not a module-level constant
"""

import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_runtime_state(tmp_path, monkeypatch):
    """Redirect high-risk module-level path constants to tmp_path."""

    # ── Traces (core/tracer.py) ──────────────────────────
    traces_dir = tmp_path / "traces"
    traces_dir.mkdir(exist_ok=True)
    monkeypatch.setattr("core.tracer.TRACES_DIR", traces_dir)

    # ── Self-eval metrics (services/self_eval.py) ────────
    monkeypatch.setattr(
        "services.self_eval.STATE_PATH",
        tmp_path / "self_eval_state.json",
    )

    # ── Value log (core/value_log.py) ────────────────────
    monkeypatch.setattr(
        "core.value_log.VALUE_LOG_PATH",
        tmp_path / "value_log.jsonl",
    )

    # ── Own-post store (services/own_post_store.py) ──────
    monkeypatch.setattr(
        "services.own_post_store.PUBLISHED_LOG_PATH",
        tmp_path / "published_posts.json",
    )
    monkeypatch.setattr(
        "services.own_post_store.OWN_POST_IDS_PATH",
        tmp_path / "own_post_ids.json",
    )

    # ── General persistence (services/persistence.py) ────
    monkeypatch.setattr(
        "services.persistence.DB_PATH",
        tmp_path / "comet_state.db",
    )

    # ── Generation attempts log (phases/phase_a_content.py) ──
    monkeypatch.setattr(
        "phases.phase_a_content._GENERATION_ATTEMPTS_LOG",
        tmp_path / "generation_attempts.jsonl",
    )

    # ── Rejected-posts log (phases/phase_a_content.py) ──
    # Sin esto, los tests que ejercitan execute() real de Fase A escriben en
    # el data/rejected_posts.jsonl REAL cuando un cuerpo generado cae en un gate.
    # Los tests que ya parchean este path (Fix 2) siguen ganando: su monkeypatch
    # se aplica despues de este fixture autouse y lo sobreescribe.
    monkeypatch.setattr(
        "phases.phase_a_content._REJECTED_POSTS_LOG",
        tmp_path / "rejected_posts.jsonl",
    )

    # ── Hero-post state (phases/phase_a_content.py) ──
    # Estado del enrutado hero/no-hero de Fase A (1 Opus/día). Sin esto los tests
    # que ejercitan execute() escribirían el data/hero_state.json REAL.
    monkeypatch.setattr(
        "phases.phase_a_content._HERO_STATE_FILE",
        tmp_path / "hero_state.json",
    )

    # ── Anthropic spend tracker (services/model_cascade.py) ──
    # Sin esto, los tests que ejercitan _call_anthropic leen el data/
    # anthropic_spend_tracker.json REAL y fallan cuando el gasto del dia cruza el
    # cap (spend guard). Cada test arranca con su propio tracker vacio en tmp.
    monkeypatch.setattr(
        "services.model_cascade._ANTHROPIC_SPEND_FILE",
        str(tmp_path / "anthropic_spend_tracker.json"),
    )

    # ── Roadmap published-log constant propia (services/roadmap.py) ──
    monkeypatch.setattr(
        "services.roadmap.PUBLISHED_LOG_PATH",
        tmp_path / "published_posts.json",
    )
