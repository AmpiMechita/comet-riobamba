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

    # ── Neutralise production env vars (leak from .env) ──────
    # Every test starts from the DEFAULT behaviour: no flash-only, no
    # best-of-N, default Anthropic spend limit (2.00). Tests that WANT
    # these vars (test_flash_only_guard, test_quality_bestof) set them
    # explicitly in their own scope AFTER this autouse fixture.
    monkeypatch.delenv("AGENT_FLASH_ONLY", raising=False)
    monkeypatch.delenv("AGENT_QUALITY_BESTOF", raising=False)
    monkeypatch.delenv("QUALITY_BESTOF_N", raising=False)
    monkeypatch.delenv("ANTHROPIC_SPEND_LIMIT_USD", raising=False)

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

    # ── Incident store (services/incident_store.py) ──
    # Sin esto, los tests que ejercitan execute() real de Fase A leerian/escribirian
    # el data/incidents.jsonl REAL (get_incident_by_id, mark_incident_used).
    monkeypatch.setattr(
        "services.incident_store.INCIDENTS_PATH",
        tmp_path / "incidents.jsonl",
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

    # ── Interlocutors ledger (services/interlocutors.py) ──
    monkeypatch.setattr(
        "services.interlocutors._INTERLOCUTORS_PATH",
        tmp_path / "interlocutors.json",
    )

    # ── Durable per-comment dedup (services/reply_cap.py) ──
    monkeypatch.setattr(
        "services.reply_cap._REPLIED_COMMENT_IDS_PATH",
        tmp_path / "replied_comment_ids_durable.json",
    )

    # ── Unrepliable namespace (services/reply_cap.py) ──
    # Comentarios con padre borrado (404). Sin redirect, los tests escriben en
    # el data/unrepliable_comment_ids.json REAL.
    monkeypatch.setattr(
        "services.reply_cap._UNREPLIABLE_IDS_PATH",
        tmp_path / "unrepliable_comment_ids.json",
    )

    # ── DedupStore SQLite (services/dedup_store.py) — GLOBAL isolation ──
    # Causa raíz de la contaminación del store real: cualquier test que
    # construyera PhaseB() (→ DedupStore()) sin un fixture puntual escribía en
    # el data/comet_dedup.db REAL, dejando claves de test (p1, new_post) que
    # rompen el matching de parent_id del seguimiento de hilos. Redirigimos el
    # path por defecto a tmp para TODOS los tests. Además vaciamos
    # _JSON_NAMESPACES para que la migración inicial no siembre los data/*.json
    # reales dentro del store de test (el db en tmp arranca vacío → count=0).
    # Los fixtures por-archivo que ya reasignan estos valores siguen ganando
    # (corren después de este autouse) y su restore no filtra.
    monkeypatch.setattr(
        "services.dedup_store.DedupStore._default_db_path",
        tmp_path / "comet_dedup.db",
    )
    monkeypatch.setattr("services.dedup_store._JSON_NAMESPACES", [])

    # ── Cross-cycle reply history (phases/phase_b/orchestrator.py) ──
    # Aísla data/reply_history.json por test: el path de feed-reply escribe
    # aquí al publicar, y sin redirect contamina el archivo real (haciendo
    # que el check anti-dupe cross-ciclo bloquee mocks en corridas siguientes).
    monkeypatch.setattr(
        "phases.phase_b.orchestrator._REPLY_HISTORY_PATH",
        tmp_path / "reply_history.json",
    )
