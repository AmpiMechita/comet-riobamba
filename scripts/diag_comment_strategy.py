"""Diagnóstico del comment section — viabilidad de la estrategia."""
import json, sys
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
POSTS = ROOT / "data" / "moltbook_full_archive" / "posts"

posts = []
for f in POSTS.glob("*.json"):
    try: posts.append(json.loads(f.read_text(encoding="utf-8")))
    except: pass

def _a(p):
    a = p.get("author")
    if isinstance(a, dict): return a.get("name") or a.get("username") or "?"
    return str(a)

def _up(p):
    for k in ("upvotes","score","karma","upvote_count","points","votes"):
        v = p.get(k)
        if isinstance(v,(int,float)): return int(v)
    return 0

# ── 1. Schema de un comentario ──
print("═══ 1. SCHEMA DE COMENTARIO ═══")
any_post = next((p for p in posts if p.get("_all_comments")), None)
if any_post:
    c = any_post["_all_comments"][0]
    print("keys:", list(c.keys()))
    print("sample:")
    for k, v in c.items():
        s = repr(v)
        print(f"  {k}: {s[:120]}")

# ── 2. Top-3 posts globales: análisis del comment section ──
print("\n═══ 2. COMMENT SECTION — TOP 3 GLOBALES ═══")
ranked = sorted(posts, key=lambda p: -_up(p))[:3]
for p in ranked:
    cs = p.get("_all_comments") or []
    print(f"\n### {_a(p)} | karma={_up(p)} | captured={len(cs)} ###")
    print(f"  título: {(p.get('title') or '')[:90]}")
    print(f"  post.created_at: {p.get('created_at')}")
    # primeros 5 comentarios (asumiendo orden cronológico ascendente)
    print(f"  primeros 5 comments:")
    for c in cs[:5]:
        ca = c.get("author")
        if isinstance(ca, dict): ca = ca.get("name") or ca.get("username")
        ts = c.get("created_at") or c.get("createdAt") or "?"
        txt = (c.get("content") or "").replace("\n"," ")[:140]
        print(f"    [{str(ts)[:19]}] {str(ca)[:18]:<18} {txt}")
    # últimos 3 comentarios (para ver horizonte temporal)
    print(f"  últimos 3 comments:")
    for c in cs[-3:]:
        ca = c.get("author")
        if isinstance(ca, dict): ca = ca.get("name") or ca.get("username")
        ts = c.get("created_at") or c.get("createdAt") or "?"
        txt = (c.get("content") or "").replace("\n"," ")[:140]
        print(f"    [{str(ts)[:19]}] {str(ca)[:18]:<18} {txt}")

# ── 3. ¿Algún comment tiene más engagement que otros? ──
print("\n═══ 3. ¿VOTES EN COMENTARIOS? ═══")
if any_post and any_post.get("_all_comments"):
    c = any_post["_all_comments"][0]
    vote_keys = [k for k in c.keys() if any(w in k.lower() for w in ["vote","score","like","upvote","karma","reaction"])]
    print(f"  campos tipo vote: {vote_keys if vote_keys else '(ninguno)'}")

# ── 4. Autores recurrentes en comments de TOP posts ═─
print("\n═══ 4. AUTORES FRECUENTES EN COMMENTS DE TOP POSTS ═══")
auth_counter = Counter()
for p in ranked[:5]:
    for c in p.get("_all_comments") or []:
        a = c.get("author")
        if isinstance(a, dict): a = a.get("name") or a.get("username")
        auth_counter[str(a)] += 1
print("top 20 autores en comments de posts top:")
for a, n in auth_counter.most_common(20):
    print(f"  {n:5d}  {a}")

# ── 5. ¿Hazel/Ronin/eudaemon comentan en posts ajenos? ═─
print("\n═══ 5. ¿TOP AGENTS COMENTAN EN POSTS AJENOS? ═══")
for target in ["Hazel_OC","Ronin","eudaemon_0","clawdbottom","PDMN","Jackle","Fred"]:
    hits = []
    for p in posts:
        if _a(p) == target: continue
        for c in p.get("_all_comments") or []:
            a = c.get("author")
            if isinstance(a, dict): a = a.get("name") or a.get("username")
            if str(a) == target:
                hits.append((p.get("title","")[:60], (c.get("content") or "")[:100]))
                break
    print(f"  {target:14s}: comentó en {len(hits)} de los 311 posts del archive")
    for t, c in hits[:2]:
        print(f"     -> {t}")
        print(f"        comentario: {c}")

# ── 6. Timestamp distribution — ¿cuándo comentan? ═─
print("\n═══ 6. FRECUENCIA DE PUBLICACIÓN DE TOP AGENTS ═══")
by_month = {}
for p in posts:
    a = _a(p)
    if a in ["Hazel_OC","Ronin","eudaemon_0","clawdbottom","ultrathink"]:
        d = (p.get("created_at") or "")[:7]
        by_month.setdefault(a, Counter())[d] += 1
for a, months in by_month.items():
    print(f"  {a:14s}: {dict(months)}")
