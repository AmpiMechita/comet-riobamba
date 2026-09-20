"""E2: firma de voz de los 10 referentes top. Read-only."""
import json, sys, re
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config.credentials import Credentials
from services.moltbook_api_client import MoltbookAPIClient

client = MoltbookAPIClient(Credentials.from_env())

TARGETS = ["Hazel_OC","Ronin","clawdbottom","PDMN","JeevisAgent",
           "ultrathink","eudaemon_0","Jackle","Fred","m0ther"]

def _a(p):
    a = p.get("author")
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

def _body(p): return p.get("body") or p.get("content") or ""

top = client.fetch_posts(limit=100, sort="top") or []
by_auth = defaultdict(list)
for p in top:
    by_auth[_a(p)].append(p)

print("═" * 90)
print("FIRMA DE VOZ — 10 REFERENTES TOP")
print("═" * 90)

# regexes
RX_I     = re.compile(r"\b(I|my|me|myself)\b", re.I)
RX_YOU   = re.compile(r"\b(you|your|yours)\b", re.I)
RX_WE    = re.compile(r"\b(we|our|us)\b", re.I)
RX_HDR   = re.compile(r"^#{1,4}\s", re.M)
RX_BOLD  = re.compile(r"\*\*[^*]+\*\*")
RX_BULL  = re.compile(r"^\s*[-*]\s", re.M)
RX_NUM   = re.compile(r"^\s*\d+\.\s", re.M)
RX_TIME  = re.compile(r"\b(last|this|two|three|four|five|six)\s+(week|month|day|Tuesday|Monday|Sunday|year)", re.I)
RX_NUMB  = re.compile(r"\b\d+\b")
RX_MES   = re.compile(r"\b(measured|observed|in production|we found|we saw)\b", re.I)

def first_sent(s):
    s = (s or "").strip().replace("\n"," ")
    m = re.split(r"(?<=[.!?])\s+", s)
    return (m[0] if m else s)[:110]

# table
print(f"\n{'AUTOR':<16} {'n':>3} {'words':>6} {'karma':>7} {'I/100w':>7} {'you/100w':>9} {'we/100w':>8} {'HDR%':>5} {'BOLD%':>6} {'BULL%':>6} {'TIME%':>6} {'NUM%':>5} {'MES%':>5}")
print("-" * 110)

summaries = {}
for t in TARGETS:
    ps = by_auth.get(t, [])
    if not ps:
        print(f"{t:<16} NOT IN TOP-100")
        continue
    n = len(ps)
    ws = [len(_body(p).split()) for p in ps]
    ks = [_up(p) for p in ps]
    def rate(rx):
        return sum(1 for p in ps if rx.search(_body(p))) / n * 100
    def per100w(rx):
        total_w = sum(ws) or 1
        total_m = sum(len(rx.findall(_body(p))) for p in ps)
        return total_m / total_w * 100
    i100, y100, w100 = per100w(RX_I), per100w(RX_YOU), per100w(RX_WE)
    hdr, bold, bull, time_, num_, mes = rate(RX_HDR), rate(RX_BOLD), rate(RX_BULL), rate(RX_TIME), rate(RX_NUMB), rate(RX_MES)
    print(f"{t:<16} {n:>3} {sum(ws)/n:>6.0f} {sum(ks)/n:>7.0f} {i100:>7.2f} {y100:>9.2f} {w100:>8.2f} {hdr:>5.0f} {bold:>6.0f} {bull:>6.0f} {time_:>6.0f} {num_:>5.0f} {mes:>5.0f}")
    summaries[t] = {"n":n,"posts":ps}

# Openers: primera frase de cada post, agrupadas por autor
print("\n" + "═" * 90)
print("OPENERS — primera frase (máx 3 por autor, top-karma)")
print("═" * 90)
for t in TARGETS:
    if t not in summaries: continue
    ps = sorted(summaries[t]["posts"], key=lambda p: -_up(p))[:3]
    print(f"\n### {t} (n={summaries[t]['n']}) ###")
    for p in ps:
        print(f"  [{_up(p):>5}] {first_sent(_body(p))}")

# Primer párrafo completo de top-1 de cada autor
print("\n" + "═" * 90)
print("PRIMER PÁRRAFO COMPLETO — top-1 de cada autor")
print("═" * 90)
for t in TARGETS:
    if t not in summaries: continue
    p = max(summaries[t]["posts"], key=lambda x: _up(x))
    body = _body(p).strip()
    first_para = body.split("\n\n")[0] if "\n\n" in body else body[:500]
    print(f"\n### {t}  | karma={_up(p)} cc={_cc(p)} ###")
    print(f"TÍTULO: {p.get('title')}")
    print(first_para[:600])
