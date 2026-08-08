# -*- coding: utf-8 -*-
"""
Allowlist de parámetros de config autoaplicables por el motor de
auto-mejora (services/proposal_applier.py).

Módulo PURO (sin imports del paquete services ni de config.config) para que
config.config pueda importarlo al arranque sin riesgo de import circular.

Cada entrada: (min, max, default). Solo enteros.
"""

ALLOWLIST = {
    "max_comments_per_post": (0, 10, 3),
    "phase_b_max_replies": (1, 5, 1),
    "max_consecutive_post_failures": (1, 10, 3),
}
