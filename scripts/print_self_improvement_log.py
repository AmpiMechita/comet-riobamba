#!/usr/bin/env python3
"""Print the self-improvement log in a human-readable table.

Usage:
    python -m scripts.print_self_improvement_log          # all proposals
    python -m scripts.print_self_improvement_log pending   # only pending
    python -m scripts.print_self_improvement_log applied   # only applied
"""

import sys
from services.self_improvement import list_proposals


def main():
    status_filter = None
    for a in sys.argv[1:]:
        if a.lower() in ("pending", "applied"):
            status_filter = a.lower()
            break

    proposals = list_proposals(status=status_filter)

    if not proposals:
        print("No hay propuestas de automejora." + (f" (filtro: {status_filter})" if status_filter else ""))
        return

    print(f"{'ID':<8} {'Status':<10} {'Source':<25} {'Summary'}")
    print("-" * 80)
    for p in proposals:
        pid = p.get("proposal_id", "?")
        status = p.get("status", "?")
        source = p.get("source", "?")
        summary = p.get("summary", "")
        print(f"{pid:<8} {status:<10} {source:<25} {summary[:50]}")
    print(f"\nTotal: {len(proposals)} propuesta(s)")


if __name__ == "__main__":
    main()
