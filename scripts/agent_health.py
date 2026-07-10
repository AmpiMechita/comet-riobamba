#!/usr/bin/env python3
"""
CLI: COMET-RIOBAMBA Agent Health Report

Usage:
    python scripts/agent_health.py
    python scripts/agent_health.py path/to/data
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path
_proj_root = Path(__file__).resolve().parent.parent
if str(_proj_root) not in sys.path:
    sys.path.insert(0, str(_proj_root))

from core.agent_health import generate_health_report


def _fmt(val: Any, decimals: int = 2) -> str:
    if isinstance(val, float):
        return f"{val:.{decimals}f}"
    return str(val)


def print_report(data_dir: Path) -> None:
    report = generate_health_report(data_dir)
    ts = report["timestamp"][:19].replace("T", " ")

    sep = "=" * 66

    print()
    print(sep)
    print("   COMET-RIOBAMBA AGENT HEALTH REPORT".center(66))
    print(sep)
    print(f"   Timestamp: {ts}")
    print()

    # ── Self-Monitor ────────────────────────────────────────────
    sm = report["self_monitor"]
    print("   [SELF-MONITOR]")
    if sm.get("insufficient_data", True):
        print("      Insufficient data")
    else:
        pct = sm["intervention_pct"]
        print(f"      Interventions triggered: {sm['intervention_count']}/{sm['total']} total diagnoses ({pct}%)")
        print(f"      Trend: {sm['trend']}")
        if sm["last_intervention_types"]:
            print(f"      Last 3 interventions: {sm['last_intervention_types']}")
    print()

    # ── Topic Diversity ─────────────────────────────────────────
    td = report["topic_diversity"]
    print("   [TOPIC DIVERSITY]")
    if td.get("insufficient_data", True):
        print("      Insufficient data")
    else:
        bal = td.get("cluster_balance", {})
        print(f"      Cluster balance: {bal}")
        print(f"      Least used cluster: {td['least_used_cluster']}")
        print(f"      Active cooldowns: {td['active_cooldowns']}/{td['total_topics']}")
    print()

    # ── Claims Tracker ──────────────────────────────────────────
    cl = report["claims"]
    print("   [CLAIMS TRACKER]")
    if cl.get("insufficient_data", True):
        print("      Insufficient data")
    else:
        stages = cl.get("evolution_stages", {})
        initial = stages.get("initial", 0)
        refined = stages.get("refined", 0)
        established = stages.get("established", 0)
        print(f"      Total claims: {cl['total']}")
        print(f"      Evolution: {initial} initial | {refined} refined | {established} established")
        print(f"      Repetition rate (last 10): {cl['repetition_rate']}%")
        top = cl.get("top_reinforced", [])
        if top:
            print("      Top reinforced:")
            for i, (text, count) in enumerate(top, 1):
                preview = text[:60]
                print(f"        {i}. \"{preview}\" ({count}x)")
    print()

    # ── Dual Scoring ────────────────────────────────────────────
    ds = report["dual_scoring"]
    print("   [DUAL SCORING] (Last 20 entries)")
    if ds.get("insufficient_data", True):
        print("      Insufficient data")
    else:
        print(f"      Avg Research Value: {ds['avg_research_value']}")
        print(f"      Avg Engagement: {ds['avg_engagement']}")
        types_str = ", ".join(f"{k}: {v}%" for k, v in ds.get("type_distribution", {}).items())
        print(f"      Content Types: {types_str}")
        ratio = ds["metric_proposal_ratio"]
        flag = "HIGH" if ratio > 0.4 else "HEALTHY"
        print(f"      Metric Proposal Ratio: {ratio} [{flag}]")
    print()

    # ── Overall ─────────────────────────────────────────────────
    status = report["overall_status"]
    icon = {"HEALTHY": "\U0001F7E2", "ATTENTION": "\U0001F7E1", "INTERVENTION NEEDED": "\U0001F534"}
    print(sep)
    print(f"   Overall Status: {icon.get(status, '')} {status}".center(66))
    print(sep)
    print()


def main() -> None:
    if len(sys.argv) > 1:
        data_dir = Path(sys.argv[1])
    else:
        data_dir = Path("C:/comet-riobamba-v31")
    data_dir = data_dir.resolve()
    if not data_dir.exists():
        print(f"Data directory not found: {data_dir}")
        sys.exit(1)
    print_report(data_dir)


if __name__ == "__main__":
    main()
