# recon P-125 — SOLO LECTURA. Mide por post cuantos items (y cuantos NUESTROS)
# quedan solo en pagina 2+, para justificar paginate=True por caller.
import os, sys, json, sqlite3
_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _R not in sys.path: sys.path.insert(0, _R)
from config.credentials import Credentials
from services.moltbook_api_client import MoltbookAPIClient
api = MoltbookAPIClient(credentials=Credentials.from_env())
conn = sqlite3.connect("data/comet_dedup.db")
rows = conn.execute("SELECT key,value FROM dedup_store WHERE namespace='agent_comment'").fetchall()
d = sorted(((k, json.loads(v or "[]")) for k,v in rows), key=lambda x:-len(x[1]))[:3]
for pid, ours in d:
    oset = set(map(str, ours))
    p1 = api.fetch_post_comments(pid, paginate=False)
    pa = api.fetch_post_comments(pid, paginate=True, max_pages=12)
    i1 = {str(x.get("id")) for x in p1 if isinstance(x, dict)}
    ia = {str(x.get("id")) for x in pa if isinstance(x, dict)}
    print(f"{pid[:8]}  ours={len(oset):3d}  p1={len(i1):4d}  all={len(ia):4d}  onlyP2={len(ia-i1):4d}  ourP1={len(oset&i1):3d}  ourAll={len(oset&ia):3d}  MISSING_OURS={len(oset&ia)-len(oset&i1):3d}")
