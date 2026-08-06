#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spend Dashboard en vivo — gasto por tarea de los modelos LLM del agente.

Lee data/cascade_telemetry.jsonl (llamadas por ciclo con tokens + cost_usd)
y data/anthropic_spend_tracker.json (guard diario), agrega por caller/tarea
y por proveedor, y refresca en pantalla cada N segundos.

Uso:
    python -m scripts.spend_dashboard [--refresh 5] [--hours 24]
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
TELEMETRY = BASE_DIR / "data" / "cascade_telemetry.jsonl"
SPEND_TRACKER = BASE_DIR / "data" / "anthropic_spend_tracker.json"


def _load_telemetry() -> list:
    """Load current + archived telemetry (the .archive holds entries rotated out
    of the active file — ignoring it under-reports real spend by ~90%)."""
    entries = []
    files = [TELEMETRY, Path(str(TELEMETRY) + ".archive")]
    for path in files:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
    return entries


def _load_anthropic_tracker() -> dict:
    if not SPEND_TRACKER.exists():
        return {}
    try:
        return json.loads(SPEND_TRACKER.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _render(entries: list, tracker: dict, window_hours: int) -> None:
    os.system("cls" if os.name == "nt" else "clear")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    by_caller: dict = defaultdict(lambda: {"calls": 0, "cost": 0.0,
                                           "tokens_in": 0, "tokens_out": 0,
                                           "errors": 0})
    by_provider: dict = defaultdict(lambda: {"calls": 0, "cost": 0.0})
    total_cost = 0.0
    total_calls = 0

    for e in entries:
        try:
            ts = datetime.fromisoformat(e.get("ts", ""))
        except (ValueError, TypeError):
            continue
        if ts < cutoff:
            continue
        caller = str(e.get("caller") or "unknown")
        provider = str(e.get("provider") or "?")
        cost = float(e.get("cost_usd", 0.0) or 0.0)
        tin = int(e.get("input_tokens", 0) or 0)
        tout = int(e.get("output_tokens", 0) or 0)
        success = bool(e.get("success"))

        by_caller[caller]["calls"] += 1
        by_caller[caller]["cost"] += cost
        by_caller[caller]["tokens_in"] += tin
        by_caller[caller]["tokens_out"] += tout
        if not success:
            by_caller[caller]["errors"] += 1
        by_provider[provider]["calls"] += 1
        by_provider[provider]["cost"] += cost
        total_cost += cost
        total_calls += 1

    now_s = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    tracker_usd = float(tracker.get("total_usd", 0.0) or 0.0)
    tracker_date = tracker.get("date", "?")

    print(f"═══ GASTO LLM EN VIVO — ventana {window_hours}h ═══  {now_s}")
    print(f"Llamadas totales: {total_calls} | Costo estimado: ${total_cost:.4f}")
    print(f"Guard Anthropic (hoy {tracker_date}): ${tracker_usd:.4f}\n")

    print("── Por tarea (caller) ──────────────────────────────────────")
    rows = sorted(by_caller.items(), key=lambda kv: -kv[1]["cost"])
    print(f"{'TAREA':<28} {'CALLS':>6} {'ERR':>4} {'IN':>9} {'OUT':>9} {'COSTO':>10}")
    for caller, s in rows:
        print(f"{caller[:27]:<28} {s['calls']:>6} {s['errors']:>4} "
              f"{s['tokens_in']:>9} {s['tokens_out']:>9} ${s['cost']:>9.4f}")

    print("\n── Por proveedor ───────────────────────────────────────────")
    prows = sorted(by_provider.items(), key=lambda kv: -kv[1]["cost"])
    for provider, s in prows:
        pct = (s["cost"] / total_cost * 100) if total_cost else 0.0
        print(f"  {provider:<22} calls={s['calls']:>4}  ${s['cost']:>9.4f}  ({pct:>5.1f}%)")

    print("\n(Refrescando... Ctrl+C para salir)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dashboard de gasto LLM en vivo")
    parser.add_argument("--refresh", type=int, default=5, help="segundos entre refrescos")
    parser.add_argument("--hours", type=int, default=24, help="ventana de tiempo (horas)")
    parser.add_argument("--once", action="store_true", help="imprimir una sola vez y salir")
    args = parser.parse_args()

    try:
        while True:
            _render(_load_telemetry(), _load_anthropic_tracker(), args.hours)
            if args.once:
                break
            time.sleep(args.refresh)
    except KeyboardInterrupt:
        print("\nDashboard detenido.")


if __name__ == "__main__":
    main()
