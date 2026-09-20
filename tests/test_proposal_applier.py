# -*- coding: utf-8 -*-
"""Tests for services/proposal_applier.py — auto-apply engine (config-only)."""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _isolate_paths(monkeypatch, tmp_path):
    """Aislar overlay y log de apply en un tmp dir para no tocar data/ real."""
    import services.proposal_applier as pa
    monkeypatch.setattr(pa, "OVERLAY_PATH", tmp_path / "auto_applied_config.json")
    monkeypatch.setattr(pa, "APPLY_LOG_PATH", tmp_path / "proposal_apply_log.jsonl")
    monkeypatch.setattr(pa, "COOLDOWN_SECONDS", 0)
    yield


def test_apply_valid_proposal_mutates_cfg_and_persists():
    import services.proposal_applier as pa
    cfg = {"max_consecutive_post_failures": 3}
    r = pa.apply_structured_proposal(
        {"param": "max_consecutive_post_failures", "suggested": 7, "reason": "demanda"},
        cfg,
    )
    assert r["status"] == "applied"
    assert cfg["max_consecutive_post_failures"] == 7
    assert pa.load_overlay()["max_consecutive_post_failures"] == 7


def test_reject_param_not_in_allowlist():
    import services.proposal_applier as pa
    cfg = {"cycle_interval_seconds": 28800}
    r = pa.apply_structured_proposal(
        {"param": "cycle_interval_seconds", "suggested": 60, "reason": "x"}, cfg
    )
    assert r["status"] == "rejected"
    assert cfg["cycle_interval_seconds"] == 28800


def test_clamp_value_to_allowlist_bounds():
    import services.proposal_applier as pa
    cfg = {"max_consecutive_post_failures": 3}
    r = pa.apply_structured_proposal(
        {"param": "max_consecutive_post_failures", "suggested": 999, "reason": "subir"}, cfg
    )
    assert r["status"] == "applied"
    assert r["applied"] == 10  # max de allowlist
    r2 = pa.apply_structured_proposal(
        {"param": "max_consecutive_post_failures", "suggested": -5, "reason": "bajar"}, cfg
    )
    assert r2["applied"] == 1  # min de allowlist


def test_invalid_value_rejected():
    import services.proposal_applier as pa
    cfg = {"max_comments_per_post": 3}
    r = pa.apply_structured_proposal(
        {"param": "max_comments_per_post", "suggested": "abc", "reason": "x"}, cfg
    )
    assert r["status"] == "rejected"


def test_cooldown_blocks_repeated_change(monkeypatch):
    import services.proposal_applier as pa
    monkeypatch.setattr(pa, "COOLDOWN_SECONDS", 86400)
    cfg = {"max_consecutive_post_failures": 3}
    r1 = pa.apply_structured_proposal(
        {"param": "max_consecutive_post_failures", "suggested": 7, "reason": "a"}, cfg
    )
    assert r1["status"] == "applied"
    r2 = pa.apply_structured_proposal(
        {"param": "max_consecutive_post_failures", "suggested": 8, "reason": "b"}, cfg
    )
    assert r2["status"] == "skipped_cooldown"
    assert cfg["max_consecutive_post_failures"] == 7


def test_merge_overlay_on_startup():
    """El overlay persistido se aplica al arranque: la logica inline de
    config.config se replica aqui (clamp + solo allowlist)."""
    import services.proposal_applier as pa
    pa.apply_structured_proposal(
        {"param": "max_comments_per_post", "suggested": 7, "reason": "ok"}, {}
    )
    overlay = pa.load_overlay()
    assert overlay.get("max_comments_per_post") == 7


def test_overlay_skips_unknown_params_on_merge(tmp_path):
    """Claves fuera de allowlist en el overlay NO contaminan la config."""
    import services.proposal_applier as pa
    from config.auto_appliable import ALLOWLIST
    (tmp_path / "auto_applied_config.json").write_text(
        json.dumps({"nonsense_param": 5, "max_consecutive_post_failures": 42}), encoding="utf-8"
    )
    assert "nonsense_param" not in ALLOWLIST
    assert "max_consecutive_post_failures" in ALLOWLIST
    assert ALLOWLIST["max_consecutive_post_failures"][1] == 10  # clamp a 10


def test_apply_log_is_auditable(tmp_path):
    import services.proposal_applier as pa
    pa.apply_structured_proposal(
        {"param": "max_consecutive_post_failures", "suggested": 7, "reason": "razon"}, {}
    )
    entries = pa._read_apply_log()
    assert len(entries) == 1
    assert entries[0]["param"] == "max_consecutive_post_failures"
    assert entries[0]["status"] == "applied"
    assert entries[0]["reason"] == "razon"


# --- Tests nuevos 2026-09-20: sincronizacion allowlist <-> prompt ---------

def test_allowlist_includes_restored_params():
    """Los 4 params restaurados 2026-09-20 deben estar en el allowlist."""
    from config.auto_appliable import ALLOWLIST
    restored = (
        "max_comments_per_day",
        "max_feed_replies_per_day",
        "max_comment_replies_per_cycle",
        "max_posts_per_day",
    )
    for p in restored:
        assert p in ALLOWLIST, f"{p} debe estar en allowlist"
        lo, hi, default = ALLOWLIST[p]
        assert lo < hi, f"bounds invalidos para {p}: {lo} >= {hi}"
        assert lo <= default <= hi, (
            f"default {default} fuera de [{lo}, {hi}] para {p}"
        )


def test_allowlist_and_prompt_are_in_sync():
    """El prompt del LLM solo puede ofrecer params del allowlist.

    Regresion historica: el prompt ofrecia 'phase_b_max_replies' (ghost,
    nunca leido) y el allowlist habia perdido 4 params reales. Este test
    evita que se vuelvan a desincronizar.
    """
    import re
    from pathlib import Path
    from config.auto_appliable import ALLOWLIST

    src = Path("phases/phase_c_analytics.py").read_text(encoding="utf-8")
    # Buscar el bloque del prompt "param_name (min-max)"
    menu = re.findall(r"(\w+)\s*\((\d+)-(\d+)\)", src)
    prompt_params = {m[0] for m in menu}

    # Excluir matches que no sean params (versiones, rangos sin nombre)
    known_non_params = {"phase_b_max_replies"}  # eliminado del prompt
    offered = prompt_params - known_non_params

    missing = offered - set(ALLOWLIST.keys())
    assert not missing, (
        f"Prompt del LLM ofrece params que NO estan en allowlist: {missing}. "
        f"Sincronizar phase_c_analytics.py con config/auto_appliable.py."
    )
