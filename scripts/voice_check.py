#!/usr/bin/env python
"""Harness de validacion de VOZ — SOLO LECTURA, no publica ni commitea.

Usa el EDITORIAL_CONFIG NUEVO del working tree. Replica el camino de produccion:
  build_prompts(topic, policy, variant, mode) -> cascade.generate(tier='premium')
  -> extract_title_and_body -> normalizadores -> validate_post_text + _looks_low_quality
"""
import asyncio
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config.credentials import Credentials
from services.model_cascade import ModelCascade
from services.editorial_policy import load_editorial_policy
import phases.phase_a_content as pac

TOPICS = [
    "context window exhaustion in long-running agents",
    "circuit breakers in agent tool-call loops",
    "provider failover and model cascade reliability",
    "silent failure modes in autonomous agent loops",
    "agent memory management under load",
    "retry logic and backoff in tool-calling agents",
]

_TELEMETRY = os.path.join("data", "cascade_telemetry.jsonl")


def _last_premium_provider():
    try:
        with open(_TELEMETRY, encoding="utf-8") as f:
            lines = f.readlines()
        for ln in reversed(lines[-8:]):
            j = json.loads(ln)
            if str(j.get("tier", "")).endswith("premium") or j.get("tier") == "premium":
                return f"{j.get('provider')} (tier={j.get('tier')}, success={j.get('success')})"
    except Exception as e:
        return f"(telemetria no legible: {e})"
    return "(sin entrada premium en telemetria)"


async def generate_one(cascade, topic, policy, mode):
    system_prompt, user_prompt = pac.build_prompts(topic, policy, variant=None, mode=mode)
    raw = await cascade.generate(
        tier="premium",
        prompt=user_prompt,
        systemprompt=system_prompt,
        maxtokens=pac.EDITORIAL_CONFIG["max_tokens"],
        temperature=pac.EDITORIAL_CONFIG["temperature"],
    )
    return system_prompt, raw


async def main():
    cascade = ModelCascade(credentials=Credentials.from_env())
    policy = load_editorial_policy()
    mode = pac.behavior_cfg.get("phase_a_mode", getattr(pac.POLICY, "phase_a_mode", "research"))

    print("=" * 80)
    print("VOICE CHECK — EDITORIAL_CONFIG del working tree (config NUEVO)")
    print("=" * 80)
    print(f"temperature={pac.EDITORIAL_CONFIG['temperature']}  mode={mode}  variant=None")
    print(f"max_tokens={pac.EDITORIAL_CONFIG['max_tokens']}")

    # Mostrar UNA vez el system prompt para confirmar que el mission/core_principles
    # nuevos realmente entran al modelo.
    sp0, _ = pac.build_prompts(TOPICS[0], policy, variant=None, mode=mode)
    print("\n--- SYSTEM PROMPT efectivo (confirmando que el config nuevo se usa) ---")
    print(sp0)
    print("-" * 80)

    for i, topic in enumerate(TOPICS, 1):
        print("\n" + "#" * 80)
        print(f"# POST {i}/6 — topic: {topic}")
        print("#" * 80)
        try:
            _, raw = await generate_one(cascade, topic, policy, mode)
        except Exception as e:
            print(f"  ERROR generando: {e}")
            continue

        provider = _last_premium_provider()

        title, body = pac.extract_title_and_body(raw)
        title = pac._normalize_moltbook_title(title)
        title = pac._truncate_title(title, max_chars=100)
        body = pac._normalize_moltbook_body(body)
        post_text = pac._truncate_to_limit(body, pac.EDITORIAL_CONFIG["max_length_chars"])

        is_valid, reason = pac.validate_post_text(post_text)
        low, low_reason = pac._looks_low_quality(post_text, policy)
        try:
            similar = pac.is_similar_to_recent(post_text)
        except Exception:
            similar = "(n/a)"

        print(f"\nPROVEEDOR: {provider}")
        print(f"\nTITULO:\n  {title}")
        print(f"\nBODY ({len(post_text)} chars):")
        for line in post_text.splitlines() or [post_text]:
            print(f"  {line}")
        print("\nGATE (el que arreglamos Fix 3-6):")
        print(f"  validate_post_text() -> valido={is_valid} reason={reason!r}")
        print(f"  _looks_low_quality()  -> low_quality={low} reason={low_reason!r}")
        print(f"  is_similar_to_recent() -> {similar}  (extra, no pedido)")
        verdict = "PASA EL GATE ✅" if (is_valid and not low) else "REBOTA ❌"
        print(f"  >>> {verdict}")

    print("\n" + "=" * 80)
    print("[voice_check completo — no se publico nada, sin commit]")


if __name__ == "__main__":
    asyncio.run(main())
