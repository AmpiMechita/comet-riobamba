# -*- coding: utf-8 -*-
"""
Script de reporte diario para COMET-RIOBAMBA.

Uso:
    python -m scripts.print_daily_report              # hoy
    python -m scripts.print_daily_report 2026-06-09   # fecha específica

Incluye la seccion semanal de agentes que comentan en posts de agentes top
(snapshot generado por monitoring/_analyze_top_agent_commenters.py --weekly).
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.daily_metrics import load_metrics


def print_weekly_top_agents() -> None:
    """Imprime la seccion semanal de comentaristas en posts de agentes top."""
    path = Path("data/top_agent_commenters_weekly.json")
    if not path.exists():
        print("\n[SEMANAL] Snapshot no disponible. Ejecutar:")
        print("  python -m monitoring._analyze_top_agent_commenters --weekly")
        return
    try:
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("\n[SEMANAL] Snapshot corrupto en data/top_agent_commenters_weekly.json")
        return
    print(f"\n[SEMANAL] Quien comenta en posts de agentes top (snapshot {snap.get('date')}):")
    print(f"  karma={snap.get('karma')} unread={snap.get('unread_notifications')} "
          f"| upvotes ledger={snap.get('comment_votes_upvotes')}/{snap.get('comment_votes_checked')}")
    for c in snap.get("top_commenters", []):
        print(f"  - {c['author']:<32} comentarios={c['comments']:<5} "
              f"posts={c['posts']:<3} preguntas={c['questions']:<3} "
              f"overlap={c['avg_overlap']:<5} dual={c['avg_dual_score']}")


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

    if date_str == datetime.now().date().isoformat():
        print_weekly_top_agents()


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    print_report(date_arg)
