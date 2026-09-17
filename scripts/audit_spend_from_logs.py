#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COMET-RIOBAMBA - DeepSeek Spend Audit from Logs
Reconstruye historial de gasto DeepSeek de los últimos 30 días
a partir de logs existentes (cascade_telemetry.jsonl, agent.log, deepseek_spend_tracker.json).

Solo lectura. NO llama a la API de DeepSeek.
"""

import json
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Asegurar que el directorio raíz esté en el path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("audit_spend_from_logs")

# ─── Configuración de precios (agosto 2026) ───
# Precios en CNY por 1M tokens (input_miss, input_hit, output)
# Flash valle: input miss ¥1.5/M, hit ¥0.05/M, output ¥4.5/M
# Flash pico:  input miss ¥3.0/M, hit ¥0.10/M, output ¥9.0/M
# Pro valle:   input miss ¥4.5/M, hit ¥0.15/M, output ¥13.5/M
# Pro pico:    input miss ¥9.0/M, hit ¥0.30/M, output ¥27.0/M

PRICES_CNY_PER_1M = {
    "flash": {"valley": (1.5, 0.05, 4.5), "peak": (3.0, 0.10, 9.0)},
    "pro":   {"valley": (4.5, 0.15, 13.5), "peak": (9.0, 0.30, 27.0)},
}

CNY_TO_USD = 7.2

# Horario pico Beijing (UTC+8): 09:00-12:00 y 14:00-18:00 Beijing = 01:00-04:00 y 06:00-10:00 UTC
def is_peak_hour_beijing(ts: datetime) -> bool:
    """True si la hora UTC cae en horario pico de Beijing."""
    hour_utc = ts.hour
    return (1 <= hour_utc < 4) or (6 <= hour_utc < 10)


def estimate_cost_usd(provider: str, input_tokens: int, output_tokens: int, ts: datetime) -> float:
    """
    Estima costo USD usando precios por tier y horario pico/valle.
    provider: 'tier_fallback', 'tier_pro', 'tier_flash', 'tier_flash' (via zen), etc.
    """
    provider_lower = provider.lower()
    if "pro" in provider_lower or "fallback" in provider_lower:
        tier = "pro"
    elif "flash" in provider_lower:
        tier = "flash"
    else:
        # default a pro para safety (más caro)
        tier = "pro"

    is_peak = is_peak_hour_beijing(ts)
    period = "peak" if is_peak else "valley"
    in_miss, in_hit, out_price = PRICES_CNY_PER_1M[tier][period]

    # Asumimos todo input como "miss" (conservador = más caro)
    cost_cny = (input_tokens * in_miss + output_tokens * out_price) / 1_000_000
    return cost_cny / CNY_TO_USD


def parse_telemetry_file(path: Path) -> List[Dict[str, Any]]:
    """Parsea data/cascade_telemetry.jsonl"""
    events = []
    if not path.exists():
        logger.warning("Telemetry file no existe: %s", path)
        return events

    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                # Normalizar campos
                ts_str = data.get("ts")
                if ts_str:
                    # Parsear timestamp ISO con timezone
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                else:
                    continue
                provider = data.get("provider", "")
                tier = data.get("tier", "")
                input_tokens = int(data.get("input_tokens", 0) or 0)
                output_tokens = int(data.get("output_tokens", 0) or 0)
                cost_usd = float(data.get("cost_usd", 0.0) or 0.0)
                success = bool(data.get("success", False))
                caller = data.get("caller", "unknown")

                events.append({
                    "ts": ts,
                    "provider": provider,
                    "tier": tier,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost_usd,
                    "success": success,
                    "caller": caller,
                    "source": "telemetry",
                })
            except Exception as e:
                logger.debug("Error parseando telemetry línea %d: %s", i, e)
    logger.info("Telemetry: %d eventos parseados", len(events))
    return events


def parse_agent_log(path: Path, days_back: int = 30) -> List[Dict[str, Any]]:
    """
    Parsea logs/agent.log buscando líneas de model_cascade con costos.
    Patrón: "Phase A: costos capturados - input=X, output=Y, cost=$Z"
    o "Phase B: costos capturados - input=X, output=Y, cost=$Z"
    """
    events = []
    if not path.exists():
        logger.warning("Agent log no existe: %s", path)
        return events

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    pattern = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (?:INFO|WARNING) \| (?:phases\.phase_[ab])\.phase_[ab] \| "
        r"(?:Phase [AB]: costos capturados - input=(\d+), output=(\d+), cost=\$([0-9.]+))"
    )
    # También buscar logs de model_cascade con AUDIT DEEPSEEK
    audit_pattern = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| INFO \| services\.model_cascade \| "
        r"AUDIT DEEPSEEK: provider=(\w+) tier=(\w+) caller=(\w+) input_tokens=(\d+) output_tokens=(\d+) cost_usd=([0-9.]+)"
    )

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            # Intentar pattern de Phase A/B costos
            m = pattern.search(line)
            if m:
                ts_str = m.group(1)
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                input_tokens = int(m.group(2))
                output_tokens = int(m.group(3))
                cost_usd = float(m.group(4))
                events.append({
                    "ts": ts,
                    "provider": "tier_fallback",  # Phase A usa fallback
                    "tier": "premium",
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost_usd,
                    "success": True,
                    "caller": "phase_a_or_b",
                    "source": "agent_log_cost",
                })
                continue

            # Intentar pattern AUDIT DEEPSEEK
            m = audit_pattern.search(line)
            if m:
                ts_str = m.group(1)
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                provider = m.group(2)
                tier = m.group(3)
                input_tokens = int(m.group(4))
                output_tokens = int(m.group(5))
                cost_usd = float(m.group(6))
                events.append({
                    "ts": ts,
                    "provider": provider,
                    "tier": tier,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost_usd,
                    "success": True,
                    "caller": m.group(4),
                    "source": "agent_log_audit",
                })

    logger.info("Agent log: %d eventos de costo parseados", len(events))
    return events


def load_spend_tracker(path: Path) -> List[Dict[str, Any]]:
    """Carga data/deepseek_spend_tracker.json (puede tener múltiples líneas o ser un solo objeto)"""
    events = []
    if not path.exists():
        logger.warning("Spend tracker no existe: %s", path)
        return events

    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
        if not content:
            return events

        # Intentar parsear como JSON lines o JSON único
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                date_str = data.get("date")
                total_usd = float(data.get("total_usd", 0.0))
                if date_str:
                    ts = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
                    events.append({
                        "ts": ts,
                        "provider": "tracker",
                        "tier": "daily_total",
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost_usd": total_usd,
                        "success": True,
                        "caller": "tracker",
                        "source": "spend_tracker",
                    })
            except Exception as e:
                logger.debug("Error parseando tracker línea: %s", e)
    logger.info("Spend tracker: %d días", len(events))
    return events


def load_all_logs(days_back: int = 30) -> List[Dict[str, Any]]:
    """Carga y combina todas las fuentes de datos."""
    all_events = []

    # 1. Telemetry (fuente principal, más completa)
    telemetry = parse_telemetry_file(ROOT_DIR / "data" / "cascade_telemetry.jsonl")
    all_events.extend(telemetry)

    # 2. Agent log (complementa con Phase A/B costos)
    agent_log = parse_agent_log(ROOT_DIR / "logs" / "agent.log", days_back)
    all_events.extend(agent_log)

    # 3. Spend tracker (totales diarios)
    tracker = load_spend_tracker(ROOT_DIR / "data" / "deepseek_spend_tracker.json")
    all_events.extend(tracker)

    # Filtrar por rango temporal
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    all_events = [e for e in all_events if e["ts"] >= cutoff]

    # Deduplicar por (ts, provider, input_tokens, output_tokens) - mantener el de mayor prioridad
    # Prioridad: telemetry > agent_log_audit > agent_log_cost > tracker
    priority = {"telemetry": 4, "agent_log_audit": 3, "agent_log_cost": 2, "spend_tracker": 1}
    dedup_key = {}
    for e in all_events:
        key = (e["ts"].isoformat(), e["provider"], e["input_tokens"], e["output_tokens"])
        if key not in dedup_key or priority.get(e["source"], 0) > priority.get(dedup_key[key]["source"], 0):
            dedup_key[key] = e

    unique_events = list(dedup_key.values())
    unique_events.sort(key=lambda x: x["ts"])

    logger.info("Total eventos únicos en rango %d días: %d", days_back, len(unique_events))
    return unique_events


def compute_daily_stats(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calcula estadísticas diarias."""
    daily = defaultdict(lambda: {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "by_tier": defaultdict(lambda: {"calls": 0, "cost": 0.0}),
        "by_provider": defaultdict(lambda: {"calls": 0, "cost": 0.0}),
        "by_caller": defaultdict(lambda: {"calls": 0, "cost": 0.0}),
    })

    for e in events:
        day = e["ts"].date().isoformat()
        d = daily[day]
        d["calls"] += 1
        d["input_tokens"] += e["input_tokens"]
        d["output_tokens"] += e["output_tokens"]
        d["cost_usd"] += e["cost_usd"]
        d["by_tier"][e["tier"]]["calls"] += 1
        d["by_tier"][e["tier"]]["cost"] += e["cost_usd"]
        d["by_provider"][e["provider"]]["calls"] += 1
        d["by_provider"][e["provider"]]["cost"] += e["cost_usd"]
        d["by_caller"][e["caller"]]["calls"] += 1
        d["by_caller"][e["caller"]]["cost"] += e["cost_usd"]

    # Convertir defaultdicts a dicts normales
    result = {}
    for day, stats in daily.items():
        result[day] = {
            "calls": stats["calls"],
            "input_tokens": stats["input_tokens"],
            "output_tokens": stats["output_tokens"],
            "cost_usd": round(stats["cost_usd"], 6),
            "by_tier": {k: {"calls": v["calls"], "cost_usd": round(v["cost"], 6)} for k, v in stats["by_tier"].items()},
            "by_provider": {k: {"calls": v["calls"], "cost_usd": round(v["cost"], 6)} for k, v in stats["by_provider"].items()},
            "by_caller": {k: {"calls": v["calls"], "cost_usd": round(v["cost"], 6)} for k, v in stats["by_caller"].items()},
        }
    return result


def detect_bursts(events: List[Dict[str, Any]], window_minutes: int = 10, threshold: int = 10) -> List[Dict[str, Any]]:
    """Detecta bursts: más de N llamadas en ventana de M minutos."""
    if not events:
        return []

    events_sorted = sorted(events, key=lambda x: x["ts"])
    bursts = []

    for i, e in enumerate(events_sorted):
        window_end = e["ts"] + timedelta(minutes=window_minutes)
        count = 1
        total_cost = e["cost_usd"]
        for j in range(i + 1, len(events_sorted)):
            if events_sorted[j]["ts"] <= window_end:
                count += 1
                total_cost += events_sorted[j]["cost_usd"]
            else:
                break
        if count >= threshold:
            bursts.append({
                "start_ts": e["ts"].isoformat(),
                "end_ts": window_end.isoformat(),
                "calls": count,
                "total_cost_usd": round(total_cost, 6),
                "providers": list(set(ev["provider"] for ev in events_sorted[i:i+count])),
            })

    # Filtrar bursts solapados (mantener el de mayor count)
    bursts.sort(key=lambda x: x["calls"], reverse=True)
    filtered = []
    for b in bursts:
        start = datetime.fromisoformat(b["start_ts"])
        end = datetime.fromisoformat(b["end_ts"])
        overlap = False
        for f in filtered:
            f_start = datetime.fromisoformat(f["start_ts"])
            f_end = datetime.fromisoformat(f["end_ts"])
            if start < f_end and end > f_start:
                overlap = True
                break
        if not overlap:
            filtered.append(b)

    return filtered[:20]  # top 20


def compute_summary(events: List[Dict[str, Any]], daily_stats: Dict[str, Any]) -> Dict[str, Any]:
    """Calcula resumen ejecutivo."""
    if not events:
        return {
            "total_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": 0.0,
            "date_range": None,
            "by_tier": {},
            "by_provider": {},
            "top_days": [],
            "bursts": [],
        }

    total_calls = len(events)
    total_input = sum(e["input_tokens"] for e in events)
    total_output = sum(e["output_tokens"] for e in events)
    total_cost = sum(e["cost_usd"] for e in events)

    # Agregado por tier
    by_tier = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    by_provider = defaultdict(lambda: {"calls": 0, "cost_usd": 0.0})
    for e in events:
        t = by_tier[e["tier"]]
        t["calls"] += 1
        t["input_tokens"] += e["input_tokens"]
        t["output_tokens"] += e["output_tokens"]
        t["cost_usd"] += e["cost_usd"]
        p = by_provider[e["provider"]]
        p["calls"] += 1
        p["cost_usd"] += e["cost_usd"]

    # Top 10 días por gasto
    top_days = sorted(
        [(day, stats["cost_usd"], stats["calls"]) for day, stats in daily_stats.items()],
        key=lambda x: x[1],
        reverse=True,
    )[:10]

    # Bursts
    bursts = detect_bursts(events)

    # Rango temporal
    min_ts = min(e["ts"] for e in events)
    max_ts = max(e["ts"] for e in events)

    return {
        "total_calls": total_calls,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cost_usd": round(total_cost, 6),
        "date_range": {
            "start": min_ts.isoformat(),
            "end": max_ts.isoformat(),
            "days_covered": len(daily_stats),
        },
        "by_tier": {k: {"calls": v["calls"], "input_tokens": v["input_tokens"], "output_tokens": v["output_tokens"], "cost_usd": round(v["cost_usd"], 6)} for k, v in by_tier.items()},
        "by_provider": {k: {"calls": v["calls"], "cost_usd": round(v["cost_usd"], 6)} for k, v in by_provider.items()},
        "top_10_days": [{"date": d, "cost_usd": round(c, 6), "calls": n} for d, c, n in top_days],
        "bursts_detected": bursts,
    }


def main() -> int:
    days_back = 30
    logger.info("=" * 60)
    logger.info("DeepSeek Spend Audit - últimos %d días", days_back)
    logger.info("=" * 60)

    # Cargar todos los eventos
    events = load_all_logs(days_back)

    if not events:
        logger.warning("No se encontraron eventos en el rango temporal")
        # Crear reporte vacío
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days_analyzed": days_back,
            "summary": {
                "total_calls": 0,
                "total_cost_usd": 0.0,
                "message": "No data found in logs for this period",
            },
        }
    else:
        # Calcular estadísticas
        daily_stats = compute_daily_stats(events)
        summary = compute_summary(events, daily_stats)

        # Recalcular costos con precios actuales para events de telemetry (más precisos)
        # Los costos en telemetry ya usan _estimate_cost_usd del model_cascade (precios dinámicos)
        # Para consistencia, usamos los costos ya calculados en telemetry

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days_analyzed": days_back,
            "data_sources": {
                "cascade_telemetry_jsonl": True,
                "agent_log": (ROOT_DIR / "logs" / "agent.log").exists(),
                "deepseek_spend_tracker": (ROOT_DIR / "data" / "deepseek_spend_tracker.json").exists(),
            },
            "summary": summary,
            "daily_breakdown": daily_stats,
        }

    # Guardar reporte
    out_file = ROOT_DIR / "data" / f"logs_audit_{datetime.now().strftime('%Y%m%d')}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    logger.info("Reporte guardado en: %s", out_file)

    # Imprimir resumen ejecutivo (máx 40 líneas)
    s = report.get("summary", {})
    print("\n" + "=" * 60)
    print("DEEPSEEK SPEND AUDIT - RESUMEN EJECUTIVO")
    print("=" * 60)
    print(f"Rango analizado:     {s.get('date_range', {}).get('start', 'N/A')[:10]}  →  {s.get('date_range', {}).get('end', 'N/A')[:10]}")
    print(f"Días con actividad:  {s.get('date_range', {}).get('days_covered', 0)}")
    print(f"Total llamadas:      {s.get('total_calls', 0)}")
    print(f"Tokens input:        {s.get('total_input_tokens', 0):,}")
    print(f"Tokens output:       {s.get('total_output_tokens', 0):,}")
    print(f"Gasto estimado USD:  ${s.get('total_cost_usd', 0.0):.6f}")
    print()
    print("Por tier:")
    for tier, stats in s.get("by_tier", {}).items():
        print(f"  {tier:15s}: {stats['calls']:4d} llamadas, ${stats['cost_usd']:.6f}")
    print()
    print("Por provider:")
    for prov, stats in s.get("by_provider", {}).items():
        print(f"  {prov:15s}: {stats['calls']:4d} llamadas, ${stats['cost_usd']:.6f}")
    print()
    print("Top 5 días por gasto:")
    for i, day in enumerate(s.get("top_10_days", [])[:5], 1):
        print(f"  {i}. {day['date']}  ${day['cost_usd']:.6f}  ({day['calls']} llamadas)")
    print()
    if s.get("bursts_detected"):
        print(f"Bursts detectados:   {len(s['bursts_detected'])} (>{10} llamadas/10min)")
        for b in s["bursts_detected"][:3]:
            print(f"  {b['start_ts'][:19]}  {b['calls']} calls  ${b['total_cost_usd']:.6f}")
    else:
        print("Bursts detectados:   0")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())