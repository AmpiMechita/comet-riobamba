"""
Refresh data/topic_performance.jsonl with live score/comment_count from Moltbook API.

Usage:
    python scripts/refresh_topic_performance.py

Safe to run: makes only GET requests (read-only).
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from services.moltbook_api_client import MoltbookAPIClient

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)

load_dotenv(Path(".").resolve() / ".env", override=True)
client = MoltbookAPIClient()
data_path = Path("data/topic_performance.jsonl")

# ── Backup ────────────────────────────────────────────────────────────
backup_path = data_path.with_suffix(f".jsonl.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
if data_path.exists():
    with open(data_path, "r", encoding="utf-8") as f:
        original = f.read()
    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(original)
    print(f"Backup -> {backup_path}")

# ── Read all records ──────────────────────────────────────────────────
with open(data_path, "r", encoding="utf-8") as f:
    records = [json.loads(line) for line in f if line.strip()]

print(f"\nRecords loaded: {len(records)}")

# ── Refresh ───────────────────────────────────────────────────────────
checked = 0
failed = 0
fail_reasons: dict[str, int] = {}

for i, rec in enumerate(records):
    post_id = rec.get("post_id", "").strip()

    if not post_id or not UUID_RE.match(post_id) or "dry-run" in post_id.lower():
        continue

    time.sleep(0.6)

    post = client.get_post(post_id)
    if post is None:
        failed += 1
        continue

    score = post.get("score") or post.get("upvotes") or 0
    comment_count = post.get("comment_count", 0)
    now_iso = datetime.now(timezone.utc).isoformat()

    rec["score"] = score
    rec["comment_count"] = comment_count
    rec["score_checked"] = True
    rec["checked_at"] = now_iso
    checked += 1

    if (i + 1) % 25 == 0:
        print(f"  ... {i+1}/{len(records)} checked={checked} failed={failed}")

# ── Write back ────────────────────────────────────────────────────────
with open(data_path, "w", encoding="utf-8") as f:
    for rec in records:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

# ── Summary ───────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print(f"Posts checked : {checked}")
print(f"Posts failed  : {failed}")
if fail_reasons:
    print(f"Fail reasons  : {json.dumps(fail_reasons, indent=2)}")
print(f"{'='*70}")

# Engagement ranking: only records where score_checked is True and post exists
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
