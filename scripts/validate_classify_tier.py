# -*- coding: utf-8 -*-
"""
Validacion del tier classify vs flash (paridad de decision).

Mide el % de acuerdo entre classify (gratis) y flash (pago) sobre las mismas
entradas, para decidir si la migracion es segura:
  - value_log: ~30 casos reales (clasificacion_valor).
  - claim_checker: ~20 claims reales (check_claim on_topic — puede BLOQUEAR
    publicaciones; si el acuerdo es <80% aca, el claim_checker NO migra).

Uso: python -m scripts.validate_classify_tier
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

from config.credentials import Credentials
from services.model_cascade import ModelCascade

VALUE_LOG_PATH = Path("data/value_log.jsonl")
CLAIMS_PATH = Path("data/claims_tracker.json")
SAMPLE_VALUE = 30
SAMPLE_CLAIMS = 20


async def classify_value(llm, tier, post, comment, reply):
    """Replica _classify_and_log_value y devuelve la clasificacion_valor."""
    from prompts.value_classifier import build_classifier_prompt
    system_prompt, user_prompt = build_classifier_prompt(post=post, comment=comment, reply=reply)
    raw = await llm.generate(
        tier=tier, prompt=user_prompt,
        system_prompt=f"Always respond in English.\n\n{system_prompt}",
        max_tokens=300, temperature=0.3,
    )
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        data = json.loads(raw)
        return data.get("clasificacion_valor", "baja_relevancia")
    except (json.JSONDecodeError, ValueError):
        return None


async def check_claim_value(llm, tier, claim_text):
    """Replica check_claim y devuelve on_topic."""
    from services.claim_checker import CHECK_CLAIM_SYSTEM
    prompt = (
        f"CENTRAL CLAIM:\n{claim_text}\n\n"
        f"REPLY MUST ADDRESS:\n{claim_text}\n\n"
        f"REPLY DRAFT:\n{claim_text}"
    )
    raw = await llm.generate(
        tier=tier, prompt=prompt, system_prompt=CHECK_CLAIM_SYSTEM,
        max_tokens=400, temperature=0.1,
    )
    try:
        cleaned = (raw or "").strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        result = json.loads(cleaned)
        return bool(result.get("on_topic", True))
    except (json.JSONDecodeError, ValueError):
        return None


async def main() -> int:
    cascade = ModelCascade(credentials=Credentials.from_env())

    # ── value_log ──
    value_cases = []
    if VALUE_LOG_PATH.exists():
        for line in VALUE_LOG_PATH.read_text(encoding="utf-8").splitlines()[: SAMPLE_VALUE * 3]:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("resumen_problema") and rec.get("resumen_solucion"):
                value_cases.append(rec)
            if len(value_cases) >= SAMPLE_VALUE:
                break

    value_agree = value_total = 0
    for i, rec in enumerate(value_cases, 1):
        post = f"Post ID: {rec.get('post_id', '')}\nTema: {rec.get('tema', '')}"
        comment = rec.get("resumen_problema", "")
        reply = rec.get("resumen_solucion", "")
        v_flash = await classify_value(cascade, "flash", post, comment, reply)
        v_class = await classify_value(cascade, "classify", post, comment, reply)
        if v_flash is None or v_class is None:
            print(f"[value {i:2d}] flash={v_flash} classify={v_class} -> SIN DATO")
            continue
        value_total += 1
        agree = v_flash == v_class
        value_agree += agree
        print(f"[value {i:2d}] flash={v_flash} classify={v_class} -> {'ACUERDO' if agree else 'DESACUERDO'}")

    # ── claim_checker ──
    claim_cases = []
    if CLAIMS_PATH.exists():
        data = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
        claim_cases = [c.get("text", "") for c in data.get("claims", []) if c.get("text")][: SAMPLE_CLAIMS]

    claim_agree = claim_total = 0
    for i, claim_text in enumerate(claim_cases, 1):
        c_flash = await check_claim_value(cascade, "flash", claim_text)
        c_class = await check_claim_value(cascade, "classify", claim_text)
        if c_flash is None or c_class is None:
            print(f"[claim {i:2d}] flash={c_flash} classify={c_class} -> SIN DATO")
            continue
        claim_total += 1
        agree = c_flash == c_class
        claim_agree += agree
        print(f"[claim {i:2d}] flash={c_flash} classify={c_class} -> {'ACUERDO' if agree else 'DESACUERDO'}")

    print("=" * 60)
    if value_total:
        pct = value_agree / value_total * 100
        print(f"value_log: {value_agree}/{value_total} acuerdo ({pct:.1f}%)")
    else:
        print("value_log: sin casos")
    if claim_total:
        pct = claim_agree / claim_total * 100
        verdict = "MIGRAR claim_checker" if pct >= 80 else "NO MIGRAR claim_checker (queda en flash)"
        print(f"claim_checker: {claim_agree}/{claim_total} acuerdo ({pct:.1f}%) -> {verdict}")
    else:
        print("claim_checker: sin casos")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
