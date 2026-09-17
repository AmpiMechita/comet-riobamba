#!/usr/bin/env python
"""Reconocimiento de SOLO LECTURA de Moltbook. NO escribe nada (solo GETs).

Reutiliza MoltbookAPIClient con Credentials.from_env() — exactamente como
core/agent.py. `Credentials.from_env()` ya hace load_dotenv(override=True).

Uso:  ..venv\Scripts\python.exe scripts\recon_moltbook.py
"""
import os
import sys
from collections import Counter

# El script vive en scripts/, meter la raiz del repo en sys.path para los imports.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config.credentials import Credentials
from services.moltbook_api_client import MoltbookAPIClient


def _s(x, n):
    x = "" if x is None else str(x)
    return x.replace("\n", " ").strip()[:n]


def _author(p):
    a = p.get("author") or p.get("author_name") or p.get("username") or ""
    if isinstance(a, dict):
        return a.get("name") or a.get("username") or a.get("id") or "?"
    return str(a) if a else "?"


def _submolt(p):
    s = p.get("submolt") or p.get("community") or p.get("submolt_name") or ""
    if isinstance(s, dict):
        return s.get("name") or s.get("slug") or s.get("id") or "?"
    return str(s) if s else "?"


def _upvotes(p):
    for k in ("upvotes", "karma", "score", "upvote_count", "points", "votes", "net_votes"):
        v = p.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return None


def _ncomments(p):
    c = p.get("comments")
    if isinstance(c, list):
        return len(c)
    if isinstance(c, (int, float)):
        return int(c)
    for k in ("comment_count", "comments_count", "num_comments", "n_comments"):
        v = p.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return None


def section_a(client):
    print("=" * 72)
    print("A. DONDE ESTA COMET HOY")
    print("=" * 72)
    home = client.fetch_home_dashboard()
    if not home:
        print("  fetch_home_dashboard(): VACIO (fail-open / no disponible)")
    else:
        print(f"  karma:                {home.get('karma')}")
        print(f"  unread_notifications: {home.get('unread_notifications')}")
        print(f"  active_posts:         {home.get('active_posts')}")
        foll = home.get("followers") or home.get("follower_count") or home.get("standing")
        print(f"  followers/standing:   {foll if foll is not None else 'NO EXPUESTO por /home'}")
        print(f"  [keys crudas de /home: {sorted(home.keys())}]")
        act = home.get("activity_on_your_posts") or []
        print(f"  actividad en tus posts: {len(act)} entradas")
        for a in act[:10]:
            print(f"     - notif={a.get('new_notification_count')} | "
                  f"{_s(a.get('title'), 55)} | autores={a.get('authors')}")

    print("\n  --- fetch_my_posts(limit=20) ---")
    mine = client.fetch_my_posts(limit=20)
    print(f"  total posts propios: {len(mine)}")
    if mine:
        print(f"  [keys del primer post propio: {sorted(mine[0].keys())}]")
    ups = []
    for i, p in enumerate(mine, 1):
        title = _s(p.get("title") or p.get("topic"), 60)
        uv, nc = _upvotes(p), _ncomments(p)
        if uv is not None:
            ups.append(uv)
        uv_s = str(uv) if uv is not None else "n/a"
        nc_s = str(nc) if nc is not None else "n/a"
        print(f"  {i:2d}. up={uv_s:>4} com={nc_s:>3} | {title}")
    if ups:
        print(f"  PROMEDIO upvotes (n={len(ups)}): {sum(ups) / len(ups):.2f}")
    else:
        print("  PROMEDIO upvotes: n/a (el store de posts propios no trae upvotes/comentarios en vivo)")


def section_b(client):
    print("\n" + "=" * 72)
    print("B. QUE CONTENIDO GANA (TOP)")
    print("=" * 72)
    used_sort, top = None, []
    for s in ("top", "hot", "new"):
        top = client.fetch_posts(limit=50, sort=s)
        if top:
            used_sort = s
            break
    print(f"  sort usado: {used_sort!r}  (pedido 'top'; con fallback a hot/new si viene vacio)")
    print(f"  posts obtenidos: {len(top)}")
    if not top:
        print("  (sin datos — ningun sort devolvio posts)")
        return
    if top:
        print(f"  [keys del primer post del feed: {sorted(top[0].keys())}]")

    ranked = sorted(top, key=lambda p: (_upvotes(p) or 0), reverse=True)
    print("\n  -- Top 10 por upvotes/karma --")
    for i, p in enumerate(ranked[:10], 1):
        uv = _upvotes(p)
        print(f"  {i:2d}. up={str(uv) if uv is not None else 'n/a':>4} "
              f"[{_submolt(p)}] @{_author(p)} :: {_s(p.get('title'), 80)}")

    author_karma, author_freq, submolt_freq = Counter(), Counter(), Counter()
    for p in top:
        a, sm = _author(p), _submolt(p)
        author_freq[a] += 1
        author_karma[a] += (_upvotes(p) or 0)
        submolt_freq[sm] += 1

    print("\n  -- Autores 'top' (karma acumulado en el top50) --")
    for a, k in author_karma.most_common(10):
        print(f"     {k:>6} karma | {author_freq[a]:>2} posts | @{a}")
    print("\n  -- Submolts mas frecuentes en el top50 --")
    for sm, n in submolt_freq.most_common(10):
        print(f"     {n:>2}x | {sm}")

    print("\n  -- BODY COMPLETO de los 3 de mayor karma --")
    for i, p in enumerate(ranked[:3], 1):
        print(f"\n  [{i}] up={_upvotes(p)} [{_submolt(p)}] @{_author(p)}")
        print(f"      TITULO: {_s(p.get('title'), 120)}")
        body = (p.get("body") or p.get("content") or "").strip()
        print("      BODY:")
        for line in (body.splitlines() or [body]):
            print(f"        {line}")


def section_c(client):
    print("\n" + "=" * 72)
    print("C. QUE ESTA ACTIVO AHORA (HOT)")
    print("=" * 72)
    hot = client.fetch_posts(limit=30, sort="hot")
    print(f"  posts hot obtenidos: {len(hot)}")
    if not hot:
        print("  (sin datos hot)")
        return
    af, sf = Counter(), Counter()
    for p in hot:
        af[_author(p)] += 1
        sf[_submolt(p)] += 1
    print("\n  -- Autores mas frecuentes en hot --")
    for a, n in af.most_common(10):
        print(f"     {n:>2}x | @{a}")
    print("\n  -- Submolts mas frecuentes en hot (temas calientes) --")
    for sm, n in sf.most_common(10):
        print(f"     {n:>2}x | {sm}")


def main():
    client = MoltbookAPIClient(credentials=Credentials.from_env())
    section_a(client)
    section_b(client)
    section_c(client)
    print("\n[recon completo — solo lecturas, sin escrituras]")


if __name__ == "__main__":
    main()
