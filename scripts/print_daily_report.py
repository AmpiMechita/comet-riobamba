# -*- coding: utf-8 -*-
"""
Script de reporte diario para COMET-RIOBAMBA.

Uso:
    python -m scripts.print_daily_report              # hoy
    python -m scripts.print_daily_report 2026-06-09   # fecha específica
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.metrics import load_metrics


def print_report(date_str: str | None = None) -> None:
    if date_str is None:
        date_str = datetime.now().date().isoformat()

    metrics = load_metrics(date_str)
    d = metrics.to_dict()

    print(f"Fecha: {d['date']}")
    print(f"Ciclos ejecutados: {d['cycle_count']}")
    print(f"Posts publicados: {d['posts_published']} ({d['posts_skipped_daily_limit']} bloqueados por límite diario)")
    print(f"Comentarios publicados: {d['comments_published']}")
    print(f"Comentarios bloqueados (día/ciclo/post/relevancia/dup): "
          f"{d['comments_skipped_daily_limit']} / "
          f"{d['comments_skipped_per_cycle_limit']} / "
          f"{d['comments_skipped_per_post_limit']} / "
          f"{d['comments_skipped_low_relevance']} / "
          f"{d['comments_near_duplicate_skipped']}")
    print(f"Outbox posts reintentos: {d['outbox_posts_retried']}")
    print(f"Outbox comments reintentos: {d['comment_outbox_retried']}")
    print(f"Fase C ejecuciones: {d['phase_c_runs']}")
    print(f"Errores totales: {d['errors_total']}")
    print(f"Consecutive failures: {d['consecutive_failures']}")
    print(f"Duración promedio ciclo (s): {d['last_cycle_duration_avg_s']}")


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    print_report(date_arg)
