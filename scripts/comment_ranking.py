"""Ver el ranking real de comentarios: qué comentarios ganan."""
import json
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
POSTS = ROOT / "data" / "moltbook_full_archive" / "posts"

posts = []
for f in POSTS.glob("*.json"):
    try: posts.append(json.loads(f.read_text(encoding="utf-8")))
    except: pass

# ── 1. Score distribution global de comentarios ──
print("═══ 1. SCORE DISTRIBUTION DE COMENTARIOS ═══")
all_scores = []
for p in posts:
    for c in p.get("_all_comments") or []:
        s = c.get("score")
        if isinstance(s, (int, float)):
            all_scores.append(s)
all_scores.sort()
if all_scores:
    n = len(all_scores)
    print(f"n={n} min={all_scores[0]} p25={all_scores[n//4]} med={all_scores[n//2]} p75={all_scores[3*n//4]} p90={all_scores[9*n//10]} p99={all_scores[99*n//100]} max={all_scores[-1]}")
    by_bucket = Counter()
    for s in all_scores:
        if s <= 0: by_bucket["<=0"] += 1
        elif s < 5: by_bucket["1-4"] += 1
        elif s < 20: by_bucket["5-19"] += 1
        elif s < 100: by_bucket["20-99"] += 1
        else: by_bucket["100+"] += 1
    for k in ["<=0","1-4","5-19","20-99","100+"]:
        print(f"  {k:6s}: {by_bucket[k]:5d} ({100*by_bucket[k]/n:.1f}%)")

# ── 2. Top comentarios por score global ──
print("\n═══ 2. TOP 15 COMENTARIOS POR SCORE ═══")
all_comments = []
for p in posts:
    for c in p.get("_all_comments") or []:
        if isinstance(c.get("score"), (int, float)):
            all_comments.append({
                "score": c["score"],
                "author": c.get("author"),
                "text": (c.get("content") or "")[:180],
                "post_title": (p.get("title") or "")[:60],
                "post_author": (p.get("author") or {}).get("name") if isinstance(p.get("author"), dict) else "?",
                "depth": c.get("depth"),
            })
all_comments.sort(key=lambda x: -x["score"])
for c in all_comments[:15]:
    print(f"\n  score={c['score']:>4} depth={c['depth']} by {c['author']}  (post: {c['post_author']})")
    print(f"    {c['text']}")

# ── 3. ¿Qué comentarios de comet tienen score alto? ──
print("\n═══ 3. COMENTARIOS DE comet_riobamba CON SCORE ALTO ═══")
comet_comments = [c for c in all_comments if "comet" in str(c.get("author","")).lower()]
print(f"total comentarios de comet en archive: {len(comet_comments)}")
comet_comments.sort(key=lambda x: -x["score"])
for c in comet_comments[:10]:
    print(f"\n  score={c['score']:>4} depth={c['depth']}  en post de {c['post_author']}")
    print(f"    {c['text']}")

# ── 4. Firma de los comentarios ganadores (>20 score) ──
print("\n═══ 4. FIRMA DE COMENTARIOS GANADORES (score >= 20) ═══")
import re
winners = [c for c in all_comments if c["score"] >= 20]
print(f"n ganadores: {len(winners)}")
if winners:
    I_ct = sum(1 for c in winners if re.search(r'\b(I|my|me)\b', c["text"], re.I))
    you_ct = sum(1 for c in winners if re.search(r'\b(you|your)\b', c["text"], re.I))
    q_ct = sum(1 for c in winners if '?' in c["text"])
    num_ct = sum(1 for c in winners if re.search(r'\d', c["text"]))
    print(f"  con I/my:    {I_ct}/{len(winners)} ({100*I_ct/len(winners):.0f}%)")
    print(f"  con you/your:{you_ct}/{len(winners)} ({100*you_ct/len(winners):.0f}%)")
    print(f"  con '?':     {q_ct}/{len(winners)} ({100*q_ct/len(winners):.0f}%)")
    print(f"  con dígitos: {num_ct}/{len(winners)} ({100*num_ct/len(winners):.0f}%)")
    avg_len = sum(len(c["text"]) for c in winners) / len(winners)
    print(f"  largo promedio (chars): {avg_len:.0f}")

# ── 5. ¿Existen comentarios con reply_count alto? ──
print("\n═══ 5. TOP COMENTARIOS POR REPLY_COUNT ═══")
all_with_rc = []
for p in posts:
    for c in p.get("_all_comments") or []:
        rc = c.get("reply_count")
        if isinstance(rc, (int, float)) and rc > 0:
            all_with_rc.append({
                "rc": rc,
                "author": c.get("author"),
                "text": (c.get("content") or "")[:150],
                "score": c.get("score"),
            })
all_with_rc.sort(key=lambda x: -x["rc"])
for c in all_with_rc[:10]:
    print(f"\n  replies={c['rc']:>3} score={c['score']:>4} by {c['author']}")
    print(f"    {c['text']}")
