#!/usr/bin/env python
"""Reconciliacion de karma — SOLO LECTURA (GETs). No escribe nada.

Objetivo: karma actual segun API vs suma de upvotes de posts vs upvotes de
comentarios de Fase B, para ver de donde viene el karma.
"""
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config.credentials import Credentials
from services.moltbook_api_client import MoltbookAPIClient
from services.dedup_store import DedupStore

_COMET = {"comet_riobamba", "cometriobamba", "comet-riobamba", "comet"}
_MAX_COMMENT_POSTS = 80  # tope modesto de GETs de fetch_post_comments


def _upvotes(d):
    for k in ("upvotes", "score", "karma", "upvote_count", "points", "votes", "net_votes"):
        v = d.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return None


def _author_str(d):
    a = d.get("author") or d.get("author_name") or d.get("username") or ""
    if isinstance(a, dict):
        return (a.get("name") or a.get("username") or a.get("id") or "").lower()
    return str(a).lower()


def raw_get(client, path):
    try:
        r = client._request("GET", path)
        return r.get("status"), (r.get("data") or {})
    except Exception as e:
        return None, {"_error": str(e)}


def main():
    client = MoltbookAPIClient(credentials=Credentials.from_env())

    print("=" * 74)
    print("1. KARMA ACTUAL (fresco)")
    print("=" * 74)
    home = client.fetch_home_dashboard()
    print(f"  fetch_home_dashboard() -> karma = {home.get('karma')}")
    print(f"  keys de fetch_home_dashboard(): {sorted(home.keys())}")

    st, raw_home = raw_get(client, "/home")
    print(f"\n  RAW GET /home  (status={st}) — todas las keys crudas:")
    if isinstance(raw_home, dict):
        for k in sorted(raw_home.keys()):
            v = raw_home[k]
            vs = v if not isinstance(v, (list, dict)) else f"<{type(v).__name__} len={len(v)}>"
            print(f"     {k:<28} = {vs}")

    st2, me = raw_get(client, "/agents/me")
    print(f"\n  RAW GET /agents/me  (status={st2}):")
    if isinstance(me, dict):
        # la respuesta puede envolver en 'agent'/'profile'
        prof = me.get("agent") or me.get("profile") or me
        if isinstance(prof, dict):
            for k in sorted(prof.keys()):
                v = prof[k]
                vs = v if not isinstance(v, (list, dict)) else f"<{type(v).__name__} len={len(v)}>"
                print(f"     {k:<28} = {vs}")
        else:
            print(f"     {me}")

    print("\n" + "=" * 74)
    print("2a. UPVOTES DE POSTS PROPIOS (get_post por id)")
    print("=" * 74)
    mine = client.fetch_my_posts(limit=20)
    post_total = 0
    post_n = 0
    for p in mine:
        pid = p.get("id") or p.get("post_id")
        live = client.get_post(pid) if pid else None
        if not live:
            continue
        uv = _upvotes(live) or 0
        post_total += uv
        post_n += 1
        # inspeccionar si el post trae un objeto author con karma total del agente
        au = live.get("author")
        if isinstance(au, dict) and post_n == 1:
            print(f"  [author obj del post: keys={sorted(au.keys())}]")
        print(f"  up={uv:>4} | {(live.get('title') or '')[:64]}")
    print(f"  --> TOTAL upvotes de POSTS: {post_total}  (n={post_n})")

    print("\n" + "=" * 74)
    print("2b. UPVOTES DE COMENTARIOS PROPIOS (Fase B)")
    print("=" * 74)
    store = DedupStore()
    agent_comments = store.get_agent_comment_ids()      # post_id -> [comment_ids]
    commented = store.get_commented_post_ids()          # post_id -> ts
    # union de post_ids: donde hay comment_ids registrados + donde marco commented
    post_ids = list(dict.fromkeys(list(agent_comments.keys()) + list(commented.keys())))
    print(f"  posts con comentario propio registrado (agent_comment): {len(agent_comments)}")
    print(f"  posts marcados commented_post: {len(commented)}")
    print(f"  posts a inspeccionar (union): {len(post_ids)}")
    capped = post_ids[:_MAX_COMMENT_POSTS]
    if len(post_ids) > _MAX_COMMENT_POSTS:
        print(f"  (CAP a {_MAX_COMMENT_POSTS} GETs — quedan {len(post_ids) - _MAX_COMMENT_POSTS} sin inspeccionar)")

    comment_total = 0
    comment_n = 0
    matched_posts = 0
    for pid in capped:
        known_ids = set(agent_comments.get(pid, []) or [])
        comments = client.fetch_post_comments(pid)
        hit = False
        for c in comments:
            cid = c.get("id") or c.get("comment_id")
            is_mine = (cid in known_ids) or (_author_str(c) in _COMET)
            if is_mine:
                uv = _upvotes(c) or 0
                comment_total += uv
                comment_n += 1
                hit = True
        if hit:
            matched_posts += 1
    print(f"  comentarios propios encontrados: {comment_n} (en {matched_posts} posts)")
    print(f"  --> TOTAL upvotes de COMENTARIOS: {comment_total}")

    print("\n" + "=" * 74)
    print("3. RECONCILIACION")
    print("=" * 74)
    api_karma = home.get("karma")
    print(f"  karma segun API (/home):        {api_karma}")
    print(f"  upvotes de POSTS:               {post_total}")
    print(f"  upvotes de COMENTARIOS:         {comment_total}")
    print(f"  suma posts+comentarios:         {post_total + comment_total}")
    print(f"  objetivo mencionado:            ~1850")


if __name__ == "__main__":
    main()
