"""
Mock LLM client used by tests and ``--dry-run``-style local smoke tests.

Returns canned JSON payloads per platform so we can verify the pipeline
end-to-end without spending real API quota.
"""

from __future__ import annotations

from typing import Dict

from .llm_client import LLMResponse


_CANNED: Dict[str, dict] = {
    "instagram": {
        "caption": "Your agent's 'health score' might be lying to you. A high success rate looks identical whether an endpoint is rate-limiting you or the network path is silently broken. Here is how to tell them apart.",
        "carousel_slides": [
            "Slide 1 — The trap: success rate looks healthy at 99.7%.",
            "Slide 2 — But TCP resets are spiking every 6 minutes.",
            "Slide 3 — Two failure modes, identical dashboard, opposite fixes.",
            "Slide 4 — Pair success rate with fast-changing signals.",
            "Slide 5 — ICMP reachability tells you the path is alive.",
            "Slide 6 — Reset bursts tell you the endpoint is unhappy.",
            "Slide 7 — Without both, you are flying blind.",
        ],
        "hashtags": ["AIagents", "agentobservability", "MLOps", "LLM", "SRE", "reliability", "monitoring", "agentengineering"],
        "cta": "Save this for the next time your agent silently degrades.",
    },
    "tiktok": {
        "hook": "Your AI agent's health score is lying to you. Here's why.",
        "script": [
            "Beat 1 — On screen: '99.7% success rate'. Voice: 'Looks great, right? Wrong.'",
            "Beat 2 — On screen: 'TCP resets every 6 min'. Voice: 'The endpoint is silently choking.'",
            "Beat 3 — On screen: 'Same dashboard, opposite fix'. Voice: 'Rate limit vs network path. Both look identical.'",
            "Beat 4 — On screen: 'Pair success rate + fast signals'. Voice: 'ICMP reachability + reset bursts. That's the unlock.'",
        ],
        "duration_seconds": 38,
        "voiceover_tone": "Direct, technical, no hype.",
        "hashtags": ["AIagents", "observability", "MLOps"],
    },
    "youtube": {
        "shorts_script": [
            "Beat 1 (0-3s) — Hook: 'Your agent's health score is lying.'",
            "Beat 2 (3-12s) — '99.7% success rate hides silent back-pressure.'",
            "Beat 3 (12-25s) — 'Pair success rate with TCP resets + ICMP.'",
            "Beat 4 (25-40s) — 'Otherwise you are flying blind. Comment: what signal do you trust?'",
        ],
        "shorts_duration_seconds": 40,
        "long_form_title": "Why your agent's health score is a lie (and what to measure instead)",
        "long_form_outline": [
            {"chapter": "01 — The dashboard lie", "one_liner": "Why success rate alone is dangerous."},
            {"chapter": "02 — Silent back-pressure", "one_liner": "Two failure modes, identical numbers."},
            {"chapter": "03 — Fast-changing signals", "one_liner": "TCP resets, ICMP, retry storms."},
            {"chapter": "04 — A reference health formula", "one_liner": "Concrete weights you can copy."},
            {"chapter": "05 — Implementation in 50 lines", "one_liner": "Python snippet using psutil + requests."},
            {"chapter": "06 — What still doesn't work", "one_liner": "Honest gaps and open questions."},
        ],
        "description": "Most agent health scores are success-rate in disguise. We break down why that hides silent back-pressure, and show a reference formula mixing success rate with fast-changing transport signals. Code snippet in the description below. Timestamps: 00:00 the dashboard lie 02:14 silent back-pressure 06:40 fast signals 11:20 reference formula 18:05 implementation.",
        "tags": ["AI agents", "observability", "MLOps"],
    },
    "x": {
        "tweets": [
            "Your agent's 'health score' is lying to you. A 99.7% success rate looks identical whether the endpoint is rate-limiting you or the network path is silently broken. Same dashboard, opposite fix. ->",
            "The trick is to pair success rate with fast-changing signals. TCP reset bursts mean the endpoint is unhappy. ICMP reachability means the path is alive. Both are cheap to collect. ->",
            "Without both signals you are flying blind. Most 'agent observability' dashboards I see are success rate plus p99 latency. That is a control panel with two gauges and no warning lights. ->",
            "Open question: what is the minimum viable signal set for an agent that calls 12 tools across 4 providers, with one tool going to a flaky partner API? Reply with your stack.",
        ],
        "thread_topic": "Agent health scores are a lie without fast-changing signals",
    },
    "linkedin": {
        "post": "Your agent's 'health score' is probably lying to you.\n\nA 99.7% success rate looks identical whether the endpoint is rate-limiting you or the network path is silently broken. The dashboard says green. The reality is silent back-pressure. The fix for one makes the other worse.\n\nMost agent observability stacks I see are success rate plus p99 latency. Two gauges and no warning lights. That is a control panel for a system that fails slowly and quietly.\n\nThe unlock is to pair success rate with fast-changing transport signals: TCP reset bursts, ICMP reachability, retry storms. They are cheap to collect, they move on the order of seconds, and they differentiate between 'endpoint unhappy' and 'path dead' -- which success rate alone never will.\n\nOpen research question: what is the minimum viable signal set for an agent that calls 12 tools across 4 providers, with one tool hitting a flaky partner API? I don't think we have a canonical answer yet.",
        "hashtags": ["AIagents", "AgentObservability", "MLOps"],
    },
    "facebook": {
        "post": "Your AI agent's 'health score' is probably lying to you.\n\nA 99.7% success rate looks identical whether an endpoint is rate-limiting you or the network path is silently broken. Same dashboard. Opposite fix. Most observability stacks I see are success rate plus p99 latency -- two gauges, no warning lights.\n\nThe unlock is pairing success rate with fast-changing transport signals: TCP resets, ICMP reachability, retry storms. Cheap to collect, differentiate 'endpoint unhappy' from 'path dead'.\n\nWho is building agent observability dashboards right now? Curious what signals you trust.",
        "hashtags": ["AIagents", "MLOps"],
        "question_to_audience": "What signals do you trust for agent health beyond success rate?",
    },
}


class MockLLMClient:
    """Drop-in replacement for LLMClient that returns canned payloads."""

    def __init__(self, *_, **__):
        pass

    def chat(self, system: str, user: str):
        # Sniff which platform the prompt targets by reading the user prompt.
        platform = None
        for p in _CANNED:
            label_map = {
                "x": "X / TWITTER",
                "youtube": "YOUTUBE",
                "instagram": "INSTAGRAM",
                "tiktok": "TIKTOK",
                "linkedin": "LINKEDIN",
                "facebook": "FACEBOOK",
            }
            if label_map[p] in user.upper():
                platform = p
                break
        if platform is None:
            raise ValueError("Could not detect target platform from prompt")
        import json
        from .llm_client import LLMResponse
        return LLMResponse(
            text=json.dumps(_CANNED[platform], ensure_ascii=False),
            provider="mock",
            model="mock-1",
            elapsed_s=0.01,
            raw={"canned": True, "platform": platform},
        )
