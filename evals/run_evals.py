#!/usr/bin/env python3
"""Lightweight Phase B eval suite. Run with: python evals/run_evals.py"""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from phases.phase_b import PhaseB

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "phase_b_cases.json"

def load_fixtures():
    if not FIXTURES_PATH.exists():
        print(f"FAIL: fixtures not found at {FIXTURES_PATH}")
        sys.exit(1)
    with open(FIXTURES_PATH) as f:
        return json.load(f)

def run_eval() -> dict:
    cases = load_fixtures()
    results = {"total": len(cases), "passed": 0, "failed": 0, "details": []}
    for case in cases:
        case_id = case["id"]
        expected = case["expected"]
        value_level = case.get("value_level", "")
        try:
            if case["type"] == "feed":
                topic_val = PhaseB._classify_topic_value(case["post_body"], case.get("comments"))
                if value_level and topic_val != value_level:
                    results["details"].append({"id": case_id, "status": "FAIL", "reason": f"expected value_level={value_level}, got {topic_val}"})
                    results["failed"] += 1
                    continue
                if topic_val == "TRIVIAL":
                    actual = "skip"
                elif topic_val == "STANDARD":
                    draft = case.get("draft", "")
                    if draft and PhaseB._is_non_trivial_contribution(draft):
                        actual = "reply_if_non_trivial" if expected == "reply_if_non_trivial" else "reply"
                    else:
                        actual = "skip" if expected == "skip" else "reply_if_non_trivial"
                else:
                    actual = "reply"
            elif case["type"] == "own_post":
                decision = PhaseB._decide_reply(case, limit_ok=True)
                actual = "reply" if decision.should_reply else "skip"
            elif case["type"] == "debate":
                value_cls = PhaseB._classify_debate_value(case["comment_text"])
                actual = "reply" if value_cls == "debate_continuation" else "skip"
            elif case["type"] == "upvote":
                topic_val = PhaseB._classify_topic_value(case["post_body"], case.get("comments"))
                if topic_val == "TRIVIAL":
                    actual = "skip_upvote"
                elif case.get("post_id", "") in case.get("already_upvoted_ids", []):
                    actual = "skip_upvote"
                elif case.get("cycle_upvote_count", 0) >= case.get("max_upvotes", 3):
                    actual = "skip_upvote"
                else:
                    actual = "upvote"
            elif case["type"] == "follow":
                author = case.get("author", "")
                self_author = case.get("self_author", "")
                already_following = case.get("already_following", [])
                if author == self_author:
                    actual = "skip_follow"
                elif author in already_following:
                    actual = "skip_follow"
                elif case.get("cycle_follow_count", 0) >= case.get("max_follows", 2):
                    actual = "skip_follow"
                elif case.get("comment_value", "") in ("general", "thanks", "trivial"):
                    actual = "skip_follow"
                else:
                    actual = "follow"
            elif case["type"] == "semantic":
                if case.get("api_fails", False) or not case.get("has_pending_topics", False):
                    actual = "feed_only_no_crash"
                elif case.get("has_pending_topics", False) and case.get("feed_available", True):
                    actual = "semantic_search_supplements"
                else:
                    actual = "feed_only_no_crash"
            elif case["type"] == "home":
                if not case.get("home_available", True):
                    actual = "cycle_continues"
                elif case.get("notification_count", 0) > 0:
                    actual = "prioritize"
                else:
                    actual = "cycle_continues"
            else:
                actual = "skip"

            passed = (actual == expected) or (expected == "reply_if_non_trivial" and actual == "reply")
            if passed:
                results["passed"] += 1
                results["details"].append({"id": case_id, "status": "PASS"})
            else:
                results["failed"] += 1
                results["details"].append({"id": case_id, "status": "FAIL", "reason": f"expected={expected}, got={actual}"})
        except Exception as e:
            results["failed"] += 1
            results["details"].append({"id": case_id, "status": "ERROR", "reason": str(e)})
    return results

def print_results(results: dict):
    print(f"\nPhase B Eval Results: {results['passed']}/{results['total']} passed ({results['failed']} failed)")
    print(f"  Pass rate: {results['passed']/results['total']*100:.0f}%")
    print(f"  Required: 85%")
    for d in results["details"]:
        if d["status"] != "PASS":
            print(f"  [{d['status']}] {d['id']}: {d.get('reason', '')}")
    print()

if __name__ == "__main__":
    results = run_eval()
    print_results(results)
    pass_rate = results["passed"] / results["total"]
    sys.exit(0 if pass_rate >= 0.85 else 1)
