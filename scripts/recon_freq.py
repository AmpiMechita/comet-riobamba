#!/usr/bin/env python
"""Frecuencia real de publicacion en Moltbook. SOLO LECTURA (GETs)."""
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config.credentials import Credentials
from services.moltbook_api_client import MoltbookAPIClient


def _author(p):
    a = p.get("author") or p.get("author_name") or p.get("username") or ""
    if isinstance(a, dict):
        return a.get("name") or a.get("username") or a.get("id") or "?"
    return str(a) if a else "?"


def _up(p):
    for k in ("upvotes", "score", "upvote_count", "points"):
        v = p.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def _ts(p):
    v = p.get("created_at") or p.get("createdAt") or p.get("published_at") or ""
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt, str(v)
    except Exception:
        return None, str(v)


def main():
    client = MoltbookAPIClient(credentials=Credentials.from_env())
    collected = {}
    cursor = None
    for _ in range(6):
        params = {"limit": 100, "sort": "new"}
        if cursor:
            params["cursor"] = cursor
        try:
            r = client._request("GET", "/posts", params=params)
            data = r.get("data") or {}
        except Exception as e:
            print("error:", e)
            break
        posts = data.get("posts") or data.get("items") or []
        for p in posts:
            pid = p.get("id") or p.get("post_id")
            if pid:
                collected[pid] = p
        cursor = data.get("next_cursor")
        if not cursor or len(collected) >= 200:
            break

    posts = list(collected.values())
    print(f"posts recolectados (sort=new): {len(posts)}")

    # timestamps parseados
    parsed = []
    for p in posts:
        dt, raw = _ts(p)
        if dt is not None:
            parsed.append((dt, raw, _author(p), _up(p)))
    if parsed:
        dts = [x[0] for x in parsed]
        print(f"ventana temporal: {min(dts).isoformat()}  ..  {max(dts).isoformat()}")

    by_author = defaultdict(list)
    for dt, raw, author, up in parsed:
        by_author[author].append((dt, raw, up))

    # metricas por autor (>=3 posts)
    stats = []
    for author, items in by_author.items():
        if len(items) < 3:
            continue
        items.sort(key=lambda x: x[0])
        intervals = [(items[i][0] - items[i - 1][0]).total_seconds() for i in range(1, len(items))]
        if not intervals:
            continue
        min_i = min(intervals)
        min_idx = intervals.index(min_i)
        avg_up = sum(x[2] for x in items) / len(items)
        stats.append({
            "author": author,
            "n": len(items),
            "min_s": min_i,
            "avg_s": sum(intervals) / len(intervals),
            "avg_up": avg_up,
            "closest_pair": (items[min_idx][1], items[min_idx + 1][1]),
        })

    stats.sort(key=lambda s: s["min_s"])

    print("\n" + "=" * 78)
    print("TOP 10 AUTORES POR FRECUENCIA (menor intervalo minimo primero, >=3 posts)")
    print("=" * 78)
    print(f"  {'AUTOR':<24} {'n':>3} {'min(s)':>8} {'avg(s)':>9} {'avg_up':>7}")
    for s in stats[:10]:
        print(f"  {s['author'][:24]:<24} {s['n']:>3} {s['min_s']:>8.1f} {s['avg_s']:>9.1f} {s['avg_up']:>7.1f}")

    print("\n  -- par de posts mas cercanos de los 5 de mayor frecuencia (ts crudos) --")
    for s in stats[:5]:
        a, b = s["closest_pair"]
        print(f"     @{s['author']}  Δ={s['min_s']:.1f}s")
        print(f"        {a}")
        print(f"        {b}")

    print("\n" + "=" * 78)
    print("MINIMO GLOBAL entre 2 posts consecutivos del mismo autor")
    print("=" * 78)
    if stats:
        g = min(stats, key=lambda s: s["min_s"])
        print(f"  {g['min_s']:.1f}s  (@{g['author']})")
        print(f"     posts: {g['closest_pair'][0]}  |  {g['closest_pair'][1]}")
        near6 = [s for s in stats if s["min_s"] <= 10]
        print(f"  autores con intervalo minimo <=10s: {len(near6)} -> {[s['author'] for s in near6]}")

    print("\n" + "=" * 78)
    print("CROSS-CHECK: frecuencia vs karma (avg upvotes)")
    print("=" * 78)
    hi = stats[:8]
    lo = sorted(stats, key=lambda s: -s["min_s"])[:8]
    if hi:
        print(f"  alta frecuencia (min_s mas chico): avg_up promedio = {sum(s['avg_up'] for s in hi)/len(hi):.1f}")
    if lo:
        print(f"  baja frecuencia (min_s mas grande): avg_up promedio = {sum(s['avg_up'] for s in lo)/len(lo):.1f}")
    print("  detalle alta frecuencia:")
    for s in hi:
        print(f"     @{s['author']:<22} min={s['min_s']:>7.1f}s  avg_up={s['avg_up']:>6.1f}  n={s['n']}")


if __name__ == "__main__":
    main()
