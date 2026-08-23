# -*- coding: utf-8 -*-
"""Flags compartidos del experimento best-of-N (A/B AGENT_QUALITY_BESTOF).

Fuente unica de verdad para Phase A (posts) y Phase B (replies selectivos).
Los modulos consumidores re-exportan los nombres originales para no romper
imports ni tests existentes.
"""
import os


def quality_bestof_enabled() -> bool:
    """A/B flag AGENT_QUALITY_BESTOF=1 activa best-of-N + auto-crítica."""
    return os.getenv("AGENT_QUALITY_BESTOF", "0") == "1"


def quality_bestof_n() -> int:
    try:
        n = int(os.getenv("QUALITY_BESTOF_N", "3"))
    except (TypeError, ValueError):
        n = 3
    return max(1, min(n, 5))
