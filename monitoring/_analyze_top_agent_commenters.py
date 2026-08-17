# -*- coding: utf-8 -*-
"""Analisis read-only: quien comenta en los posts de los agentes top (watchlist).

Preguntas que responde:
  1. Cuantos y cuales agentes comentan en los posts de los agentes top (ej. vina).
  2. Son recurrentes (comentan en varios posts / varias veces)?
  3. Que temas responden y que calidad tienen esas respuestas (dual_score,
     longitud, preguntas, overlap tematico con el post)?
  4. Son acordes a los temas principales del post?
  5. Suman karma esas interacciones? (karma propio via /home + ledger de votos)

Uso:  python -m monitoring._analyze_top_agent_commenters [--author vina] [--max-posts 6]
Solo hace lecturas (GET). NO escribe en la plataforma.
--weekly: ademas escribe data/top_agent_commenters_weekly.json para la seccion
          semanal del daily report (scripts/print_daily_report.py).
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.moltbook_api_client import MoltbookAPIClient
from services.dual_scoring import compute_dual_score

TOP_TERMS = re.compile(r"\b[a-z][a-z-]{2,}\b", re.IGNORECASE)
STOP = {
    "the", "and", "for", "are", "but", "was", "not", "you", "all", "any",
    "can", "had", "her", "was", "one", "our", "out", "day", "did", "get",
    "has", "him", "how", "its", "let", "may", "new", "now", "old", "see",
    "two", "way", "who", "why", "yet", "she", "his", "they", "this", "that",
    "with", "from", "have", "been", "will", "would", "could", "should",
    "their", "there", "about", "which", "what", "when", "where", "than",
    "into", "them", "then", "these", "those", "also", "just", "like", "more",
    "most", "some", "such", "only", "other", "over", "own", "same", "very",
    "even", "still", "while", "because", "before", "after", "being", "made",
    "make", "does", "done", "down", "here", "back", "ever", "every", "many",
    "much", "must", "need", "never", "once", "really", "right", "should",
    "thing", "think", "though", "through", "under", "upon", "well",
}


def topic_tokens(text: str, limit: int = 12) -> Counter:
    tokens = re.findall(TOP_TERMS, (text or "").lower())
    return Counter(t for t in tokens if t not in STOP and len(t) > 2)


def overlap_ratio(comment: str, post_text: str) -> float:
    c = topic_tokens(comment)
    p = topic_tokens(post_text)
    if not c:
        return 0.0
    hits = sum(v for t, v in c.items() if t in p)
    return round(hits / sum(c.values()), 2)


def author_name(c: dict) -> str:
    a = c.get("author") or ""
    if isinstance(a, dict):
        return str(a.get("name") or a.get("username") or "")
    return str(a)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--author", default="", help="Autor top a analizar (ej. vina)")
    ap.add_argument("--max-posts", type=int, default=6)
    ap.add_argument("--max-authors", type=int, default=12)
    ap.add_argument("--weekly", action="store_true",
                    help="Escribe snapshot en data/top_agent_commenters_weekly.json")
    args = ap.parse_args()

    client = MoltbookAPIClient()

    print("=" * 100)
    print("ANALISIS: agentes que comentan en posts de agentes top (read-only)")
    print("=" * 100)

    # ── 0. Karma propio actual (para la pregunta 5) ──
    home = client.fetch_home_dashboard()
    karma_now = home.get("karma", 0)
    print(f"[karma propio] actual={karma_now} unread={home.get('unread_notifications')}")

    # ── 1. Feed amplio: hot + new ──
    posts_by_author: dict = defaultdict(list)
    for sort in ("hot", "new"):
        for post in client.fetch_posts(limit=100, sort=sort) or []:
            a = author_name(post).strip()
            pid = post.get("id")
            if a and pid:
                posts_by_author[a].append(post)

    # ── 2. Ranking de autores por presencia en el feed ──
    author_stats = []
    for a, posts in posts_by_author.items():
        uniq = {(p.get("id")) for p in posts}
        total_up = sum(int(p.get("upvotes") or 0) for p in posts)
        author_stats.append((len(uniq), total_up, a))
    author_stats.sort(reverse=True)

    target = args.author.strip().lower()
    if target:
        selected = [a for _, _, a in author_stats if a.lower() == target]
        selected = selected or [target]
    else:
        selected = [a for _, _, a in author_stats[: args.max_authors]]
        # garantizar vina/neo_konsi_s2bw si estan en el feed
        for cand in ("vina", "neo_konsi_s2bw", "diviner", "lightningzero", "bytes"):
            if cand in posts_by_author and cand not in selected:
                selected.append(cand)

    print(f"\nFeed muestreado: {sum(len(v) for v in posts_by_author.values())} posts, "
          f"{len(posts_by_author)} autores unicos")
    print(f"Top autores en feed (posts, upvotes): "
          f"{[(a, n, u) for n, u, a in author_stats[:8]]}")

    # ── 3. Por cada autor top: posts + comentarios ──
    grand = defaultdict(lambda: {
        "comments": 0, "votes": 0, "lengths": [], "questions": 0,
        "overlaps": [], "scores": [], "posts": set(), "samples": [],
    })
    for target_author in selected:
        posts = posts_by_author.get(target_author, []) or []
        if not posts:
            print(f"\n  [warn] '{target_author}' no aparecio en el feed muestreado.")
            continue
        uniq_posts = {p.get("id"): p for p in posts}
        sel = list(uniq_posts.values())[: args.max_posts]
        print(f"\n{'─' * 20} AUTOR: {target_author} ({len(uniq_posts)} posts vistos)")
        for post in sel:
            pid = post.get("id")
            title = (post.get("title") or "")[:70]
            post_text = " ".join([str(post.get("title") or ""),
                                  str(post.get("content") or post.get("body") or "")])
            comments = []
            for page in range(3):
                batch = client.fetch_post_comments(pid, offset=page * 50) or []
                comments.extend(batch)
                if len(batch) < 50:
                    break
            print(f"  post {pid} | {title} | comentarios={len(comments)} "
                  f"| up={post.get('upvotes')}")

            for c in comments:
                a = author_name(c).strip()
                text = c.get("content") or c.get("text") or ""
                if not a or not text:
                    continue
                key = a.lower()
                g = grand[key]
                g["comments"] += 1
                g["votes"] += int(c.get("upvotes") or 0)
                g["lengths"].append(len(text))
                g["posts"].add(pid)
                if "?" in text:
                    g["questions"] += 1
                g["overlaps"].append(overlap_ratio(text, post_text))
                try:
                    g["scores"].append(compute_dual_score(text)["research_value_score"])
                except Exception:
                    pass
                if len(g["samples"]) < 2 and text not in g["samples"]:
                    g["samples"].append(text[:150])

    # ── 4. Reporte por comentarista ──
    print("\n" + "=" * 100)
    print("QUIEN COMENTA EN POSTS DE AGENTES TOP (agrupado)")
    print("=" * 100)
    ranked = sorted(grand.items(), key=lambda kv: kv[1]["comments"], reverse=True)
    for key, g in ranked:
        if g["comments"] == 0:
            continue
        avg_len = round(sum(g["lengths"]) / len(g["lengths"])) if g["lengths"] else 0
        avg_ov = round(sum(g["overlaps"]) / len(g["overlaps"]), 2) if g["overlaps"] else 0
        avg_sc = round(sum(g["scores"]) / len(g["scores"]), 2) if g["scores"] else 0
        print(f"  [{key}] comentarios={g['comments']} en {len(g['posts'])} posts distintos "
              f"| preguntas={g['questions']} | avg_len={avg_len} | overlap_tema={avg_ov} "
              f"| valor_dual_avg={avg_sc} | recurrente={'SI' if len(g['posts']) >= 2 else 'no'}")
        for s in g["samples"]:
            print(f"      ej: {s!r}")

    # ── 5. Karma: correlacion (observacional) ──
    print("\n" + "=" * 100)
    print("KARMA (pregunta 5)")
    print("=" * 100)
    votes_path = Path("data/comment_votes.jsonl")
    total_up = 0
    n_checked = 0
    if votes_path.exists():
        for line in votes_path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("upvotes") is not None:
                n_checked += 1
                total_up += int(rec["upvotes"])
    print(f"  karma actual en /home: {karma_now}")
    print(f"  ledger comment_votes: {n_checked} comentarios propios chequeados con "
          f"{total_up} upvotes totales")
    import subprocess
    log = Path("logs/agent.log")
    if log.exists():
        out = subprocess.run(
            ["Select-String" if False else "rg", "-o", "karma=\\d+", str(log)],
            capture_output=True, text=True,
        )
        vals = re.findall(r"karma=(\d+)", out.stdout or "")
        if vals:
            print(f"  historial karma en agent.log: min={min(map(int, vals))} "
                  f"max={max(map(int, vals))} (muestra de {len(vals)} lecturas)")

    # ── 6. Snapshot semanal (para el daily report) ──
    if args.weekly:
        snapshot = {
            "date": datetime.now(timezone.utc).date().isoformat(),
            "karma": karma_now,
            "unread_notifications": home.get("unread_notifications", 0),
            "comment_votes_checked": n_checked,
            "comment_votes_upvotes": total_up,
            "top_commenters": [
                {
                    "author": key,
                    "comments": g["comments"],
                    "posts": len(g["posts"]),
                    "questions": g["questions"],
                    "avg_overlap": (round(sum(g["overlaps"]) / len(g["overlaps"]), 2)
                                    if g["overlaps"] else 0.0),
                    "avg_dual_score": (round(sum(g["scores"]) / len(g["scores"]), 2)
                                       if g["scores"] else 0.0),
                }
                for key, g in ranked[: args.max_authors * 2]
            ],
        }
        snap_path = Path("data/top_agent_commenters_weekly.json")
        snap_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"\n[weekly] snapshot escrito en {snap_path}")


if __name__ == "__main__":
    main()