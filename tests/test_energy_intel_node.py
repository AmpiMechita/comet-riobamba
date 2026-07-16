# -*- coding: utf-8 -*-
"""Tests for docs/ein/energy_intel_node.py — DB_PATH resolution and ingest."""

import os
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _add_ein_to_path():
    """Ensure docs/ein/ is importable during tests."""
    ein_path = str(Path(__file__).resolve().parents[1] / "docs" / "ein")
    sys.path.insert(0, ein_path)
    yield
    # Cleanup not needed — tests run in isolated processes


def test_db_path_is_absolute():
    """DB_PATH must be an absolute path, not relative."""
    import energy_intel_node
    path = Path(energy_intel_node.DB_PATH)
    assert path.is_absolute(), f"DB_PATH is not absolute: {path}"


def test_db_path_ends_with_correct_location():
    """DB_PATH must resolve to data/energy_intel.db."""
    import energy_intel_node
    path = Path(energy_intel_node.DB_PATH)
    assert path.name == "energy_intel.db"
    assert path.parent.name == "data"


def test_db_path_independent_of_cwd(tmp_path):
    """DB_PATH must be the same regardless of the current working directory."""
    # Import the module with the original cwd
    import energy_intel_node
    original_path = energy_intel_node.DB_PATH

    # Change to a temp directory and re-import (force reload)
    old_cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        import importlib
        importlib.reload(energy_intel_node)
        new_path = energy_intel_node.DB_PATH
    finally:
        os.chdir(old_cwd)

    assert original_path == new_path, (
        f"DB_PATH changed with cwd:\n  original={original_path}\n  new={new_path}"
    )


def test_db_path_matches_orchestrator_energy_knowledge_base():
    """DB_PATH must point to the same file that EnergyKnowledgeBase uses."""
    import energy_intel_node
    from pathlib import Path as PathCls
    from config import BASE_DIR

    ein_path = Path(energy_intel_node.DB_PATH).resolve()
    kb_path = (BASE_DIR / "data" / "energy_intel.db").resolve()
    assert ein_path == kb_path, (
        f"DB_PATH mismatch:\n  ein={ein_path}\n  kb={kb_path}"
    )


def test_module_exports_run_ingest():
    """The module must export run_ingest function."""
    import energy_intel_node
    assert hasattr(energy_intel_node, "run_ingest")
    assert callable(energy_intel_node.run_ingest)
