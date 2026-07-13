# -*- coding: utf-8 -*-
"""
Energy Intel → Telegram integration.

Hooks into the energy_intel_node ingest pipeline to send Telegram
notifications when new frontier-technology claims are discovered.
Also scans funding/VC feeds and tech radar RSS for energy-related entries.

Usage from the agent cycle (Phase C or standalone):
    from services.energy_intel_telegram import run_energy_intel_with_alerts, should_run_energy_intel
    if should_run_energy_intel():
        new_count = run_energy_intel_with_alerts(telegram_client)
"""

import json
import logging
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("services.energy_intel_telegram")

# Technologies considered "frontier" (cutting-edge, worth alerting)
FRONTIER_TECHNOLOGIES = {
    "solid-state-battery",
    "perovskite-solar",
    "thermophotovoltaic",
    "fusion",
    "flow-battery",
}

# Only alert on claims with quantified metrics (not generic press releases)
MIN_CLAIM_TEXT_LEN = 50

# Throttle: minimum interval between energy intel runs
_LAST_RUN_FILE = Path("data/last_energy_intel_run.txt")
ENERGY_INTEL_INTERVAL_MINUTES = 60


def _get_recent_new_claims(db_path: str = "data/energy_intel.db", limit: int = 5) -> list:
    """Fetch the most recently ingested claims that are new (last run)."""
    try:
        if not Path(db_path).exists():
            return []
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # Get claims created in the last 10 minutes (covers one scrape run)
        rows = conn.execute("""
            SELECT title, technology, metric_name, metric_value, metric_unit,
                   source_url, source_type, claim_text
            FROM claims
            WHERE created_at >= datetime('now', '-10 minutes')
              AND technology != 'other'
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("energy_intel_telegram: error reading claims DB — %s", e)
        return []


def _is_frontier_claim(claim: dict) -> bool:
    """Determine if a claim qualifies as frontier tech worth alerting."""
    tech = claim.get("technology", "")
    if tech in FRONTIER_TECHNOLOGIES:
        return True
    # Also alert if it has quantified metrics (regardless of tech)
    if claim.get("metric_value") and claim.get("metric_name"):
        return True
    return False


def _format_claim_alert(claim: dict) -> str:
    """Format a single claim as a Telegram message."""
    tech = claim.get("technology", "unknown")
    title = claim.get("title", "")[:120]
    source_type = claim.get("source_type", "")
    url = claim.get("source_url", "")

    lines = [f"⚡ <b>Energy Intel: {tech}</b>"]
    lines.append(f"📄 {title}")

    metric_name = claim.get("metric_name")
    metric_value = claim.get("metric_value")
    metric_unit = claim.get("metric_unit", "")
    if metric_name and metric_value:
        lines.append(f"📊 {metric_name}: {metric_value} {metric_unit}")

    lines.append(f"🏷️ Fuente: {source_type}")
    if url:
        lines.append(f"🔗 {url}")

    return "\n".join(lines)


def run_energy_intel_with_alerts(telegram_client=None) -> int:
    """Run energy intel ingest and send Telegram alerts for frontier claims.

    Returns the number of new claims ingested.
    """
    try:
        # Import and run the ingest pipeline
        import sys
        import os
        # energy_intel_node.py lives in docs/ein/ (standalone CLI tool)
        _ein_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "ein")
        sys.path.insert(0, _ein_path)
        from energy_intel_node import run_ingest
        new_count = run_ingest()
    except ImportError as e:
        logger.warning("energy_intel_telegram: cannot import energy_intel_node — %s", e)
        return 0
    except Exception as e:
        logger.warning("energy_intel_telegram: ingest failed — %s", e)
        return 0

    # Mark the run timestamp
    _mark_last_run()

    if new_count == 0 or not telegram_client:
        return new_count

    # Fetch the new claims and alert on frontier ones
    try:
        new_claims = _get_recent_new_claims()
        frontier_claims = [c for c in new_claims if _is_frontier_claim(c)]

        if not frontier_claims:
            logger.info("energy_intel_telegram: %d new claims, none frontier-worthy", new_count)
            return new_count

        # Send max 3 alerts per run to avoid spam
        for claim in frontier_claims[:3]:
            msg = _format_claim_alert(claim)
            try:
                telegram_client.send_message(msg, parse_mode="HTML")
            except Exception as e:
                logger.warning("energy_intel_telegram: Telegram send failed — %s", e)
                break

        logger.info(
            "energy_intel_telegram: sent %d alerts out of %d frontier claims",
            min(len(frontier_claims), 3), len(frontier_claims),
        )
    except Exception as e:
        logger.warning("energy_intel_telegram: alert processing failed — %s", e)

    return new_count


# ── Throttle helpers ─────────────────────────────────────────────


def should_run_energy_intel() -> bool:
    """Check if enough time has passed since the last energy intel run (1h throttle)."""
    try:
        if not _LAST_RUN_FILE.exists():
            return True
        last_run_str = _LAST_RUN_FILE.read_text(encoding="utf-8").strip()
        last_run = datetime.fromisoformat(last_run_str)
        elapsed = datetime.now() - last_run
        return elapsed >= timedelta(minutes=ENERGY_INTEL_INTERVAL_MINUTES)
    except Exception:
        return True


def minutes_since_last_run() -> Optional[float]:
    """Return minutes since last energy intel run, or None if never run."""
    try:
        if not _LAST_RUN_FILE.exists():
            return None
        last_run_str = _LAST_RUN_FILE.read_text(encoding="utf-8").strip()
        last_run = datetime.fromisoformat(last_run_str)
        elapsed = datetime.now() - last_run
        return elapsed.total_seconds() / 60.0
    except Exception:
        return None


def _mark_last_run() -> None:
    """Record the current time as the last energy intel run."""
    try:
        _LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LAST_RUN_FILE.write_text(datetime.now().isoformat(), encoding="utf-8")
    except Exception as e:
        logger.warning("energy_intel_telegram: could not save last run timestamp — %s", e)


# ── Funding/VC & Tech Radar RSS scanning ─────────────────────

_FUNDING_FEEDS = [
    "https://news.crunchbase.com/feed/",
    "https://cleantechnica.com/feed/",
]

_TECH_RADAR_FEEDS = [
    "https://www.technologyreview.com/feed/",
]

_ENERGY_KEYWORDS = frozenset([
    "energy", "cleantech", "battery", "solar", "grid", "hydrogen",
    "wind", "storage", "renewable", "carbon", "climate", "ev",
    "charging", "nuclear", "fusion", "geothermal", "efficiency",
    "electrolysis", "perovskite", "solid-state", "sodium-ion",
])


def _fetch_rss_entries(feed_url: str, max_entries: int = 10) -> List[Dict[str, str]]:
    """Fetch RSS feed and return list of {title, link, summary, published}."""
    try:
        import requests
        resp = requests.get(feed_url, timeout=15, headers={"User-Agent": "EnergyIntelBot/1.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        entries = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "")[:300].strip()
            pub = (item.findtext("pubDate") or "").strip()
            if title:
                entries.append({"title": title, "link": link, "summary": desc, "published": pub})
            if len(entries) >= max_entries:
                break
        return entries
    except Exception as e:
        logger.warning("Failed to fetch RSS %s: %s", feed_url, e)
        return []


def _filter_energy_entries(entries: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Keep only entries with energy-related keywords."""
    result = []
    for entry in entries:
        text = f"{entry['title']} {entry.get('summary', '')}".lower()
        if any(kw in text for kw in _ENERGY_KEYWORDS):
            result.append(entry)
    return result


def run_funding_scan(telegram_client) -> int:
    """Scan funding/VC feeds and alert on energy-related entries."""
    if not telegram_client:
        return 0
    all_entries = []
    for feed_url in _FUNDING_FEEDS:
        try:
            entries = _fetch_rss_entries(feed_url)
            all_entries.extend(_filter_energy_entries(entries))
        except Exception as e:
            logger.warning("Funding scan error for %s: %s", feed_url, e)

    if not all_entries:
        return 0

    for entry in all_entries[:5]:  # Max 5 alerts per scan
        msg = f"💰 <b>Funding/News</b>\n{entry['title'][:120]}\n🔗 {entry.get('link', '')}"
        try:
            telegram_client.send_message(msg, parse_mode="HTML")
        except Exception as e:
            logger.warning("Telegram send failed: %s", e)
            break

    logger.info("Energy Intel funding scan: %d entries found, %d alerted", len(all_entries), min(len(all_entries), 5))
    return len(all_entries)


def run_tech_radar_scan(telegram_client) -> int:
    """Scan tech radar feeds and alert on energy-related entries."""
    if not telegram_client:
        return 0
    all_entries = []
    for feed_url in _TECH_RADAR_FEEDS:
        try:
            entries = _fetch_rss_entries(feed_url)
            all_entries.extend(_filter_energy_entries(entries))
        except Exception as e:
            logger.warning("Tech radar scan error for %s: %s", feed_url, e)

    if not all_entries:
        return 0

    for entry in all_entries[:3]:  # Max 3 alerts per scan
        msg = f"📡 <b>Tech Radar</b>\n{entry['title'][:120]}\n🔗 {entry.get('link', '')}"
        try:
            telegram_client.send_message(msg, parse_mode="HTML")
        except Exception as e:
            logger.warning("Telegram send failed: %s", e)
            break

    logger.info("Energy Intel tech radar: %d entries found, %d alerted", len(all_entries), min(len(all_entries), 3))
    return len(all_entries)


# ── Weekly Digest ────────────────────────────────────────────

_WEEKLY_DIGEST_STATE = Path("data/energy_weekly_digest_last.json")


def should_run_weekly_digest() -> bool:
    """True if today is Monday and digest hasn't run today."""
    now = datetime.now()
    if now.weekday() != 0:  # Monday = 0
        return False
    if _WEEKLY_DIGEST_STATE.exists():
        try:
            data = json.loads(_WEEKLY_DIGEST_STATE.read_text(encoding="utf-8"))
            last = datetime.fromisoformat(data["last_run"])
            if (now - last).total_seconds() < 72000:  # 20h
                return False
        except Exception:
            pass
    return True


def run_weekly_digest(telegram_client) -> None:
    """Send weekly summary of energy claims via Telegram."""
    if not telegram_client:
        return
    try:
        from services.energy_knowledge_base import EnergyKnowledgeBase
        kb = EnergyKnowledgeBase(Path("data/energy_intel.db"))
        if not kb.available:
            return
        claims = kb.get_recent_claims(limit=50)
    except Exception as e:
        logger.warning("Weekly digest: could not load claims — %s", e)
        return

    if not claims:
        return

    frontier = [c for c in claims if _is_frontier_claim(c)]
    msg_lines = [
        f"📊 <b>Weekly Energy Intel Digest</b>",
        f"Total claims: {len(claims)} | Frontier: {len(frontier)}",
        "",
    ]
    for c in frontier[:10]:
        title = (c.get("title") or "")[:80]
        tech = c.get("technology", "")
        msg_lines.append(f"• [{tech}] {title}")

    try:
        telegram_client.send_message("\n".join(msg_lines), parse_mode="HTML")
    except Exception as e:
        logger.warning("Weekly digest send failed: %s", e)
        return

    # Record last run
    try:
        _WEEKLY_DIGEST_STATE.parent.mkdir(parents=True, exist_ok=True)
        _WEEKLY_DIGEST_STATE.write_text(
            json.dumps({"last_run": datetime.now().isoformat()}),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Weekly digest: could not save state — %s", e)
