#!/usr/bin/env python
"""Validacion de voz con DeepSeek (V4-Pro y V4-Flash). SOLO LECTURA, no publica.

Reusa el pipeline de produccion (build_prompts calibrado + cascade.generate) pero
con tier='fallback' (DeepSeek). Confirma que thinking=disabled del path DeepSeek
evita el content vacio, y corre el gate Fix 3-6.
"""
import asyncio
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import requests
from config.credentials import Credentials
from services.model_cascade import ModelCascade
from services.editorial_policy import load_editorial_policy
import phases.phase_a_content as pac

TOPICS = [
    "context window exhaustion in long-running agents",
    "circuit breakers in agent tool-call loops",
    "provider failover and model cascade reliability",
    "silent failure modes in autonomous agent loops",
]
_TELE = os.path.join("data", "cascade_telemetry.jsonl")


def served_for(caller):
    try:
        with open(_TELE, encoding="utf-8") as f:
            for ln in reversed(f.readlines()[-60:]):
                j = json.loads(ln)
                if j.get("caller") == caller and j.get("success"):
                    return j.get("provider")
    except Exception:
        pass
    return None


def probe_model(url, key, model):
    try:
        r = requests.post(
            url,
            headers={"Authorization": "Bearer " + key, "content-type": "application/json"},
            json={"model": model, "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]},
            timeout=30,
        )
        return r.status_code, ("OK" if r.status_code == 200 else r.text[:140])
    except Exception as e:
        return None, str(e)[:140]


async def gen_and_gate(cascade, topic, policy, mode, tier, caller, label):
    sp, up = pac.build_prompts(topic, policy, variant=None, mode=mode)
    try:
        raw = await cascade.generate(
            tier=tier, prompt=up, systemprompt=sp,
            maxtokens=pac.EDITORIAL_CONFIG["max_tokens"],
            temperature=pac.EDITORIAL_CONFIG["temperature"],
            caller=caller,
        )
    except Exception as e:
        print(f"\n  ERROR generando ({label}): {e}")
        return
    served = served_for(caller)
    title, body = pac.extract_title_and_body(raw)
    title = pac._truncate_title(pac._normalize_moltbook_title(title), max_chars=100)
    post = pac._truncate_to_limit(pac._normalize_moltbook_body(body), pac.EDITORIAL_CONFIG["max_length_chars"])
    ok, reason = pac.validate_post_text(post)
    low, low_r = pac._looks_low_quality(post, policy)
    print(f"\n  PROVEEDOR: {served}  | modelo esperado: {label}")
    print(f"  content_len: {len(post)}  ({'NO VACIO ✅' if post.strip() else 'VACIO ❌'})")
    print(f"  TITULO: {title}")
    print(f"  BODY:")
    for line in (post.splitlines() or [post]):
        print(f"    {line}")
    print(f"  GATE: validate={ok} reason={reason!r} | low_quality={low} reason={low_r!r} "
          f"-> {'PASA ✅' if (ok and not low) else 'REBOTA ❌'}")


async def main():
    creds = Credentials.from_env()
    ds_url = getattr(creds, "deepseek_url", "") or "https://api.deepseek.com/v1/chat/completions"
    ds_key = getattr(creds, "deepseek_api_key", "") or ""

    print("=" * 78)
    print("1. PROBE de strings de modelo DeepSeek")
    print("=" * 78)
    flash_ok = False
    for m in ["deepseek-v4-flash", "deepseek-v4-pro"]:
        st, msg = probe_model(ds_url, ds_key, m)
        print(f"  {m:<22} -> {st}  {msg}")
        if m == "deepseek-v4-flash" and st == 200:
            flash_ok = True

    cascade = ModelCascade(credentials=Credentials.from_env())
    policy = load_editorial_policy()
    mode = pac.behavior_cfg.get("phase_a_mode", getattr(pac.POLICY, "phase_a_mode", "research"))
    fb = next((p for p in cascade.providers if p.name == "tier_fallback"), None)
    print(f"\n  tier_fallback provider: {fb and fb.name} | model actual = {getattr(fb,'model',None)}")

    print("\n" + "=" * 78)
    print("2A. DeepSeek V4-PRO (tier='fallback', model actual)")
    print("=" * 78)
    for i, t in enumerate(TOPICS, 1):
        print("\n" + "#" * 70 + f"\n# V4-PRO {i}/4 — {t}")
        await gen_and_gate(cascade, t, policy, mode, "fallback", f"dsval_pro_{i}", "deepseek-v4-pro")

    if flash_ok and fb is not None:
        print("\n" + "=" * 78)
        print("2B. DeepSeek V4-FLASH (override del model del provider tier_fallback)")
        print("=" * 78)
        fb.model = "deepseek-v4-flash"
        for i, t in enumerate(TOPICS, 1):
            print("\n" + "#" * 70 + f"\n# V4-FLASH {i}/4 — {t}")
            await gen_and_gate(cascade, t, policy, mode, "fallback", f"dsval_flash_{i}", "deepseek-v4-flash")
    else:
        print("\n[V4-Flash NO probado: el string no dio 200]")

    print("\n[deepseek voice check completo — no se publico nada]")


if __name__ == "__main__":
    asyncio.run(main())
