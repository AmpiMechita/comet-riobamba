#!/usr/bin/env python3
"""
CLI: Generate energy intelligence report from energy_intel.db via LLM.

Usage:
    python scripts/generate_energy_report.py
    python scripts/generate_energy_report.py --watch --interval 3600
"""

import argparse
import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_proj_root = Path(__file__).resolve().parent.parent
if str(_proj_root) not in sys.path:
    sys.path.insert(0, str(_proj_root))

from services.energy_knowledge_base import EnergyKnowledgeBase
from services.model_cascade import ModelCascade
from config.credentials import Credentials


SYSTEM_PROMPT = (
    "You are Dr. Aris Thorne, an R&D intelligence analyst for next-gen renewable energy.\n"
    "Analyze the following raw claims extracted from recent scientific papers and press releases.\n"
    "Identify:\n"
    "\n"
    "1. The most promising technological breakthrough (and its fatal flaw or scaling bottleneck).\n"
    "2. The most overhyped claim (and why the physics or economics do not support it yet).\n"
    "3. A hidden contradiction between two of the claims.\n"
    "\n"
    "OUTPUT FORMAT: Write in valid Markdown. Use headers (##), bullet points, "
    "and bold text for key metrics. Do not use emojis. Be brutally technical and precise."
)


def _format_claims(claims: list[dict]) -> str:
    lines = []
    for i, c in enumerate(claims, 1):
        tech = c.get("technology", "unknown")
        title = c.get("title", "").strip()
        source = c.get("source_type", "unknown")
        date = c.get("date_pub", "unknown")
        text = c.get("claim_text", "")
        metric_value = c.get("metric_value")
        metric_unit = c.get("metric_unit", "")
        metric_str = ""
        if metric_value is not None and metric_unit:
            metric_str = f" [{metric_value} {metric_unit}]"
        authors = c.get("authors", "").strip()
        lines.append(
            f"--- Claim {i} ---\n"
            f"Technology: {tech}\n"
            f"Title: {title}\n"
            f"Source: {source} ({date})\n"
            f"{'Authors: ' + authors if authors else ''}\n"
            f"Claim:{metric_str} {text[:600]}"
        )
    return "\n\n".join(lines)


async def run_cycle() -> None:
    kb = EnergyKnowledgeBase(Path("energy_intel.db"))
    claims = kb.get_recent_claims(limit=10)
    if not claims:
        print("No energy data found")
        return

    user_prompt = _format_claims(claims)
    print(f"Loaded {len(claims)} claims from energy_intel.db")
    print(f"Technologies: {list(set(c.get('technology','') for c in claims))}")
    print()

    creds = Credentials.from_env()
    cascade = ModelCascade(creds)
    result = await cascade.generate(
        tier="openrouter",
        prompt=user_prompt,
        system_prompt=SYSTEM_PROMPT,
        max_tokens=2048,
        temperature=0.7,
    )

    report_dir = Path("exports") / "energy_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_path = report_dir / f"{date_str}_energy_intel.md"
    report_path.write_text(result, encoding="utf-8")

    print(f"Report saved to {report_path}")
    print()
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate energy intelligence report.")
    parser.add_argument("--watch", action="store_true", help="Run in continuous watch mode.")
    parser.add_argument("--interval", type=int, default=28800, help="Seconds between cycles (default: 28800 = 8h).")
    args = parser.parse_args()

    if args.watch:
        print(f"Energy Intel Node en modo watch. Intervalo: {args.interval}s")
        while True:
            try:
                asyncio.run(run_cycle())
            except Exception as e:
                print(f"Error en ciclo: {e}")
            print(f"Ciclo completado. Durmiendo {args.interval}s...")
            time.sleep(args.interval)
    else:
        asyncio.run(run_cycle())
