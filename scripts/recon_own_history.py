#!/usr/bin/env python
"""Caracterizar los ganadores REALES de comet_riobamba (los 525 posts del server).
SOLO LECTURA (GETs). No escribe nada.
"""
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


def _submolt(p):
    s = p.get("submolt") or p.get("community") or ""
    if isinstance(s, dict):
        return s.get("name") or s.get("slug") or "?"
    return str(s) if s else "?"


def _upvotes(d):
    for k in ("upvotes", "score", "upvote_count", "points", "votes", "net_votes"):
        v = d.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def _ncomments(d):
    for k in ("comment_count", "comments_count", "num_comments"):
        v = d.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    c = d.get("comments")
    return len(c) if isinstance(c, list) else 0


def _first_sentence(body, n=130):
    body = (body or "").strip().replace("\n", " ")
    m = re.split(r"(?<=[.!?])\s+", body)
    return (m[0] if m else body)[:n]


def raw(client, path, params=None):
    try:
        r = client._request("GET", path, params=params or {})
        return r.get("status"), (r.get("data") or {})
    except Exception as e:
        return None, {"_error": str(e)}


def items_of(data):
    if isinstance(data, dict):
        for k in ("posts", "items", "data", "results", "comments"):
            v = data.get(k)
            if isinstance(v, list):
                return v
    if isinstance(data, list):
        return data
    return []


def main():
    client = MoltbookAPIClient(credentials=Credentials.from_env())

    st, me = raw(client, "/agents/me")
    prof = me.get("agent") or me.get("profile") or me
    aid = prof.get("id")
    aname = prof.get("name") or prof.get("display_name") or "comet_riobamba"
    print(f"agente: name={aname} id={aid} karma={prof.get('karma')} posts_count={prof.get('posts_count')}")

    print("\n" + "=" * 74)
    print("1. PROBE de endpoints de posts propios")
    print("=" * 74)
    candidates = [
        ("/agents/me/posts", None),
        (f"/agents/{aid}/posts", None),
        (f"/agents/{aname}/posts", None),
        ("/posts", {"author": aname}),
        ("/posts", {"author_id": aid}),
        (f"/users/{aname}/posts", None),
        ("/agents/me/posts", {"limit": 100}),
    ]
    working = None
    for path, params in candidates:
        st, data = raw(client, path, params)
        n = len(items_of(data))
        keys = sorted(data.keys()) if isinstance(data, dict) else "list"
        print(f"  GET {path} params={params} -> status={st} items={n} data_keys={keys}")
        if st and 200 <= st < 300 and n > 0 and working is None:
            working = (path, params, data)

    if not working:
        print("\n  Ningun endpoint devolvio posts propios. No puedo traer el historico server-side.")
        return

    path, params, first_data = working
    print(f"\n  --> endpoint elegido: GET {path} params={params}")

    # Paginacion: probar limit/offset y page
    collected = {}
    def _ingest(data):
        for p in items_of(data):
            pid = p.get("id") or p.get("post_id")
            if pid:
                collected[pid] = p

    _ingest(first_data)
    got_more = True
    # intento offset
    for off in range(0, 700, 100):
        st, data = raw(client, path, {**(params or {}), "limit": 100, "offset": off})
        n = len(items_of(data))
        if st and 200 <= st < 300 and n:
            before = len(collected)
            _ingest(data)
            if len(collected) == before:
                break
        else:
            break
    # si offset no crecio, intento page
    if len(collected) <= 100:
        for pg in range(1, 8):
            st, data = raw(client, path, {**(params or {}), "limit": 100, "page": pg})
            n = len(items_of(data))
            if st and 200 <= st < 300 and n:
                before = len(collected)
                _ingest(data)
                if len(collected) == before:
                    break
            else:
                break

    posts = list(collected.values())
    print(f"  posts propios recolectados: {len(posts)}")

    ranked = sorted(posts, key=_upvotes, reverse=True)

    print("\n" + "=" * 74)
    print("2. TOP 15 posts propios por upvotes")
    print("=" * 74)
    print(f"  {'UP':>5} {'COM':>5}  {'SUBMOLT':<12} TITULO")
    for p in ranked[:15]:
        print(f"  {_upvotes(p):>5} {_ncomments(p):>5}  {_s(_submolt(p),12):<12} {_s(p.get('title'),80)}")

    print("\n" + "=" * 74)
    print("3. BODY COMPLETO de los 5 propios de mayor upvotes (via get_post, sin truncar)")
    print("=" * 74)
    for i, p in enumerate(ranked[:5], 1):
        pid = p.get("id") or p.get("post_id")
        full = client.get_post(pid) or p
        body = (full.get("body") or full.get("content") or "").strip()
        print("\n  " + "-" * 70)
        print(f"  [{i}] up={_upvotes(full)} com={_ncomments(full)} submolt=[{_submolt(full)}] len={len(body)}ch")
        print(f"      TITULO: {full.get('title')}")
        print("      BODY:")
        for line in (body.splitlines() or [body]):
            print(f"        {line}")

    print("\n" + "=" * 74)
    print("4. AGREGADO — patron de los top 20 propios")
    print("=" * 74)
    top20 = ranked[:20]
    fp = sum(1 for p in top20 if _first_sentence(p.get("body") or p.get("content")).lower().lstrip().startswith(("i ", "i'", "my ", "i,")))
    print(f"  arranque en 1a persona ('I'/'my'): {fp}/{len(top20)}")
    print("  COMO ABREN (top 20, por upvotes):")
    for p in top20:
        print(f"     [{_upvotes(p):>4}] {_first_sentence(p.get('body') or p.get('content'))}")

    print("\n" + "=" * 74)
    print("5. COMENTARIOS propios (probe de endpoint)")
    print("=" * 74)
    c_candidates = [
        ("/agents/me/comments", None),
        (f"/agents/{aid}/comments", None),
        (f"/agents/{aname}/comments", None),
        ("/comments", {"author": aname}),
    ]
    c_work = None
    for path, params in c_candidates:
        st, data = raw(client, path, params)
        n = len(items_of(data))
        print(f"  GET {path} params={params} -> status={st} items={n}")
        if st and 200 <= st < 300 and n > 0 and c_work is None:
            c_work = items_of(data)
    if c_work:
        cranked = sorted(c_work, key=_upvotes, reverse=True)
        print("\n  -- Top 5 comentarios propios por upvotes --")
        for i, c in enumerate(cranked[:5], 1):
            txt = (c.get("text") or c.get("content") or c.get("body") or "").strip()
            print(f"\n  [{i}] up={_upvotes(c)}")
            print(f"      {txt}")
    else:
        print("  Ningun endpoint de comentarios propios devolvio datos.")


if __name__ == "__main__":
    main()
