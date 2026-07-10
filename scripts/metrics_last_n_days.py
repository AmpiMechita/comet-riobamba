# -*- coding: utf-8 -*-
"""
Resumen de métricas de los últimos N días.

Uso:
    python -m scripts.metrics_last_n_days              # últimos 7 días
    python -m scripts.metrics_last_n_days --days 14    # últimos 14 días
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.metrics import load_metrics, METRICS_DIR


def print_summary(days: int = 7) -> None:
    today = datetime.now().date()
    print(f"{'Fecha':<14} {'Posts pub':>9} {'Posts skip':>10} {'Coms pub':>9} {'Errores':>8} {'Fail cons':>10} {'Dur avg':>8}")
    print("-" * 72)

    total_posts_pub = 0
    total_comments_pub = 0
    total_errors = 0
    found_any = False

    for i in range(days):
        date_str = (today - timedelta(days=i)).isoformat()
        metrics = load_metrics(date_str)
        d = metrics.to_dict()

        if d["cycle_count"] == 0 and d["posts_published"] == 0 and d["comments_published"] == 0:
            continue

        found_any = True
        total_posts_pub += d["posts_published"]
        total_comments_pub += d["comments_published"]
        total_errors += d["errors_total"]

        print(
            f"{d['date']:<14} "
            f"{d['posts_published']:>9} "
            f"{d['posts_skipped_daily_limit']:>10} "
            f"{d['comments_published']:>9} "
            f"{d['errors_total']:>8} "
            f"{d['consecutive_failures']:>10} "
            f"{d['last_cycle_duration_avg_s']:>8.1f}"
        )

    if not found_any:
        print("(no se encontraron archivos de métricas con actividad)")
    else:
        print("-" * 72)
        print(
            f"{'TOTAL':<14} "
            f"{total_posts_pub:>9} "
            f"{'':>10} "
            f"{total_comments_pub:>9} "
            f"{total_errors:>8}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resumen de métricas de los últimos N días")
    parser.add_argument("--days", type=int, default=7, help="Número de días a mostrar (default: 7)")
    args = parser.parse_args()
    print_summary(days=args.days)
