"""Cuantificar la población silenciosa: karma vs comentaristas únicos."""
import json
from pathlib import Path
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

def _cc(p):
    for k in ("comment_count","comments_count","num_comments"):
        v = p.get(k)
        if isinstance(v,(int,float)): return int(v)
    return 0

# ── 1. Distribución de karma (bimodalidad) ──
print("═══ 1. DISTRIBUCIÓN KARMA ═══")
ks = sorted([_up(p) for p in posts])
n = len(ks)
print(f"n={n} min={ks[0]} p25={ks[n//4]} med={ks[n//2]} p75={ks[3*n//4]} p90={ks[9*n//10]} p99={ks[99*n//100]} max={ks[-1]}")
buckets = Counter()
for k in ks:
    if k == 0: buckets["0"] += 1
    elif k < 5: buckets["1-4"] += 1
    elif k < 20: buckets["5-19"] += 1
    elif k < 50: buckets["20-49"] += 1
    elif k < 200: buckets["50-199"] += 1
    else: buckets["200+"] += 1
for k in ["0","1-4","5-19","20-49","50-199","200+"]:
    print(f"  {k:8s}: {buckets[k]:4d} ({100*buckets[k]/n:5.1f}%)")

# ── 2. Ratio karma / (comentaristas únicos) por tier ──
print("\n═══ 2. KARMA POR COMENTARISTA ÚNICO ═══")
# Para cada post: karma, cc total, comentaristas únicos (excluye comet)
rows = []
for p in posts:
    k = _up(p)
    cs = p.get("_all_comments") or []
    if not cs: continue
    uniq = set()
    self_ct = 0
    for c in cs:
        a = c.get("author")
        if isinstance(a, dict): a = a.get("name") or a.get("username")
        a = str(a)
        if "comet" in a.lower(): self_ct += 1
        else: uniq.add(a)
    n_uniq = len(uniq)
    if n_uniq > 0:
        rows.append((k, len(cs), n_uniq, self_ct, k / n_uniq))

rows.sort(key=lambda r: -r[0])
print(f"\n{'KARMA':>6} {'CC_tot':>7} {'CC_uniq':>8} {'CC_self':>8} {'k/uniq':>8}  TITULO")
for k, cc, n_uniq, self_ct, ratio in rows[:20]:
    p = next((x for x in posts if _up(x)==k and len(x.get("_all_comments") or [])==cc), None)
    title = (p.get("title") if p else "")[:55]
    print(f"{k:>6} {cc:>7} {n_uniq:>8} {self_ct:>8} {ratio:>8.2f}  {title}")

# ── 3. ¿Existen posts con karma alto y cc bajo? (población silenciosa pura) ──
print("\n═══ 3. POSTS CON KARMA ALTO Y CC BAJO (silent-heavy) ═══")
silent_heavy = [r for r in rows if r[0] >= 20 and r[1] <= 10]
print(f"n: {len(silent_heavy)}")
for k, cc, n_uniq, self_ct, ratio in silent_heavy[:15]:
    print(f"  karma={k:4d} cc_total={cc:3d} uniq={n_uniq:3d} ratio={ratio:6.2f}")

# ── 4. ¿Existen posts con cc alto y karma bajo? (commenter-heavy sin reach) ──
print("\n═══ 4. POSTS CON CC ALTO Y KARMA BAJO (viral sin karma) ═══")
commenter_heavy = [r for r in rows if r[1] >= 30 and r[0] <= 5]
print(f"n: {len(commenter_heavy)}")
for k, cc, n_uniq, self_ct, ratio in commenter_heavy[:10]:
    print(f"  karma={k:4d} cc_total={cc:3d} uniq={n_uniq:3d} ratio={ratio:6.2f}")

# ── 5. Correlación karma ↔ (cc_uniq) vs karma ↔ (cc_total) ──
print("\n═══ 5. CORRELACIONES ═══")
def pearson(a, b):
    n = len(a); ma = sum(a)/n; mb = sum(b)/n
    num = sum((x-ma)*(y-mb) for x,y in zip(a,b))
    da = (sum((x-ma)**2 for x in a))**0.5
    db = (sum((y-mb)**2 for y in b))**0.5
    return num/(da*db) if da*db else 0

ka = [r[0] for r in rows]
cc_tot = [r[1] for r in rows]
cc_uniq = [r[2] for r in rows]
print(f"  karma ↔ cc_total : r={pearson(ka, cc_tot):.3f}")
print(f"  karma ↔ cc_uniq  : r={pearson(ka, cc_uniq):.3f}")
print(f"  cc_tot ↔ cc_uniq : r={pearson(cc_tot, cc_uniq):.3f}")
