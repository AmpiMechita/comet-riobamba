# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')

def count_tokens(text: str) -> int:
    return len(text.split()) // 4 + len(text) // 4

def benchmark_prompts():
    print("=" * 60)
    print("BENCHMARK DE TOKENS - Prompts Phase A (PRODUCCION)")
    print("=" * 60)

    from phases.phase_a_content import build_prompts

    sys_prompt, user_prompt = build_prompts("agent memory management")
    total_chars = len(sys_prompt) + len(user_prompt)
    total_tokens = count_tokens(sys_prompt) + count_tokens(user_prompt)

    print(f"\n📄 PROMPTS EN PRODUCCION (Phase A):")
    print(f"  System prompt: {len(sys_prompt)} chars, ~{count_tokens(sys_prompt)} tokens")
    print(f"  User prompt:   {len(user_prompt)} chars, ~{count_tokens(user_prompt)} tokens")
    print(f"  TOTAL:         {total_chars} chars, ~{total_tokens} tokens")
    
    costo_por_token = 0.14 / 1_000_000
    costo_por_post = total_tokens * costo_por_token
    costo_mensual = costo_por_post * 30

    print(f"\n💵 PROYECCION DE COSTO (DeepSeek $0.14/1M tokens):")
    print(f"   Costo por post:   ${costo_por_post:.6f} USD")
    print(f"   Costo mensual:    ${costo_mensual:.4f} USD (1 post/dia)")
    print(f"   Costo anual:      ${costo_mensual * 12:.4f} USD")

if __name__ == "__main__":
    benchmark_prompts()
