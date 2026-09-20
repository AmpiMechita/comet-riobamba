"""E1+E3: mapa de referentes + relaciones con comet."""
import json, os, sys, re
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.credentials import Credentials
from services.moltbook_api_client import MoltbookAPIClient

client = MoltbookAPIClient(Credentials.from_env())

def _a(p):
    a = p.get("author") or p.get("author_name") or p.get("username")
    if isinstance(a, dict): return a.get("name") or a.get("username") or "?"
    return str(a) if a else "?"

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

# ── 1. TOP 100 all-time del server ──
print("═══ 1. TOP-100 ALL-TIME: AUTORES ═══")
top = client.fetch_posts(limit=100, sort="top") or []
print(f"posts: {len(top)}")
by_auth = defaultdict(list)
for p in top:
    by_auth[_a(p)].append(p)
auth_rank = sorted(by_auth.items(), key=lambda x: -len(x[1]))
print(f"\nAutores en top-100 (por presencia):")
for a, ps in auth_rank[:20]:
    ups = [_up(p) for p in ps]
    print(f"  {len(ps):3d} posts  avg_karma={sum(ups)/len(ups):7.1f}  max={max(ups):5d}  {a}")

# ── 2. TRENDING ──
print("\n═══ 2. TRENDING (24h) ═══")
try:
    r = client._request("GET", "/trending")
    d = r.get("data") or {}
    items = d.get("agents") or d.get("items") or d.get("trending") or []
    print(f"trending items: {len(items)}")
    for it in items[:20]:
        name = it.get("name") or it.get("username") or it.get("handle")
        karma = it.get("karma") or it.get("score")
        badges = it.get("badges") or it.get("achievements") or []
        print(f"  {name:30s} karma={karma}  badges={len(badges) if isinstance(badges,list) else badges}")
except Exception as e:
    print(f"  /trending falló: {e}")

# ── 3. REFERENTES CONOCIDOS: engagement con comet ──
print("\n═══ 3. RELACIONES COMET ↔ REFERENTES ═══")
# Cargar todos los comentarios que alguna vez llegaron a comet
cf = ROOT / "data" / "moltbook_full_archive" / "comments_flat.json"
comments = json.loads(cf.read_text(encoding="utf-8"))
print(f"comentarios totales en archive: {len(comments)}")

# Quién nos comentó
inbound = Counter()
for c in comments:
    a = c.get("author")
    if isinstance(a, dict): a = a.get("name") or a.get("username")
    if a and a != "comet_riobamba":
        inbound[str(a)] += 1

# Comet comentó a quién (buscamos author de comments donde comet es autor)
outbound = Counter()
for c in comments:
    a = c.get("author")
    if isinstance(a, dict): a = a.get("name") or a.get("username")
    if a == "comet_riobamba":
        target = c.get("target_author") or c.get("reply_to_author") or c.get("parent_author")
        if target:
            outbound[str(target)] += 1

# Referentes candidatos = top-100 autores + trending + top-15 inbound
refs = set()
for a, _ in auth_rank[:30]: refs.add(a)
for a, _ in inbound.most_common(15): refs.add(a)
refs -= {"comet_riobamba"}

print(f"\nreferentes a clasificar: {len(refs)}")
print(f"\n{'REFERENTE':<30} {'IN':>6} {'OUT':>6}  {'RELACIÓN':<20}")
print("-" * 70)
rows = []
for r in refs:
    i, o = inbound.get(r,0), outbound.get(r,0)
    rel = "MUTUO" if i>0 and o>0 else ("NOS MIRA" if i>0 else ("LO MIRAMOS" if o>0 else "SIN CONTACTO"))
    rows.append((r, i, o, rel))
rows.sort(key=lambda x: -x[1])
for r, i, o, rel in rows:
    print(f"  {r[:28]:<28} {i:>6} {o:>6}  {rel:<20}")

# ── 4. Resumen por relación ──
print("\n═══ 4. DISTRIBUCIÓN DE RELACIONES ═══")
c = Counter(r[3] for r in rows)
for k, v in c.most_common():
    print(f"  {k:15s}: {v:3d}")

# ── 5. Verificar si Hazel_OC / rossum / bytes interactúan con comet ──
print("\n═══ 5. TOP LÍDERES: ¿nos miran? ═══")
for name in ["Hazel_OC", "rossum", "bytes", "vina", "neo_konsi_s2bw", "lightn"]:
    i = inbound.get(name, 0)
    o = outbound.get(name, 0)
    print(f"  {name:20s}  IN={i:4d}  OUT={o:4d}")
