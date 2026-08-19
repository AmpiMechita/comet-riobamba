# -*- coding: utf-8 -*-
"""Panel de retorno de karma: mide si los cambios del agente mejoran la
recoleccion de karma real (la metrica externa de valor).

Consolida, POR DIA, las metricas que ya existen en el sistema:
  - delta de karma (primer vs ultimo snapshot del dia)   -> monitoring/snapshots.jsonl
  - ROI del ledger (upvotes/comentario)                  -> data/comment_votes.jsonl
  - actividad (posts, comentarios, inbound watchlist)    -> data/metrics/*.json
  - costo estimado (si el ledger de telemetry lo permite)

Escribe/actualiza un registro diario en monitoring/karma_trend.jsonl para
tener la serie temporal y poder comparar "antes vs despues" de un cambio.

Uso:
    python -m scripts.karma_roi_report            # muestra el reporte del dia
    python -m scripts.karma_roi_report --days 7   # muestra los ultimos N dias
    python -m scripts.karma_roi_report --record   # registra/actualiza el dia en el trend
"""

import json
import sys
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.comment_votes import votes_summary

SNAPSHOTS_PATH = Path("monitoring/snapshots.jsonl")
TREND_PATH = Path("monitoring/karma_trend.jsonl")
INBOUND_PATH = Path("data/watchlist_inbound_today.json")


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    except OSError:
        pass
    return out


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def karma_by_day() -> Dict[str, Dict[str, Any]]:
    """Por dia: karma inicial, final, delta y ultima hora observada."""
    by_day: Dict[str, Dict[str, Any]] = {}
    for r in _read_jsonl(SNAPSHOTS_PATH):
        ts = str(r.get("ts") or "")
        day = ts[:10]
        karma = r.get("karma")
        if karma is None:
            continue
        d = by_day.setdefault(day, {"first": karma, "last": karma, "last_ts": ts})
        # primero del dia = el de menor timestamp; comparar por string es ok (ISO)
        if ts < d.get("first_ts", "9999"):
            d["first"] = karma
            d["first_ts"] = ts
        if ts >= d.get("last_ts", ""):
            d["last"] = karma
            d["last_ts"] = ts
    return by_day


def _posts_per_day() -> Dict[str, int]:
    """posts publicados por dia desde data/published_posts.json (persistente,
    a diferencia de data/metrics/*.json que solo retiene el dia actual)."""
    path = Path("data/published_posts.json")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    items = data if isinstance(data, list) else data.get("posts", [])
    if isinstance(items, dict):
        items = list(items.values())
    out: Dict[str, int] = {}
    for p in items or []:
        ts = str(p.get("published_at") or p.get("published") or "")
        day = ts[:10]
        if day:
            out[day] = out.get(day, 0) + 1
    return out


def activity_for(day: str) -> Dict[str, Any]:
    """Actividad del dia: posts (published_posts persistente) + metricas."""
    posts_day = _posts_per_day()
    mf = Path("data/metrics") / f"{day}.json"
    m = _read_json(mf)
    return {
        "posts": int(posts_day.get(day, 0)) or int(m.get("posts_published", 0)),
        "comments": int(m.get("comments_published", 0)),
        "errors": int(m.get("errors_total", 0)),
        "cycles": int(m.get("cycle_count", 0)),
    }


def inbound_for(day: str) -> int:
    inbound = _read_json(INBOUND_PATH)
    if inbound.get("date") == day:
        counts = inbound.get("counts", {})
        return sum(int(v) for v in counts.values())
    return 0


def daily_report(day: str) -> Dict[str, Any]:
    """Reporte de un dia: karma delta + ROI + actividad + inbound."""
    kb = karma_by_day().get(day, {})
    act = activity_for(day)
    vs = votes_summary()
    rec = {
        "date": day,
        "karma_first": kb.get("first"),
        "karma_last": kb.get("last"),
        "karma_delta": (kb.get("last", 0) - kb.get("first", 0)) if kb.get("last") is not None and kb.get("first") is not None else None,
        "posts": act["posts"],
        "comments": act["comments"],
        "errors": act["errors"],
        "cycles": act["cycles"],
        "roi_comments_checked": int(vs.get("with_votes", 0)),
        "roi_upvotes": int(vs.get("total_upvotes", 0)),
        "inbound_watchlist": inbound_for(day),
    }
    if rec["roi_comments_checked"]:
        rec["roi_upvotes_per_comment"] = round(
            rec["roi_upvotes"] / rec["roi_comments_checked"], 3,
        )
    else:
        rec["roi_upvotes_per_comment"] = None
    return rec


def record_day(day: str, trend_path: Optional[Path] = None) -> Dict[str, Any]:
    """Registra/actualiza el reporte del dia en el trend (jsonl upsert por date)."""
    path = trend_path or TREND_PATH
    rec = daily_report(day)
    rows = [r for r in _read_jsonl(path) if r.get("date") != day]
    rows.append(rec)
    rows.sort(key=lambda r: r.get("date", ""))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"no se pudo escribir trend {path}: {e}")
    return rec


def print_report(days: int) -> None:
    kb = karma_by_day()
    dates = sorted(kb.keys(), reverse=True)[:days]
    if not dates:
        print("(sin snapshots de karma todavia)")
        return
    print(f"{'Fecha':<12} {'karma':>6} {'delta':>6} {'posts':>6} {'coms':>5} "
          f"{'upv/com':>8} {'inbound':>7} {'errs':>5}")
    print("-" * 68)
    for day in dates:
        r = daily_report(day)
        kd = r["karma_delta"]
        kd_s = f"{kd:+d}" if kd is not None else "  -"
        upc = f"{r['roi_upvotes_per_comment']:.3f}" if r["roi_upvotes_per_comment"] is not None else "  -"
        print(f"{day:<12} {r['karma_last']:>6} {kd_s:>6} {r['posts']:>6} {r['comments']:>5} "
              f"{upc:>8} {r['inbound_watchlist']:>7} {r['errors']:>5}")


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    days = 7
    record = "--record" in argv
    target_day: Optional[str] = None
    for a in argv:
        if a.startswith("--days"):
            try:
                days = int(argv[argv.index(a) + 1])
            except (ValueError, IndexError):
                pass
        if a.startswith("--date"):
            try:
                target_day = argv[argv.index(a) + 1]
            except IndexError:
                pass
    if record:
        day = target_day or datetime.now(timezone.utc).date().isoformat()
        rec = record_day(day)
        print(f"registrado {day}: karma_delta={rec['karma_delta']} roi={rec['roi_upvotes_per_comment']}")
    print_report(days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())