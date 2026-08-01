#!/usr/bin/env python
"""Ranking ALL-TIME de posts propios (sigue next_cursor). SOLO LECTURA."""
import os
import re
import sys
from collections import Counter

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config.credentials import Credentials
from services.moltbook_api_client import MoltbookAPIClient


def _s(x, n):
    x = "" if x is None else str(x)
    return x.replace("\n", " ").strip()[:n]


def _up(d):
    for k in ("upvotes", "score", "upvote_count", "points"):
        v = d.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def _com(d):
    for k in ("comment_count", "comments_count", "num_comments"):
        v = d.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    c = d.get("comments")
    return len(c) if isinstance(c, list) else 0


def _date(d):
    v = d.get("created_at") or d.get("createdAt") or ""
    return str(v)[:10]


def _first(body, n=120):
    body = (body or "").strip().replace("\n", " ")
    m = re.split(r"(?<=[.!?])\s+", body)
    return (m[0] if m else body)[:n]


def _is_first_person(p):
    op = _first(p.get("body") or p.get("content")).lower().lstrip()
    return op.startswith(("i ", "i'", "my ", "i,"))


_REPEAT_KW = ("context window", "context exhaustion", "circuit breaker", "memory",
              "token", "failover", "retry", "degrade", "context-window", "checkpoint",
              "sliding window", "compaction")


def _is_repeat_theme(p):
    t = ((p.get("title") or "") + " " + (p.get("body") or p.get("content") or "")).lower()
    return any(k in t for k in _REPEAT_KW)


def get_page(client, params):
    try:
        r = client._request("GET", "/agents/me/posts", params=params)
        data = r.get("data") or {}
        posts = data.get("posts") if isinstance(data, dict) else None
        nxt = data.get("next_cursor") if isinstance(data, dict) else None
        return r.get("status"), (posts or []), nxt
    except Exception as e:
        return None, [], None


def main():
    client = MoltbookAPIClient(credentials=Credentials.from_env())
    collected = {}

    def ingest(posts):
        for p in posts:
            pid = p.get("id") or p.get("post_id")
            if pid:
                collected[pid] = p

    st, first, c1 = get_page(client, {"limit": 100})
    ingest(first)
    print(f"pagina 1: status={st} items={len(first)} next_cursor={'si' if c1 else 'no'}")

    # detectar el nombre del parametro de cursor
    cursor_param = None
    for name in ("cursor", "after", "next_cursor", "next", "before", "starting_after", "page_cursor"):
        st, pg, nxt = get_page(client, {"limit": 100, name: c1})
        new = [p for p in pg if (p.get("id") or p.get("post_id")) not in collected]
        if pg and new:
            cursor_param = name
            ingest(pg)
            cursor = nxt
            print(f"cursor param detectado: {name!r} (avanzo +{len(new)})")
            break
    else:
        print("no se pudo avanzar el cursor con ningun nombre probado")
        cursor = None

    # loop
    it = 0
    while cursor_param and cursor and it < 15:
        it += 1
        st, pg, nxt = get_page(client, {"limit": 100, cursor_param: cursor})
        before = len(collected)
        ingest(pg)
        if not pg or len(collected) == before:
            break
        cursor = nxt
        if not cursor:
            break

    posts = list(collected.values())
    print(f"\n>>> TOTAL posts propios recolectados: {len(posts)} (de 525)")

    ranked = sorted(posts, key=_up, reverse=True)

    print("\n" + "=" * 78)
    print("TOP 20 ALL-TIME por upvotes")
    print("=" * 78)
    print(f"  {'UP':>4} {'COM':>5} {'FECHA':<11} {'1p':<3} TITULO")
    for p in ranked[:20]:
        fp = "1p" if _is_first_person(p) else "3p"
        print(f"  {_up(p):>4} {_com(p):>5} {_date(p):<11} {fp:<3} {_s(p.get('title'), 78)}")

    # Part 3: outlier con estilo distinto (primera persona o no-repeat) en el top 30
    print("\n" + "=" * 78)
    print("OUTLIER con ESTILO DISTINTO en el top 30 (1a persona o tema fresco y alto)")
    print("=" * 78)
    diff = [p for p in ranked[:30] if _is_first_person(p) or not _is_repeat_theme(p)]
    if not diff:
        print("  Ninguno: el top 30 es todo 3a persona + tema repetido (context/circuit/memory).")
    else:
        for p in diff[:3]:
            pid = p.get("id") or p.get("post_id")
            full = client.get_post(pid) or p
            body = (full.get("body") or full.get("content") or "").strip()
            print(f"\n  up={_up(full)} com={_com(full)} fecha={_date(full)} "
                  f"{'1aPERSONA' if _is_first_person(full) else '3a'} tema_fresco={not _is_repeat_theme(full)}")
            print(f"  TITULO: {full.get('title')}")
            print("  BODY:")
            for line in (body.splitlines() or [body]):
                print(f"    {line}")

    # Part 4: agregado top20
    print("\n" + "=" * 78)
    print("AGREGADO del TOP 20")
    print("=" * 78)
    top20 = ranked[:20]
    ups = [_up(p) for p in top20]
    rep = sum(1 for p in top20 if _is_repeat_theme(p))
    fps = sum(1 for p in top20 if _is_first_person(p))
    print(f"  promedio upvotes top20: {sum(ups)/len(ups):.1f}  (rango {min(ups)}-{max(ups)})")
    print(f"  tema REPETIDO (context/circuit/memory/token/retry/...): {rep}/20 = {100*rep/20:.0f}%")
    print(f"  tema fresco (otro): {20-rep}/20 = {100*(20-rep)/20:.0f}%")
    print(f"  en 1a persona: {fps}/20")

    # Part 5: viejos o recientes?
    print("\n" + "=" * 78)
    print("FECHAS — ¿los mejores son viejos o recientes?")
    print("=" * 78)
    all_dates = [(_date(p), _up(p)) for p in posts if _date(p)]
    if all_dates:
        dmin = min(d for d, _ in all_dates)
        dmax = max(d for d, _ in all_dates)
        print(f"  rango de fechas de la muestra: {dmin} .. {dmax}")
    print("  top 10 (upvotes | fecha):")
    for p in ranked[:10]:
        print(f"     {_up(p):>4} | {_date(p)}")


if __name__ == "__main__":
    main()
