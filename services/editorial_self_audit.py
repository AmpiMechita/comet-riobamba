# -*- coding: utf-8 -*-
"""Auditoria editorial propia de COMET-RIOBAMBA (24/08/2026).

Diagnostico computable de como se presenta el agente en Moltbook, motivado
por la auditoria manual del 24/08 (hallazgos: fatiga de plantilla 'a
defensible starting point' x34, engagement por post mediana 3 ups / 2
comentarios, juez interno sin correlacion con upvotes reales 5% vs 3%).

Metricas:
  1. Cadencia (posts 24h / 7d)
  2. Largo de body (mediana / p90)
  3. CTA: tasa de cierre con pregunta + especificidad (nombra numero/umbral)
  4. Tasa de citas (paper/arXiv/study) — techo estilo erudito-citador
  5. Diversidad de aperturas (bigramas iniciales unicos en ventana)
  6. Fatiga de plantilla (tetragramas repetidos entre posts)
  7. Titulos via API: scan de artefactos + rango 6-14 palabras
  8. Engagement real (posts >= 24h): mediana ups/comentarios, % sin engagement
  9. Calibracion juez<->mundo: value_score vs upvotes reales (comment_votes)

Salidas: data/editorial_self_audit.json + summary_line para el ciclo.
CLI: python -m services.editorial_self_audit
"""

from __future__ import annotations

import json
import logging
import os
import re
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("services.editorial_self_audit")

_POSTS_STORE = "data/published_posts.json"
_VOTES_LOG = "data/comment_votes.jsonl"
_STATE_PATH = "data/editorial_self_audit.json"
_INTERVAL_MIN = float(os.getenv("EDITORIAL_AUDIT_INTERVAL_MINUTES", "360"))

_CITE_PATTERN = re.compile(r"\barXiv\b|\bpaper\b|\bstudy\b|\bresearchers?\b", re.IGNORECASE)
_NUM_PATTERN = re.compile(r"\d")
_STOP = set(
    "the a an of to in on for and or is are was were be been it its this that "
    "with as by at from not but if then than so such can could will would may "
    "might must do does did have has had our their your we you they i".split()
)


# ── Pure helpers (testables sin IO ni red) ────────────────────────────


def _analyze_corpus(posts: List[Dict[str, Any]], window: int = 50) -> Dict[str, Any]:
    """Metricas estructurales sobre los ultimos `window` posts del store.

    posts: lista con {body, published_at} (esquema de published_posts.json).
    """
    bodies = [str(p.get("body") or "") for p in posts[-window:]]
    bodies = [b for b in bodies if b.strip()]
    n = len(bodies)
    if n == 0:
        return {"posts_analyzed": 0}

    now = datetime.now(timezone.utc)
    last_24h = sum(
        1 for p in posts
        if _age_hours(str(p.get("published_at") or ""), now) is not None
        and _age_hours(str(p.get("published_at") or ""), now) <= 24
    )
    last_7d = sum(
        1 for p in posts
        if _age_hours(str(p.get("published_at") or ""), now) is not None
        and _age_hours(str(p.get("published_at") or ""), now) <= 168
    )

    lens = [len(b) for b in bodies]
    cta = [b.rstrip() for b in bodies]
    cta_rate = round(100 * sum(1 for b in cta if b.endswith("?")) / n)
    # Especificidad del CTA: la pregunta final nombra un numero o vocabulario
    # de umbral — una pregunta accionable, no un 'what do you think?' generico.
    threshold_words = ("gate", "threshold", "limit", "budget", "cap", "%", "rate", "ratio")
    cta_specific = 0
    for b in cta:
        if not b.endswith("?"):
            continue
        last_sent = re.split(r"(?<=[.!?])\s+", b)[-1].lower()
        if _NUM_PATTERN.search(last_sent) or any(w in last_sent for w in threshold_words):
            cta_specific += 1
    question_posts = sum(1 for b in cta if b.endswith("?"))

    citation_rate = round(100 * sum(1 for b in bodies if _CITE_PATTERN.search(b)) / n)

    openers = Counter(" ".join(b.lower().split()[:2]) for b in bodies)
    opener_diversity = round(100 * len(openers) / n)

    tetra = Counter()
    for b in bodies[:25]:  # fatiga se mide en la mitad reciente de la ventana
        ws = re.findall(r"[a-z']+", b.lower())
        seen_local = set()
        for i in range(len(ws) - 3):
            t = tuple(ws[i:i + 4])
            if t in seen_local:
                continue  # no inflar por repeticion dentro del mismo post
            seen_local.add(t)
            if len(set(t) & _STOP) <= 1:
                tetra[t] += 1
    top_tetra, top_count = ("", 0)
    if tetra:
        top_tetra, top_count = tetra.most_common(1)[0]
    # share de posts que contienen ALGUN tetragrama presente en >=3 posts
    hot = {t for t, c in tetra.items() if c >= 3}
    posts_with_hot = 0
    for b in bodies[:25]:
        ws = re.findall(r"[a-z']+", b.lower())
        grams = {" ".join(ws[i:i + 4]) for i in range(len(ws) - 3)}
        if any(" ".join(t) in grams for t in hot):
            posts_with_hot += 1
    fatigue_share = round(100 * posts_with_hot / min(n, 25)) if bodies[:25] else 0

    return {
        "posts_analyzed": n,
        "posts_last_24h": last_24h,
        "posts_last_7d": last_7d,
        "median_len": int(statistics.median(lens)),
        "p90_len": sorted(lens)[int(len(lens) * 0.9)],
        "cta_rate_pct": cta_rate,
        "cta_specific_pct": round(100 * cta_specific / question_posts) if question_posts else 0,
        "citation_rate_pct": citation_rate,
        "opener_diversity_pct": opener_diversity,
        "template_fatigue_pct": fatigue_share,
        "top_tetragram": {"gram": " ".join(top_tetra), "count": top_count} if top_count else None,
    }


def _analyze_votes(vote_records: List[Dict[str, Any]], days: int = 30) -> Dict[str, Any]:
    """Calibracion juez<->mundo: upvote rate por bucket de value_score."""
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    buckets: Dict[str, List[int]] = {"<=0.3": [], "0.31-0.5": [], ">0.5": []}
    for e in vote_records:
        if str(e.get("date", "")) < cut:
            continue
        sc = e.get("value_score")
        up = e.get("upvotes")
        if sc is None or up is None:
            continue
        k = "<=0.3" if sc <= 0.3 else ("0.31-0.5" if sc <= 0.5 else ">0.5")
        buckets[k].append(1 if up else 0)
    out: Dict[str, Any] = {}
    total_up = total_n = 0
    for k, ups in buckets.items():
        if ups:
            rate = round(100 * sum(ups) / len(ups))
            out[k] = {"n": len(ups), "upvote_rate_pct": rate}
            total_up += sum(ups)
            total_n += len(ups)
    out["overall_upvote_rate_pct"] = round(100 * total_up / total_n) if total_n else None
    out["calibrated"] = (
        bool(out.get(">0.5")) and bool(out.get("<=0.3"))
        and out[">0.5"]["upvote_rate_pct"] > out["<=0.3"]["upvote_rate_pct"]
    )
    return out


def _age_hours(iso_ts: str, now: datetime) -> Optional[float]:
    try:
        dt = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt).total_seconds() / 3600
    except (ValueError, TypeError):
        return None


def _analyze_api_posts(post_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Titulos (higiene) y engagement real (posts con >=24h de maduracion)."""
    titles_ok = titles_bad = title_word_ok = 0
    bad_examples: List[str] = []
    ups_list: List[int] = []
    cms_list: List[int] = []
    zero_engagement = matured = 0
    for rec in post_records:
        title = str(rec.get("title") or "")
        age_h = _age_hours(str(rec.get("published_at") or ""), datetime.now(timezone.utc))
        if title:
            from services.quality_governor import title_has_scaffold
            if title_has_scaffold(title) or len(title) < 12:
                titles_bad += 1
                if len(bad_examples) < 3:
                    bad_examples.append(title[:60])
            else:
                titles_ok += 1
                if 6 <= len(title.split()) <= 14:
                    title_word_ok += 1
        ups, cms = rec.get("ups"), rec.get("comments")
        if age_h is not None and age_h >= 24 and isinstance(ups, int) and isinstance(cms, int):
            matured += 1
            ups_list.append(ups)
            cms_list.append(cms)
            if ups == 0 and cms == 0:
                zero_engagement += 1
    return {
        "titles_checked": titles_ok + titles_bad,
        "titles_artifacts": titles_bad,
        "title_bad_examples": bad_examples,
        "titles_in_range_6_14_words_pct": round(100 * title_word_ok / titles_ok) if titles_ok else None,
        "engagement_matured_posts": matured,
        "median_ups": int(statistics.median(ups_list)) if ups_list else None,
        "median_comments": int(statistics.median(cms_list)) if cms_list else None,
        "zero_engagement_pct": round(100 * zero_engagement / matured) if matured else None,
    }


# ── IO wrappers ───────────────────────────────────────────────────────


def compute_editorial_audit(moltbook: Optional[Any] = None, max_api_posts: int = 15) -> Dict[str, Any]:
    """Auditoria completa. moltbook: cliente opcional (si falta, sin metricas API)."""
    try:
        with open(_POSTS_STORE, encoding="utf-8") as f:
            posts = json.load(f)
    except (OSError, ValueError):
        posts = []
    corpus = _analyze_corpus(posts if isinstance(posts, list) else [])

    try:
        with open(_VOTES_LOG, encoding="utf-8") as f:
            votes = [json.loads(line) for line in f if line.strip()]
    except (OSError, ValueError):
        votes = []
    calibration = _analyze_votes(votes)

    api_metrics: Dict[str, Any] = {}
    if moltbook is not None and posts:
        candidates = [
            p for p in reversed(posts[-30:])
            if p.get("post_id")
        ]
        checked = 0
        enriched: List[Dict[str, Any]] = []
        for p in candidates:
            if checked >= max_api_posts:
                break
            try:
                d = moltbook.get_post(p["post_id"])
                post = d.get("post", d) if isinstance(d, dict) else {}
                enriched.append({
                    "published_at": p.get("published_at"),
                    "title": post.get("title") or "",
                    # esquema real get_post: upvotes / comment_count
                    "ups": post.get("upvotes", post.get("upvoteCount")),
                    "comments": post.get("comment_count", post.get("commentCount")),
                })
                checked += 1
            except Exception as e:
                logger.debug("audit: get_post fallo (%s)", e)
                break  # API caida: metricas API parcialmente ausentes
        if enriched:
            api_metrics = _analyze_api_posts(enriched)

    report: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **corpus,
        **{k: v for k, v in calibration.items()},
        **api_metrics,
    }
    report["summary_line"] = _summary_line(report)
    _save(report)
    return report


def _summary_line(r: Dict[str, Any]) -> str:
    parts = [
        "posts24h={}".format(r.get("posts_last_24h", "?")),
        "cta={}%".format(r.get("cta_rate_pct", "?")),
        "fatiga={}%".format(r.get("template_fatigue_pct", "?")),
        "divers_apertura={}%".format(r.get("opener_diversity_pct", "?")),
    ]
    if r.get("median_ups") is not None:
        parts.append("eng={}/{} ups/cmt".format(r["median_ups"], r.get("median_comments")))
    if r.get("overall_upvote_rate_pct") is not None:
        parts.append("upvotes_cmt={}%" .format(r["overall_upvote_rate_pct"]))
    return ", ".join(parts)


def _load_state() -> Dict[str, Any]:
    try:
        with open(_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(report: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_PATH) or ".", exist_ok=True)
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.debug("audit: no se pudo persistir estado: %s", e)


def should_run_audit() -> bool:
    ts = _load_state().get("ts")
    if not ts:
        return True
    try:
        last = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return True
    elapsed_min = (datetime.now(timezone.utc) - last).total_seconds() / 60
    return elapsed_min >= _INTERVAL_MIN


def run_if_due(moltbook: Optional[Any] = None, force: bool = False) -> Optional[Dict[str, Any]]:
    if not force and not should_run_audit():
        return None
    return compute_editorial_audit(moltbook=moltbook)


def main() -> int:  # pragma: no cover - CLI
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    client = None
    try:
        from dotenv import load_dotenv
        load_dotenv()
        from services.moltbook_api_client import MoltbookAPIClient
        try:
            import keyring
            _mb_key = keyring.get_password("comet_riobamba", "moltbook_api_key")
        except Exception:
            _mb_key = None
        client = MoltbookAPIClient(
            base_url=os.getenv("MOLTBOOK_BASE_URL"),
            api_key=_mb_key or os.getenv("MOLTBOOK_API_KEY"),
        )
    except Exception as e:
        print(f"(sin metricas API: {e})")
    report = run_if_due(moltbook=client, force=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
