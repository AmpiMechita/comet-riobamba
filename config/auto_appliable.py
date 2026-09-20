# -*- coding: utf-8 -*-
"""
Allowlist de parametros de config autoaplicables por el motor de
auto-mejora (services/proposal_applier.py).

Modulo PURO (sin imports del paquete services ni de config.config) para que
config.config pueda importarlo al arranque sin riesgo de import circular.

Cada entrada: (min, max, default). Solo enteros.

IMPORTANTE: el listado de parametros y rangos DEBE estar sincronizado con el
prompt de phase_c_analytics.py:_proposal_prompt (~L517). Si agregas un param
aca, agregalo ahi tambien.
"""

ALLOWLIST = {
    # --- Core (historico) ---
    "max_comments_per_post": (0, 10, 3),
    "max_consecutive_post_failures": (1, 10, 3),
    "phase_b_max_own_comments_per_cycle": (1, 50, 10),

    # --- Restaurados 2026-09-20 ---
    # Estaban activos (se aplicaron exitosamente entre 8/5 y 8/7) y
    # se perdieron del allowlist en un commit posterior. El LLM los
    # seguia proponiendo y eran rechazados silenciosamente con
    # 'param_not_in_allowlist'.
    "max_comments_per_day": (0, 50, 30),
    "max_feed_replies_per_day": (0, 20, 12),
    "max_comment_replies_per_cycle": (2, 10, 8),   # min=2: no desactivar Phase B
    "max_posts_per_day": (1, 10, 2),
}
