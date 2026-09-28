# scripts/_p122_probe_cursor.py -- SOLO LECTURA, evidencia diseno P-122
# NO BORRAR hasta que P-122 cierre (regla 45 + leccion H7 auditoria).
import os, sys, json
from datetime import datetime, timezone
_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _R not in sys.path: sys.path.insert(0, _R)
from config.credentials import Credentials
from services.moltbook_api_client import MoltbookAPIClient
def main():
    pid = sys.argv[1] if len(sys.argv) > 1 else "19b6e9bf"
    c = MoltbookAPIClient(credentials=Credentials.from_env())
    p = "/posts/" + pid + "/comments"
    log = []
    def out(s=""): print(s); log.append(s)
    out("# P-122 probe " + datetime.now(timezone.utc).isoformat() + " post=" + pid)
    r = c._request("GET", p, params={"limit": 50})
    d = r.get("data") or {}
    out("status=" + str(r["status"]) + " data_type=" + type(d).__name__)
    out("data_keys=" + str(sorted(d.keys()) if isinstance(d, dict) else "n/a"))
    for k in ("has_more","next_cursor","cursor","meta","pagination"):
        if isinstance(d, dict) and k in d:
            out("data[" + k + "]=" + json.dumps(d[k], ensure_ascii=False, default=str)[:300])
    items = (d.get("comments") if isinstance(d, dict) else d) or []
    out("items_p1=" + str(len(items)))
    if items and isinstance(items[0], dict): out("item0_keys=" + str(sorted(items[0].keys())))
    cur = d.get("next_cursor") if isinstance(d, dict) else None
    if not cur: out("NO next_cursor -> fin"); return
    ids1 = {i.get("id") for i in items if isinstance(i, dict)}
    for param in ("cursor","after","next_cursor","starting_after"):
        r2 = c._request("GET", p, params={"limit": 50, param: cur})
        d2 = r2.get("data") or {}
        it2 = (d2.get("comments") if isinstance(d2, dict) else d2) or []
        new = {i.get("id") for i in it2 if isinstance(i, dict)} - ids1
        out("param=" + param + " status=" + str(r2["status"]) + " n=" + str(len(it2)) + " new=" + str(len(new)))
        if new: out("CONFIRMADO " + param); break
    r3 = c._request("GET", p, params={"limit": 50, "offset": 50})
    d3 = r3.get("data") or {}
    it3 = (d3.get("comments") if isinstance(d3, dict) else d3) or []
    ids3 = {i.get("id") for i in it3 if isinstance(i, dict)}
    out("offset=50 status=" + str(r3["status"]) + " n=" + str(len(it3)) + " overlap=" + str(len(ids3 & ids1)))
    ev = os.path.join(_R, "docs", "evidence")
    os.makedirs(ev, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fp = os.path.join(ev, "P122_probe_" + ts + ".txt")
    with open(fp, "w", encoding="utf-8", newline="\n") as f: f.write("\n".join(log) + "\n")
    out("evidencia=" + fp)
if __name__ == "__main__": main()
