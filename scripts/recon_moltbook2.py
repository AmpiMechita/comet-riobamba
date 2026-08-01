#!/usr/bin/env python
"""Reconocimiento SOLO LECTURA (parte 2): engagement real por post propio +
desarme del estilo del autor #1. NO escribe nada (solo GETs).

Correr:  python scripts/recon_moltbook2.py
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
    for k in ("upvotes", "score", "karma", "upvote_count", "points", "votes", "net_votes"):
        v = p.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return None


def _ncomments(p):
    for k in ("comment_count", "comments_count", "num_comments", "n_comments"):
        v = p.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    c = p.get("comments")
    if isinstance(c, list):
        return len(c)
    if isinstance(c, (int, float)):
        return int(c)
    return None


def _first_sentence(body, n=140):
    body = (body or "").strip().replace("\n", " ")
    m = re.split(r"(?<=[.!?])\s+", body)
    return (m[0] if m else body)[:n]


def part1(client):
    print("=" * 74)
    print("PARTE 1 — ENGAGEMENT REAL POR POST PROPIO (get_post por id)")
    print("=" * 74)
    mine = client.fetch_my_posts(limit=20)
    print(f"  posts propios en store: {len(mine)}\n")

    rows = []
    for p in mine:
        pid = p.get("id") or p.get("post_id") or p.get("postId")
        topic = p.get("topic") or p.get("title") or ""
        live = client.get_post(pid) if pid else None
        if not live:
            rows.append((topic, None, None, "n/a", topic, pid))
            continue
        title = live.get("title") or topic
        rows.append((title, _upvotes(live), _ncomments(live), _submolt(live), topic, pid))

    print(f"  {'TITULO (70)':<72} {'UP':>5} {'COM':>4} {'SUBMOLT':<10}")
    print("  " + "-" * 94)
    for title, uv, nc, sm, topic, pid in rows:
        uv_s = str(uv) if uv is not None else "n/a"
        nc_s = str(nc) if nc is not None else "n/a"
        print(f"  {_s(title,70):<72} {uv_s:>5} {nc_s:>4} {_s(sm,10):<10}")

    # Grupos: (a) arXiv-derivado (topic con 'paper')  vs  (b) topic propio
    a_ups, b_ups, a_com, b_com = [], [], [], []
    print("\n  -- Clasificacion por TOPIC del store (no por titulo publicado) --")
    for title, uv, nc, sm, topic, pid in rows:
        is_arxiv = "paper" in (topic or "").lower()
        grp = "a(arXiv)" if is_arxiv else "b(propio)"
        print(f"     [{grp:>9}] up={uv if uv is not None else 'n/a'} com={nc if nc is not None else 'n/a'} | {_s(topic,60)}")
        if uv is not None:
            (a_ups if is_arxiv else b_ups).append(uv)
        if nc is not None:
            (a_com if is_arxiv else b_com).append(nc)

    def _avg(xs):
        return f"{sum(xs)/len(xs):.2f}" if xs else "n/a"

    print("\n  -- PROMEDIOS por grupo (upvotes reales) --")
    print(f"     (a) arXiv   : n={len(a_ups)} | avg upvotes={_avg(a_ups)} | avg comentarios={_avg(a_com)}")
    print(f"     (b) propio  : n={len(b_ups)} | avg upvotes={_avg(b_ups)} | avg comentarios={_avg(b_com)}")


def part2(client):
    print("\n" + "=" * 74)
    print("PARTE 2 — DESARMAR LA FORMULA DEL AUTOR #1 (@Hazel_OC)")
    print("=" * 74)
    top = client.fetch_posts(limit=100, sort="top")
    print(f"  top100 obtenidos: {len(top)}")

    def _by(name_frag):
        frag = name_frag.lower()
        return [p for p in top if frag in _author(p).lower()]

    target, label = _by("hazel"), "Hazel_OC"
    if not target:
        target, label = _by("ronin"), "Ronin (fallback: Hazel no aparece en top100)"
    print(f"  autor analizado: {label}  |  posts suyos en top100: {len(target)}")
    if not target:
        print("  (ni Hazel ni Ronin aparecen en el top100)")
        return

    ranked = sorted(target, key=lambda p: (_upvotes(p) or 0), reverse=True)

    # Agregados
    lens_c = [len(p.get("body") or p.get("content") or "") for p in target]
    lens_w = [len((p.get("body") or p.get("content") or "").split()) for p in target]
    print(f"\n  -- Agregado sobre {label} (n={len(target)} posts en top100) --")
    if lens_c:
        print(f"     largo promedio: {sum(lens_c)/len(lens_c):.0f} chars / {sum(lens_w)/len(lens_w):.0f} palabras")
        print(f"     rango: {min(lens_c)}-{max(lens_c)} chars")
    sub = Counter(_submolt(p) for p in target)
    print(f"     submolts: {dict(sub)}")
    print("     COMO ABREN (primera frase de cada uno, ordenado por upvotes):")
    for p in ranked:
        print(f"        [{_upvotes(p)}] {_first_sentence(p.get('body') or p.get('content'))}")

    print(f"\n  -- TOP 5 posts de {label}: titulo + BODY COMPLETO --")
    for i, p in enumerate(ranked[:5], 1):
        print("\n  " + "-" * 70)
        print(f"  [{i}] up={_upvotes(p)}  com={_ncomments(p)}  submolt=[{_submolt(p)}]")
        print(f"      TITULO: {p.get('title')}")
        print("      BODY:")
        body = (p.get("body") or p.get("content") or "").strip()
        for line in (body.splitlines() or [body]):
            print(f"        {line}")


def main():
    client = MoltbookAPIClient(credentials=Credentials.from_env())
    part1(client)
    part2(client)
    print("\n[recon parte 2 completo — solo lecturas, sin escrituras]")


if __name__ == "__main__":
    main()
