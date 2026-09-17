#!/usr/bin/env python3
"""
Model Router con Fallback para comet-riobamba-v31
"""

import os
import requests
import json
import time
from pathlib import Path
from dotenv import load_dotenv

# Usar directorio de trabajo actual (root del proyecto)
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

# Cargar .env
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

# Configuración de proveedores
PROVIDERS = {
    "groq": {
        "url": os.getenv("GROQ_URL", "https://api.groq.com/openai/v1/chat/completions"),
        "api_key": os.getenv("GROQ_API_KEY"),
        "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
        "timeout": int(os.getenv("GROQ_TIMEOUT_SECONDS", 30)),
        "enabled": os.getenv("GROQ_ENABLED", "true").lower() == "true",
    },
    "openrouter": {
        "url": os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions"),
        "api_key": os.getenv("OPENROUTER_API_KEY"),
        "model": os.getenv("OPENROUTER_MODEL", "liquid/lfm-2.5-2.6b:free"),
        "timeout": int(os.getenv("OPENROUTER_TIMEOUT_SECONDS", 60)),
        "enabled": os.getenv("OPENROUTER_ENABLED", "true").lower() == "true",
    },
    "deepseek": {
        "url": os.getenv("DEEPSEEK_URL", "https://api.deepseek.com/v1/chat/completions"),
        "api_key": os.getenv("DEEPSEEK_API_KEY"),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "timeout": int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", 90)),
        "enabled": True,
    },
}

FALLBACK_ORDER = ["groq", "openrouter", "deepseek"]


def call_model_with_fallback(prompt: str, system_prompt: str = None, max_tokens: int = 512, temperature: float = 0.1):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    for provider_name in FALLBACK_ORDER:
        provider = PROVIDERS[provider_name]
        if not provider.get("enabled", True) or not provider['api_key']:
            continue
        try:
            payload = {
                "model": provider["model"],
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            headers = {"Authorization": f"Bearer {provider['api_key']}", "Content-Type": "application/json"}
            response = requests.post(provider["url"], headers=headers, json=payload, timeout=provider["timeout"])
            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                tokens_used = data.get("usage", {}).get("total_tokens", 0)
                return {"success": True, "provider": provider_name, "model": provider["model"], "content": content, "tokens_used": tokens_used}
            elif response.status_code == 429:
                continue
            else:
                continue
        except:
            continue
    
    return {"success": False, "provider": None, "model": None, "content": None, "tokens_used": 0, "error": "All providers failed"}


if __name__ == "__main__":
    print("=" * 80)
    print("TEST DE MODEL ROUTER CON FALLBACK")
    print("=" * 80)
    
    print("\n[Test 1] Classify simple:")
    result = call_model_with_fallback(
        prompt="Clasifica este post: 'Acabo de publicar un análisis sobre LLVM IR'",
        system_prompt="Responde solo: OK",
        max_tokens=50,
        temperature=0.1
    )
    
    if result["success"]:
        print(f"✅ ÉXITO: {result['provider']} ({result['model']})")
        print(f"   Tokens: {result['tokens_used']}")
        print(f"   Contenido: {result['content'][:100]}")
    else:
        print(f"❌ FALLÓ: {result.get('error', 'Unknown error')}")
    
    print("\n" + "=" * 80)
    print("FIN DEL TEST")
    print("=" * 80)