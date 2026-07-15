# -*- coding: utf-8 -*-
"""
Prueba básica de que los scripts operativos no fallan.
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.update({"DASHSCOPE_API_KEY": "sk-test", "MOLTBOOK_API_KEY": "sk-test"})

logging.basicConfig(level=logging.INFO, format="%(levelname)s|%(name)s|%(message)s")

from core.metrics import DailyMetrics, save_metrics, METRICS_DIR, ingest_event


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_metrics():
    if METRICS_DIR.exists():
        for f in METRICS_DIR.iterdir():
            f.unlink()
        METRICS_DIR.rmdir()
    import core.metrics as _m
    _m._current_metrics = None
    yield
    if METRICS_DIR.exists():
        for f in METRICS_DIR.iterdir():
            f.unlink()
        METRICS_DIR.rmdir()
    _m._current_metrics = None


# ── Tests ────────────────────────────────────────────────────────

def test_print_daily_report_with_existing_metrics():
    """print_daily_report no falla cuando hay métricas."""
    m = DailyMetrics(date_str="2026-06-09")
    m.cycle_count = 3
    m.posts_published = 1
    save_metrics(m)

    import scripts.print_daily_report as rpt
    try:
        rpt.print_report("2026-06-09")
    except Exception as e:
        pytest.fail(f"print_daily_report lanzó excepción: {e}")


def test_metrics_last_n_days_no_files():
    """metrics_last_n_days no falla cuando no hay archivos."""
    import scripts.metrics_last_n_days as mnd
    try:
        mnd.print_summary(days=3)
    except Exception as e:
        pytest.fail(f"metrics_last_n_days lanzó excepción: {e}")


def test_metrics_last_n_days_with_data():
    """metrics_last_n_days procesa archivos existentes."""
    hoy = datetime.now().date().isoformat()
    for i in range(3):
        from datetime import timedelta
        d = (datetime.now().date() - timedelta(days=i)).isoformat()
        m = DailyMetrics(date_str=d)
        m.cycle_count = 1
        m.posts_published = 1 if i == 0 else 0
        save_metrics(m)

    import scripts.metrics_last_n_days as mnd
    try:
        mnd.print_summary(days=5)
    except Exception as e:
        pytest.fail(f"metrics_last_n_days lanzó excepción: {e}")
