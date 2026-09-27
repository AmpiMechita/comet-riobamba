#!/usr/bin/env python3
"""
Energy Intelligence Node  ─  Single-file data ingestion + REST API
===================================================================
Rastrea claims físicos de tecnologías de energía renovable de nueva generación.

Fuentes:  ArXiv (papers) · USPTO PatentsView (patentes) · Climate Tech PR
Storage:  SQLite
API:      FastAPI

Uso:
    pip install fastapi uvicorn requests beautifulsoup4 lxml
    python energy_intel_node.py              # crea DB + lanza API en :8000
    python energy_intel_node.py --scrape     # modo CLI: solo ingesta, sin API

Arquitectura (todo en este archivo, < 500 líneas):
    ┌─────────────┐   ┌──────────────┐   ┌──────────────────┐
    │  ArXiv API  │   │ USPTO PV API │   │  Climate Tech PR │
    └──────┬──────┘   └──────┬───────┘   └────────┬─────────┘
           │                 │                     │
           └──────────┬──────┴─────────────────────┘
                      ▼
              ┌───────────────┐
              │  IngestPipeline│  ← dedup + normaliza
              └───────┬───────┘
                      ▼
              ┌───────────────┐
              │   SQLite DB   │  tabla: claims
              └───────┬───────┘
                      ▼
              ┌───────────────┐
              │   FastAPI      │  GET/POST /claims, /stats, /scrape
              └───────────────┘
"""

import argparse, hashlib, json, logging, os, re, sqlite3, time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("energy_intel_node")

# ──────────────────────────── CONFIG ─────────────────────────────

DB_PATH       = str(Path(__file__).resolve().parents[2] / "data" / "energy_intel.db")
ARXIV_API     = "https://export.arxiv.org/api/query"
USPTO_PV_API  = "https://api.patentsview.org/patents/query"
USPTO_ODP_URL = "https://developer.uspto.gov/api/v1/patent/query"
EPO_AUTH_URL    = "https://ops.epo.org/3.2/auth/accesstoken"
EPO_SEARCH_URL  = "https://ops.epo.org/3.2/rest-services/published-data/search"
EPO_BIBLIO_URL  = "https://ops.epo.org/3.2/rest-services/published-data/publication/docdb/{docno}/biblio"
EPO_ABSTRACT_URL = "https://ops.epo.org/3.2/rest-services/published-data/publication/docdb/{docno}/abstract"
EPO_TERMS     = ["solid state battery", "perovskite solar cell", "sodium ion battery",
                 "green hydrogen electrolysis", "flow battery"]
CLIMATE_FEEDS = [
    "https://cleantechnica.com/feed/",
    "https://renewablesnow.com/feed/",
]
SCRAPE_DELAY  = 2.0   # segundos entre requests (educado)
MAX_RESULTS   = 25    # por fuente por corrida

# Query arXiv acotada: categorias APLICADAS (fisica aplicada, quimica-fisica,
# ciencia de materiales, sistemas de energia, ing. civil) + terminos de
# energia/baterias. La query amplia anterior ("all:renewable energy AND
# cat:physics*") traia optica, nanofotonica y fisica general (80% ruido).
DEFAULT_QUERY = (
    '((all:"energy storage" OR all:battery OR all:"solar cell" OR all:photovoltaic '
    'OR all:electrolysis OR all:"green hydrogen" OR all:perovskite OR all:"flow battery" '
    'OR all:thermophotovoltaic OR all:fusion OR all:agrivoltaic) '
    'AND (cat:physics.app-ph OR cat:physics.chem-ph OR cat:cond-mat.mtrl-sci '
    'OR cat:eess.SY OR cat:cs.CE))'
)

# ──────────────────────── DATABASE LAYER ─────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    id            TEXT PRIMARY KEY,          -- hash(source_url + title + date)
    source_type   TEXT NOT NULL,             -- paper | patent | press_release
    source_url    TEXT NOT NULL,
    title         TEXT NOT NULL,
    authors       TEXT DEFAULT '',
    date_pub      TEXT NOT NULL,             -- ISO-8601
    technology    TEXT NOT NULL,             -- ej: solid-state-battery, perovskite-solar
    metric_name   TEXT DEFAULT '',           -- ej: energy_density, efficiency
    metric_value  REAL,
    metric_unit   TEXT DEFAULT '',           -- ej: Wh/kg, %
    claim_text    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'claimed',  -- claimed | disputed | debunked
    raw_json      TEXT DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tech   ON claims(technology);
CREATE INDEX IF NOT EXISTS idx_status ON claims(status);
CREATE INDEX IF NOT EXISTS idx_date   ON claims(date_pub);
"""
# SCHEMA VERSIONING (ADR-005) - P-100b, addendum bis
SCHEMA_VERSION = 1
MIGRATIONS = []

def apply_migrations(conn, sv, migs, label):
    """Contrato identico a core/sqlite_migrations.py (ADR-005 INV1c)."""
    uv = conn.execute("PRAGMA user_version").fetchone()[0]
    if uv > sv: raise RuntimeError(f'[{label}] uv={uv}>{sv}')
    for tgt, fn in sorted(migs, key=lambda x: x[0]):
        if tgt > uv: fn(conn); conn.execute(f'PRAGMA user_version={tgt}'); conn.commit()
    if conn.execute('PRAGMA user_version').fetchone()[0] < sv:
        conn.execute(f'PRAGMA user_version={sv}'); conn.commit()

@contextmanager
def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with db_conn() as c:
        c.executescript(SCHEMA)
        apply_migrations(c, SCHEMA_VERSION, MIGRATIONS, 'energy_intel')

def claim_id(url: str, title: str, date: str) -> str:
    raw = f"{url}|{title}|{date}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def upsert_claim(conn, claim: dict) -> bool:
    """Inserta claim si no existe (dedup por id). Devuelve True si nuevo."""
    cid = claim_id(claim["source_url"], claim["title"], claim["date_pub"])
    existing = conn.execute("SELECT 1 FROM claims WHERE id=?", (cid,)).fetchone()
    if existing:
        return False
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO claims (id,source_type,source_url,title,authors,date_pub,
            technology,metric_name,metric_value,metric_unit,claim_text,
            status,raw_json,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (cid, claim["source_type"], claim["source_url"], claim["title"],
          claim.get("authors",""), claim["date_pub"], claim["technology"],
          claim.get("metric_name",""), claim.get("metric_value"),
          claim.get("metric_unit",""), claim["claim_text"],
          claim.get("status","claimed"), json.dumps(claim.get("raw",{})),
          now, now))
    return True

# ──────────────────── EXTRACTION HELPERS ─────────────────────────

TECH_KEYWORDS = {
    "solid-state-battery":  r"solid.?state.?batter|\bssb\b|solid.?electrolyte|sulfide.?electrolyte",
    "perovskite-solar":     r"perovskite",
    "sodium-ion":           r"sodium.?ion|na.?ion\b|prussian.?blue|sodium.?batter",
    "green-hydrogen":       r"green.?hydrogen|electrolys|alkaline.?water|anion.?exchange.?membrane|proton.?exchange.?membrane|\bpem\b",
    "flow-battery":         r"flow.?batter|redox.?flow|vanadium.?flow|organic.?redox",
    "thermophotovoltaic":   r"thermophotovoltaic|\btpv\b|thermo.?photovoltaic",
    "fusion":               r"fusion.?energy|tokamak|stellarator|inertial.?confinement",
    "agrivoltaics":         r"agrivoltaic|agri.?voltaic|crop.?solar|dual.?use.?solar",
}

METRIC_PATTERNS = [
    # (regex, metric_name, unit, value_group_idx)
    (r"(\d+(?:\.\d+)?)\s*Wh\s*(?:kg[\-−]?1?|/kg)",
                                               "energy_density",   "Wh/kg", 1),
    (r"(\d+(?:\.\d+)?)\s*Wh\s*L[\-−]?1?",     "volumetric_density","Wh/L",1),
    (r"(\d+(?:\.\d+)?)\s*W\s*kg[\-−]?1?",     "specific_power",   "W/kg",  1),
    (r"(\d+(?:\.\d+)?)\s*kW\s*kg[\-−]?1?",    "specific_power",   "kW/kg", 1),
    (r"(\d+(?:\.\d+)?)\s*mAh\s*g[\-−]?1?",    "specific_capacity","mAh/g", 1),
    (r"efficiency\s+of\s+(\d+(?:\.\d+)?)\s*%",
                                               "efficiency",       "%",      1),
    (r"(\d+(?:\.\d+)?)\s*%\s*(?:efficiency|PCE|power conversion)",
                                               "efficiency",       "%",      1),
    (r"(\d+(?:\.\d+)?)\s*mW\s*cm[\-−]?2",     "power_density",    "mW/cm2", 1),
    (r"(\d+(?:\.\d+)?)\s*\$\/\s*kWh",         "cost",             "$/kWh",  1),
    (r"(\d+(?:\.\d+)?)\s*cents?\/\s*kWh",     "cost",             "cents/kWh",1),
    (r"(\d+(?:\.\d+)?)\s*%\s*(?:after|over|retains?)",
                                               "capacity_retention","%",     1),
    (r"(\d+(?:\.\d+)?)\s*hours?.*cycling",     "cycle_life",       "hours",  1),
    (r"(\d+(?:\.\d+)?)\s*cycles?",             "cycle_life",       "cycles", 1),
]

def classify_technology(text: str) -> str:
    low = text.lower()
    for tech, pat in TECH_KEYWORDS.items():
        if re.search(pat, low):
            return tech
    return "other"

def extract_metrics(text: str) -> dict:
    """Extrae la primera métrica reconocida del texto."""
    for pat, name, unit, gidx in METRIC_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return {"metric_name": name, "metric_value": float(m.group(gidx)),
                    "metric_unit": unit}
    return {}

# ──────────────────── SCRAPERS ───────────────────────────────────

def scrape_arxiv(query: str = DEFAULT_QUERY,
                 max_results: int = MAX_RESULTS) -> list[dict]:
    """ArXiv API (Atom XML) → lista de claims normalizados."""
    claims = []
    params = {"search_query": query, "start": 0, "max_results": max_results,
              "sortBy": "submittedDate", "sortOrder": "descending"}
    try:
        r = requests.get(ARXIV_API, params=params, timeout=30)
        r.raise_for_status()
    except Exception as e:
        logger.warning("[ArXiv] Error: %s", e)
        return claims

    soup = BeautifulSoup(r.text, "lxml-xml")
    for entry in soup.find_all("entry"):
        title_t = entry.find("title")
        summ_t  = entry.find("summary")
        id_t    = entry.find("id")
        pub_t   = entry.find("published")
        if not title_t or not id_t:
            continue
        title = title_t.get_text(strip=True).replace("\n"," ")
        abstract = summ_t.get_text(strip=True).replace("\n"," ") if summ_t else ""
        url = id_t.get_text(strip=True)
        published = pub_t.get_text(strip=True)[:10] if pub_t else ""
        author_names = entry.find_all("name")
        authors = ", ".join(a.get_text() for a in author_names[:5])
        tech = classify_technology(f"{title} {abstract}")
        meta = extract_metrics(f"{title} {abstract}")
        claims.append({
            "source_type": "paper",
            "source_url": url,
            "title": title,
            "authors": authors,
            "date_pub": published,
            "technology": tech,
            **meta,
            "claim_text": abstract[:500],
            "raw": {"abstract_len": len(abstract)},
        })
    print(f"[ArXiv] {len(claims)} papers")
    logger.info("arXiv scrape: %d papers, %d clasificados", len(claims),
                sum(1 for c in claims if c["technology"] != "other"))
    return claims


def scrape_uspto(terms: list[str] = None, max_results: int = MAX_RESULTS) -> list[dict]:
    """USPTO PatentsView → claims de patentes.

    La API legacy de api.patentsview.org migro al Open Data Portal (ODP) de
    developer.uspto.gov y ya no devuelve JSON (responde HTML). ODP requiere
    API key (variable USPTO_API_KEY). Sin key el scraper se salta con un
    warning visible — nunca mas fallo silencioso."""
    if not os.environ.get("USPTO_API_KEY"):
        logger.warning(
            "[USPTO] skip: PatentsView legacy migro a Open Data Portal "
            "(developer.uspto.gov). Registra una key y define USPTO_API_KEY "
            "para reactivar el scraper de patentes."
        )
        return []
    if terms is None:
        terms = ["solid state battery", "perovskite solar cell",
                 "sodium ion battery", "green hydrogen electrolysis"]
    claims = []
    for term in terms:
        body = {
            "q": {"_and": [
                {"_text_any": {"patent_title": term}},
                {"_gte": {"patent_date": "2024-01-01"}}
            ]},
            "f": ["patent_number","patent_title","patent_date",
                  "inventor_first_name","inventor_last_name","patent_abstract"],
            "s": [{"patent_date":"desc"}],
            "o": {"per_page": min(max_results, 25)}
        }
        try:
            r = requests.post(USPTO_ODP_URL, headers={"X-Api-Key": os.environ["USPTO_API_KEY"]},
                              json=body, timeout=30)
            r.raise_for_status()
        except Exception as e:
            logger.warning("[USPTO] Error '%s': %s", term, e)
            continue
        if not r.headers.get("content-type", "").startswith("application/json"):
            logger.warning("[USPTO] respuesta no-JSON para '%s' (API migrada/cambio de contrato): %s",
                           term, r.text[:120])
            continue
        try:
            patents = r.json().get("patents") or []
        except Exception:
            logger.warning("[USPTO] JSON invalido para '%s'", term)
            patents = []
        for p in patents:
            title = p.get("patent_title","")
            abstract = p.get("patent_abstract","") or ""
            invs = p.get("inventors") or []
            authors = ", ".join(
                f"{i.get('inventor_first_name','')} {i.get('inventor_last_name','')}".strip()
                for i in invs[:5])
            url = f"https://patents.google.com/patent/US{p.get('patent_number','')}"
            tech = classify_technology(f"{title} {abstract}")
            meta = extract_metrics(f"{title} {abstract}")
            claims.append({
                "source_type": "patent",
                "source_url": url,
                "title": title,
                "authors": authors,
                "date_pub": p.get("patent_date","")[:10],
                "technology": tech,
                **meta,
                "claim_text": abstract[:500],
                "raw": {"patent_number": p.get("patent_number","")},
            })
        time.sleep(SCRAPE_DELAY)
    logger.info("USPTO scrape: %d patents", len(claims))
    return claims


# ── EPO Open Patent Services (OPS) — patentes sin SSN ─────────────
# Registro gratuito en developers.epo.org (email, sin SSN). Cobertura
# mundial incl. EEUU (INPADOC). Credenciales via env:
#   EPO_CONSUMER_KEY / EPO_CONSUMER_SECRET
_EPO_TOKEN_CACHE: dict = {"token": None, "expires_at": 0.0}


def _epo_token() -> Optional[str]:
    """OAuth2 client_credentials -> Bearer token (cacheado hasta expirar)."""
    key = os.environ.get("EPO_CONSUMER_KEY", "")
    secret = os.environ.get("EPO_CONSUMER_SECRET", "")
    if not key or not secret:
        logger.warning(
            "[EPO] skip: faltan EPO_CONSUMER_KEY/EPO_CONSUMER_SECRET. Registro gratis "
            "en developers.epo.org (solo email, sin SSN) para activar patentes."
        )
        return None
    if _EPO_TOKEN_CACHE["token"] and time.time() < _EPO_TOKEN_CACHE["expires_at"]:
        return _EPO_TOKEN_CACHE["token"]
    try:
        r = requests.post(
            EPO_AUTH_URL,
            data={"grant_type": "client_credentials"},
            auth=(key, secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        _EPO_TOKEN_CACHE["token"] = data["access_token"]
        _EPO_TOKEN_CACHE["expires_at"] = time.time() + int(data.get("expires_in", 3000)) - 60
        return _EPO_TOKEN_CACHE["token"]
    except Exception as e:
        logger.warning("[EPO] token error: %s", e)
        return None


def _parse_epo_search_response(payload: dict) -> list:
    """Extrae doc-numbers (docdb: country.number.kind) del JSON de OPS search.

    OPS v3.2 real: la raiz es 'ops:biblio-search' (no 'ops:query-result') y los
    document-id vienen anidados como country/doc-number/kind con {'$': ...}.
    Devuelve docnos en formato docdb 'WO.2026160546.A1' para usar directo en
    publication/docdb/{docno}/biblio. Aislado para test sin red."""
    refs = []
    try:
        wpd = payload["ops:world-patent-data"]
        search = wpd.get("ops:biblio-search") or wpd.get("ops:query-result") or {}
        result = search.get("ops:search-result", {})
        pubs = result.get("ops:publication-reference", [])
        if isinstance(pubs, dict):
            pubs = [pubs]
        for pub in pubs:
            doc_ids = pub.get("document-id", [])
            if isinstance(doc_ids, dict):
                doc_ids = [doc_ids]
            docdb_docno = None
            epodoc_docno = None
            for did in doc_ids:
                if did.get("@document-id-type") == "docdb":
                    def _v(node):
                        return node.get("$") if isinstance(node, dict) else node
                    country = _v(did.get("country")) or ""
                    number = _v(did.get("doc-number")) or ""
                    kind = _v(did.get("kind")) or ""
                    if number:
                        docdb_docno = f"{country}.{number}.{kind}"
                elif did.get("@document-id-type") == "epodoc":
                    num = did.get("doc-number")
                    if isinstance(num, dict):
                        num = num.get("$")
                    if num:
                        epodoc_docno = num
            # Preferir docdb (formato real del search OPS v3.2); epodoc solo como fallback.
            if docdb_docno or epodoc_docno:
                refs.append(docdb_docno or epodoc_docno)
    except Exception:
        pass
    return refs


def _parse_epo_biblio_response(payload: dict) -> dict:
    """Extrae title/date/abstract del JSON de biblio OPS.

    OPS v3.2 real: 'exchange-documents' -> 'exchange-document' -> 'bibliographic-data'
    (sin prefijo ops:). El title es una LISTA de {'$': ..., '@lang': ...} — se elige
    la inglesa. Aislado para test sin red."""
    out: dict = {}
    try:
        wpd = payload["ops:world-patent-data"]
        docs = wpd.get("exchange-documents", {}).get("exchange-document", {})
        if isinstance(docs, list):
            docs = docs[0] if docs else {}
        biblio = docs.get("bibliographic-data", {}) or {}
        if not biblio:
            biblio = (wpd.get("ops:document-instance", {})
                          .get("ops:exchange-document", {})
                          .get("ops:bibliographic-data", {}) or {})
        title = biblio.get("invention-title", {}) or biblio.get("ops:invention-title", {})
        if isinstance(title, list):
            title = next((t for t in title if t.get("@lang") == "en"), title[0] if title else {})
        if isinstance(title, dict):
            out["title"] = (title.get("$") or title.get("@value") or "").strip()
        else:
            out["title"] = str(title).strip()
        pubref = biblio.get("publication-reference", {}) or biblio.get("ops:publication-reference", {})
        doc_ids = pubref.get("document-id", [])
        if isinstance(doc_ids, dict):
            doc_ids = [doc_ids]
        for did in doc_ids:
            date_node = did.get("date") or did.get("ops:publication-date", {})
            d = date_node.get("$") if isinstance(date_node, dict) else date_node
            if d and len(str(d)) == 8 and str(d).isdigit():
                out["date"] = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                break
        abstract = biblio.get("abstract", {})
        if not abstract:
            abstract = docs.get("abstract", {})
        if isinstance(abstract, list):
            for a in abstract:
                if a.get("@lang") == "en":
                    p = a.get("p", {})
                    if isinstance(p, dict):
                        out["abstract"] = p.get("$", "")
                    else:
                        out["abstract"] = str(p or "")
                    break
        elif isinstance(abstract, dict):
            txt = abstract.get("abstract-text", "") or abstract.get("ops:abstract-text", "")
            if isinstance(txt, dict):
                out["abstract"] = txt.get("$", "")
            elif isinstance(txt, str):
                out["abstract"] = txt
    except Exception:
        pass
    return out


def scrape_epo_ops(terms: list[str] = None, max_results: int = MAX_RESULTS) -> list[dict]:
    """EPO OPS → claims de patentes (cobertura mundial incl. EEUU).

    Registro gratuito por email en developers.epo.org (sin SSN), OAuth2
    client_credentials. Sin credenciales: skip visible, nunca silencioso."""
    if terms is None:
        terms = EPO_TERMS
    token = _epo_token()
    if not token:
        return []
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    claims = []
    for term in terms:
        try:
            r = requests.get(
                EPO_SEARCH_URL,
                params={"q": f'ti="{term}"', "Range": f"1-{min(max_results, 5)}"},
                headers=headers,
                timeout=30,
            )
            r.raise_for_status()
            doc_ids = _parse_epo_search_response(r.json())
        except Exception as e:
            logger.warning("[EPO] search error '%s': %s", term, e)
            continue
        for doc_id in doc_ids[:5]:
            try:
                rb = requests.get(EPO_BIBLIO_URL.format(docno=doc_id), headers=headers, timeout=30)
                rb.raise_for_status()
                biblio = _parse_epo_biblio_response(rb.json())
                if not biblio.get("abstract"):
                    ra = requests.get(EPO_ABSTRACT_URL.format(docno=doc_id), headers=headers, timeout=30)
                    ra.raise_for_status()
                    biblio.update(_parse_epo_biblio_response(ra.json()))
            except Exception as e:
                logger.warning("[EPO] biblio error %s: %s", doc_id, e)
                continue
            title = biblio.get("title", "")
            if not title:
                continue
            abstract = biblio.get("abstract", "") or ""
            tech = classify_technology(f"{title} {abstract}")
            meta = extract_metrics(f"{title} {abstract}")
            claims.append({
                "source_type": "patent",
                "source_url": f"https://worldwide.espacenet.com/patent/search?q={doc_id}",
                "title": title,
                "authors": "",
                "date_pub": biblio.get("date", "")[:10],
                "technology": tech,
                **meta,
                "claim_text": (abstract or title)[:500],
                "raw": {"epo_doc_id": doc_id},
            })
            time.sleep(SCRAPE_DELAY)
    logger.info("EPO OPS scrape: %d patents", len(claims))
    return claims

def scrape_climate_pr(feeds: list[str] = None) -> list[dict]:
    """RSS feeds de Climate Tech → press releases."""
    feeds = feeds or CLIMATE_FEEDS
    claims = []
    for feed_url in feeds:
        try:
            r = requests.get(feed_url, timeout=20,
                             headers={"User-Agent":"EnergyIntelBot/1.0"})
            r.raise_for_status()
        except Exception as e:
            logger.warning("[PR] Error %s: %s", feed_url, e)
            continue
        soup = BeautifulSoup(r.text, "lxml-xml")
        for item in soup.find_all("item")[:MAX_RESULTS]:
            title_tag = item.find("title")
            link_tag  = item.find("link")
            date_tag  = item.find("pubDate") or item.find("dc:date")
            desc_tag  = item.find("description") or item.find("content:encoded")
            title = title_tag.get_text(strip=True) if title_tag else ""
            link  = link_tag.get_text(strip=True) if link_tag else feed_url
            raw_date = date_tag.get_text(strip=True) if date_tag else ""
            desc  = desc_tag.get_text(strip=True)[:500] if desc_tag else title
            try:
                date_pub = datetime.strptime(raw_date[:25],
                             "%a, %d %b %Y %H:%M:%S").strftime("%Y-%m-%d")
            except Exception:
                date_pub = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            tech = classify_technology(f"{title} {desc}")
            if tech == "other":
                continue  # filtrar ruido
            meta = extract_metrics(f"{title} {desc}")
            claims.append({
                "source_type": "press_release",
                "source_url": link,
                "title": title,
                "authors": "",
                "date_pub": date_pub,
                "technology": tech,
                **meta,
                "claim_text": desc[:500],
                "raw": {"feed": feed_url},
            })
        time.sleep(SCRAPE_DELAY)
    logger.info("PR scrape: %d releases (de %d feeds)", len(claims), len(feeds))
    return claims

# ──────────────────── INGEST PIPELINE ────────────────────────────

def run_ingest():
    """Ejecuta todos los scrapers y hace upsert en la DB."""
    init_db()
    new = 0
    with db_conn() as conn:
        for scraper in [scrape_arxiv, scrape_uspto, scrape_epo_ops, scrape_climate_pr]:
            for claim in scraper():
                if upsert_claim(conn, claim):
                    new += 1
    logger.info("Ingesta completa: %d claims nuevos", new)
    return new

# ──────────────────── REST API ───────────────────────────────────

def create_app():
    from fastapi import FastAPI, Query, HTTPException
    from pydantic import BaseModel as PydModel

    app = FastAPI(title="Energy Intelligence Node",
                  version="1.0.0",
                  description="API para consultar claims de energías renovables")

    # ── Pydantic models ──
    class ClaimOut(PydModel):
        id: str; source_type: str; source_url: str; title: str
        authors: str = ""; date_pub: str; technology: str
        metric_name: str = ""; metric_value: Optional[float]=None
        metric_unit: str = ""; claim_text: str; status: str
        created_at: str; updated_at: str

    class ClaimIn(PydModel):
        source_type: str; source_url: str; title: str; authors: str = ""
        date_pub: str; technology: str; metric_name: str = ""
        metric_value: Optional[float]=None; metric_unit: str = ""
        claim_text: str; status: str = "claimed"

    class StatusPatch(PydModel):
        status: str  # claimed | disputed | debunked

    class StatsOut(PydModel):
        total_claims: int; by_source: dict; by_status: dict
        by_technology: dict

    # ── Helpers ──
    def row_to_dict(row):
        d = dict(row)
        d["metric_value"] = float(d["metric_value"]) if d["metric_value"] else None
        return d

    # ── Endpoints ──
    @app.get("/claims", response_model=list[ClaimOut])
    def list_claims(
        technology: Optional[str] = Query(None, description="Filtrar por tecnología"),
        status: Optional[str] = Query(None, description="claimed|disputed|debunked"),
        source_type: Optional[str] = Query(None, description="paper|patent|press_release"),
        metric_name: Optional[str] = Query(None, description="ej: energy_density"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        """Consultar claims con filtros opcionales."""
        conds, params = [], []
        if technology:  conds.append("technology=?");  params.append(technology)
        if status:      conds.append("status=?");      params.append(status)
        if source_type: conds.append("source_type=?"); params.append(source_type)
        if metric_name: conds.append("metric_name=?"); params.append(metric_name)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        with db_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM claims {where} ORDER BY date_pub DESC LIMIT ? OFFSET ?",
                params + [limit, offset]).fetchall()
        return [row_to_dict(r) for r in rows]

    @app.get("/claims/{claim_id}", response_model=ClaimOut)
    def get_claim(claim_id: str):
        with db_conn() as conn:
            row = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Claim no encontrado")
        return row_to_dict(row)

    @app.post("/claims", response_model=ClaimOut, status_code=201)
    def add_claim(body: ClaimIn):
        with db_conn() as conn:
            claim = body.model_dump()
            cid = claim_id(claim["source_url"], claim["title"], claim["date_pub"])
            if conn.execute("SELECT 1 FROM claims WHERE id=?", (cid,)).fetchone():
                raise HTTPException(409, "Claim ya existe")
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("""
                INSERT INTO claims (id,source_type,source_url,title,authors,date_pub,
                    technology,metric_name,metric_value,metric_unit,claim_text,
                    status,raw_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (cid, claim["source_type"], claim["source_url"], claim["title"],
                  claim.get("authors",""), claim["date_pub"], claim["technology"],
                  claim.get("metric_name",""), claim.get("metric_value"),
                  claim.get("metric_unit",""), claim["claim_text"],
                  claim.get("status","claimed"), "{}", now, now))
            row = conn.execute("SELECT * FROM claims WHERE id=?", (cid,)).fetchone()
        return row_to_dict(row)

    @app.patch("/claims/{claim_id}", response_model=ClaimOut)
    def update_status(claim_id: str, body: StatusPatch):
        if body.status not in ("claimed","disputed","debunked"):
            raise HTTPException(400, "status debe ser claimed|disputed|debunked")
        with db_conn() as conn:
            if not conn.execute("SELECT 1 FROM claims WHERE id=?", (claim_id,)).fetchone():
                raise HTTPException(404, "Claim no encontrado")
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("UPDATE claims SET status=?, updated_at=? WHERE id=?",
                         (body.status, now, claim_id))
            row = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        return row_to_dict(row)

    @app.get("/stats", response_model=StatsOut)
    def stats():
        with db_conn() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM claims").fetchone()["c"]
            by_source = dict(conn.execute(
                "SELECT source_type, COUNT(*) c FROM claims GROUP BY source_type").fetchall())
            by_status = dict(conn.execute(
                "SELECT status, COUNT(*) c FROM claims GROUP BY status").fetchall())
            by_tech = dict(conn.execute(
                "SELECT technology, COUNT(*) c FROM claims GROUP BY technology "
                "ORDER BY c DESC LIMIT 20").fetchall())
        return {"total_claims": total, "by_source": by_source,
                "by_status": by_status, "by_technology": by_tech}

    @app.post("/scrape")
    def trigger_scrape():
        """Dispara ingesta asíncrona (en prod usar Celery/background task)."""
        new = run_ingest()
        return {"new_claims": new, "status": "ok"}

    @app.get("/technologies")
    def list_technologies():
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT technology, COUNT(*) c FROM claims GROUP BY technology "
                "ORDER BY c DESC").fetchall()
        return [{"technology": r["technology"], "count": r["c"]} for r in rows]

    return app

# ──────────────────── MAIN ───────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Energy Intelligence Node")
    parser.add_argument("--scrape", action="store_true",
                        help="Solo ejecutar ingesta (sin API)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default=DB_PATH, help="Ruta a SQLite DB")
    args = parser.parse_args()

    DB_PATH = args.db
    init_db()

    if args.scrape:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        run_ingest()
    else:
        import uvicorn
        app = create_app()
        print(f"\n⚡ Energy Intelligence Node → http://{args.host}:{args.port}")
        print(f"   Docs: http://{args.host}:{args.port}/docs")
        print(f"   DB:   {DB_PATH}\n")
        uvicorn.run(app, host=args.host, port=args.port)
