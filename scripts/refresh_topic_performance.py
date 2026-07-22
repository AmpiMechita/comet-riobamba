"""
Refresh data/topic_performance.jsonl with live score/comment_count from Moltbook API.

Usage:
    python scripts/refresh_topic_performance.py

Safe to run: makes only GET requests (read-only).

La logica vive en services/topic_performance_refresh.py (compartida con el
refresh automatico de Fase C). Este script la corre SIN ventana
(window_days=None): refresca todos los registros, comportamiento historico.
"""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(".").resolve() / ".env", override=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s|%(name)s|%(message)s")

from services.topic_performance_refresh import DATA_PATH, refresh_topic_performance

# ── Refresh (sin ventana: todos los registros, uso manual) ────────────
result = refresh_topic_performance(window_days=None)

if result["backup"]:
    print(f"Backup -> {result['backup']}")
print(f"\nRecords loaded: {result['records']}")

# ── Summary ───────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print(f"Posts checked : {result['checked']}")
print(f"Posts failed  : {result['failed']}")
print(f"{'='*70}")

# Engagement ranking: only records where score_checked is True and post exists
records = []
if DATA_PATH.exists():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]

scored = [r for r in records if r.get("score_checked") is True]
scored.sort(key=lambda r: (r.get("score", 0) or 0) + (r.get("comment_count", 0) or 0), reverse=True)

print(f"\n{'Engagement ranking (score + comment_count, descending):'}")
print(f"{'topic':<70} {'score':>6} {'comments':>8} {'published_at':<30}")
print("-" * 114)
for r in scored:
    topic = (r.get("topic") or "")[:68]
    s = r.get("score", 0) or 0
    cc = r.get("comment_count", 0) or 0
    pub = (r.get("published_at") or "")[:29]
    print(f"{topic:<70} {s:>6} {cc:>8} {pub:<30}")

print(f"\nTotal scored records: {len(scored)}")
