#!/usr/bin/env python
"""Rendimiento REAL de los 6 posts con la voz nueva. SOLO LECTURA (GETs)."""
import os
import sys
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config.credentials import Credentials
from services.moltbook_api_client import MoltbookAPIClient

POST_IDS = ["6828dc95", "b8045e16", "03e333a8", "61f58923", "2549ad5b", "9318556e"]
BASELINE_AVG = 3.5


def _up(d):
    for k in ("upvotes", "score", "upvote_count", "points"):
        v = d.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def _com(d):
    for k in ("comment_count", "comments_count", "num_comments"):
        v = d.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    c = d.get("comments")
    return len(c) if isinstance(c, list) else 0


def _created(d):
    return d.get("created_at") or d.get("createdAt") or ""


def _hours_since(iso):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return None


def raw_get(client, path):
    try:
        r = client._request("GET", path)
        return r.get("status"), (r.get("data") or {})
    except Exception as e:
        return None, {"_error": str(e)}


def _resolve_full_id(client, short):
    """Los ids del usuario son prefijos de 8 chars. get_post necesita el id
    completo; lo intentamos directo y, si 404, lo buscamos en los posts propios."""
    p = client.get_post(short)
    if p:
        return short, p
    return short, None


def main():
    client = MoltbookAPIClient(credentials=Credentials.from_env())

    print("=" * 78)
    print("1. KARMA ACTUAL (via /agents/me)")
    print("=" * 78)
    st, me = raw_get(client, "/agents/me")
    prof = me.get("agent") or me.get("profile") or me
    karma = prof.get("karma") if isinstance(prof, dict) else None
    print(f"  karma AHORA:      {karma}")
    print(f"  karma anterior:   1857")
    if isinstance(karma, (int, float)):
        print(f"  delta:            {karma - 1857:+d}")
    print(f"  posts_count:      {prof.get('posts_count')}")
    print(f"  follower_count:   {prof.get('follower_count')}")

    # Resolver ids completos desde los posts propios del server (prefijos de 8)
    print("\n  (resolviendo ids completos desde /agents/me/posts...)")
    owned = {}
    st, data = raw_get(client, "/agents/me/posts")
    cursor = data.get("next_cursor") if isinstance(data, dict) else None
    for p in (data.get("posts") or []):
        pid = p.get("id") or ""
        owned[pid] = p
    it = 0
    while cursor and it < 8:
        it += 1
        try:
            r = client._request("GET", "/agents/me/posts", params={"limit": 100, "cursor": cursor})
            d = r.get("data") or {}
        except Exception:
            break
        for p in (d.get("posts") or []):
            owned[p.get("id") or ""] = p
        cursor = d.get("next_cursor")

    print("\n" + "=" * 78)
    print("2-4. LOS 6 POSTS DE LA VOZ NUEVA")
    print("=" * 78)
    rows = []
    for short in POST_IDS:
        full = next((pid for pid in owned if pid.startswith(short)), None)
        post = owned.get(full) if full else None
        if not post:
            # fallback: intento get_post con el prefijo por si el server lo acepta
            post = client.get_post(short)
            full = (post or {}).get("id", short)
        if not post:
            rows.append((short, None, None, None, "NO ENCONTRADO"))
            continue
        rows.append((full or short, _up(post), _com(post), _hours_since(_created(post)), post.get("title") or ""))

    rows.sort(key=lambda r: (r[1] if r[1] is not None else -1), reverse=True)

    print(f"  {'ID':<10} {'UP':>4} {'COM':>4} {'HORAS':>7}  TITULO")
    print("  " + "-" * 92)
    ups = []
    for pid, up, com, hrs, title in rows:
        if up is not None:
            ups.append(up)
        up_s = str(up) if up is not None else "n/a"
        com_s = str(com) if com is not None else "n/a"
        hrs_s = f"{hrs:.1f}h" if hrs is not None else "n/a"
        print(f"  {str(pid)[:10]:<10} {up_s:>4} {com_s:>4} {hrs_s:>7}  {str(title)[:70]}")

    print("\n" + "=" * 78)
    print("3. PROMEDIO — VOZ NUEVA vs BASELINE HISTORICO")
    print("=" * 78)
    if ups:
        avg = sum(ups) / len(ups)
        print(f"  avg upvotes voz nueva (n={len(ups)}): {avg:.2f}")
        print(f"  baseline historico (~karma/post):    {BASELINE_AVG}")
        print(f"  diferencia:                          {avg - BASELINE_AVG:+.2f}")
    else:
        print("  sin datos de upvotes")
    print("\n  NOTA: los upvotes dependen del tiempo vivo — ver columna HORAS. Los mas")
    print("  recientes tuvieron menos ventana para acumular; comparacion es preliminar.")


if __name__ == "__main__":
    main()
