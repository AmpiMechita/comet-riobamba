# -*- coding: utf-8 -*-
"""
Reporte diario del retorno por comentario.

Correlaciona los upvotes del ledger (comment_votes.jsonl) con:
  - el motivo de entrada (watchlist / historial / primera_interaccion / valor)
  - la edad del hilo al momento del comentario (dias desde el post propio)
  - el rango de score

Con esto se define, con datos, hasta cuando conviene comentar y que canal
produce retorno. Uso: python -m scripts.comment_roi_report
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

VOTES_PATH = Path("data/comment_votes.jsonl")
PUBLISHED_PATH = Path("data/published_posts.json")


def _post_published_at() -> dict:
    """post_id -> fecha de publicacion de los posts propios."""
    out = {}
    try:
        data = json.loads(PUBLISHED_PATH.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("posts", [])
        if isinstance(items, dict):
            items = list(items.values())
        for p in items or []:
            pid = p.get("post_id") or p.get("id")
            ts = p.get("published_at") or p.get("published") or ""
            if pid and ts:
                out[str(pid)] = ts
    except Exception:
        pass
    return out


def main() -> int:
    records = []
    if VOTES_PATH.exists():
        for line in VOTES_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not records:
        print("sin comentarios en el ledger aun")
        return 0

    post_dates = _post_published_at()
    checked = [r for r in records if r.get("upvotes") is not None]

    print(f"ledger: {len(records)} comentarios | revisados: {len(checked)}")
    print(f"upvotes totales: {sum(int(r.get('upvotes') or 0) for r in checked)}")

    # ── Por motivo de entrada ──
    by_reason = defaultdict(lambda: {"n": 0, "upvotes": 0})
    for r in checked:
        m = by_reason[r.get("reason") or "valor"]
        m["n"] += 1
        m["upvotes"] += int(r.get("upvotes") or 0)
    print("\n== POR MOTIVO ==")
    for reason in ("watchlist", "historial", "primera_interaccion", "valor"):
        m = by_reason.get(reason)
        if not m:
            continue
        tasa = m["upvotes"] / m["n"] * 100 if m["n"] else 0
        print(f"  {reason:20s} n={m['n']:3d} upvotes={m['upvotes']:2d} tasa={tasa:4.1f}%")

    # ── Por edad del hilo ──
    now = datetime.now(timezone.utc)
    by_age = defaultdict(lambda: {"n": 0, "upvotes": 0})
    for r in checked:
        pid = str(r.get("post_id") or "")
        ts = post_dates.get(pid)
        if not ts:
            by_age["post_desconocido"]["n"] += 1
            by_age["post_desconocido"]["upvotes"] += int(r.get("upvotes") or 0)
            continue
        try:
            pub = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            continue
        age_days = (now - pub).total_seconds() / 86400
        bucket = "mismo_dia" if age_days < 1 else f"{int(age_days)}d"
        m = by_age[bucket]
        m["n"] += 1
        m["upvotes"] += int(r.get("upvotes") or 0)
    print("\n== POR EDAD DEL HILO (al momento del refresh) ==")
    for age, m in sorted(by_age.items()):
        tasa = m["upvotes"] / m["n"] * 100 if m["n"] else 0
        print(f"  {age:16s} n={m['n']:3d} upvotes={m['upvotes']:2d} tasa={tasa:4.1f}%")

    # ── Por rango de score ──
    by_score = defaultdict(lambda: {"n": 0, "upvotes": 0})
    for r in checked:
        s = float(r.get("value_score") or 0.0)
        b = "<=0.3" if s <= 0.3 else "0.31-0.5" if s <= 0.5 else "0.51-0.7" if s <= 0.7 else ">0.7"
        m = by_score[b]
        m["n"] += 1
        m["upvotes"] += int(r.get("upvotes") or 0)
    print("\n== POR SCORE ==")
    for b, m in sorted(by_score.items()):
        tasa = m["upvotes"] / m["n"] * 100 if m["n"] else 0
        print(f"  {b:8s} n={m['n']:3d} upvotes={m['upvotes']:2d} tasa={tasa:4.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
