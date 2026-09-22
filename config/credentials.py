from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


def _get_secret(name: str, default: str = "") -> str:
    """Read secret with three-layer fallback.

    Layer 1 (preferred): Windows DPAPI machine-scoped store
        (services.secret_store) -- works for SYSTEM services like NSSM.
    Layer 2: Windows Credential Manager via keyring -- works for
        interactive user (rafae) but NOT for SYSTEM.
    Layer 3: Environment variable -- dev/CI fallback.

    Set COMET_DISABLE_KEYRING=1 to force layer 3 only (tests).
    """
    if os.getenv("COMET_DISABLE_KEYRING", "0") == "1":
        return os.getenv(name.upper(), default)
    try:
        from services.secret_store import get_secret as _ss_get
        v = _ss_get(name)
        if v:
            return v
    except Exception:
        pass
    try:
        import keyring
        v = keyring.get_password("comet_riobamba", name)
        if v:
            return v
    except Exception:
        pass
    return os.getenv(name.upper(), default)


@dataclass
class TierConfig:
    url: str
    model: str
    api_key: str
    timeout_seconds: int = 60


@dataclass
class Credentials:
    moltbook_base_url: str
    moltbook_api_key: str

    ollama_url: str
    ollama_model: str
    ollama_timeout: int

    # DeepSeek tiers only
    deepseek_api_key: str = ""
    deepseek_url: str = ""
    deepseek_model: str = ""
    deepseek_timeout: int = 90

    # DeepSeek Pro (tier_pro / tier_fallback)
    deepseek_pro_api_key: str = ""
    deepseek_pro_url: str = ""
    deepseek_pro_model: str = ""
    deepseek_priority_model: str = ""

    # DeepSeek Flash
    deepseek_flash_api_key: str = ""
    deepseek_flash_url: str = ""
    deepseek_flash_model: str = ""

    cerebras_api_key: str = ""
    cerebras_url: str = ""
    cerebras_model: str = ""
    cerebras_timeout: int = 30

    ollama_cloud_model: str = ""
    ollama_cloud_timeout: int = 120

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_alerts_enabled: bool = False

    @classmethod
    def from_env(cls) -> Credentials:
        load_dotenv(override=True)

        return cls(
            moltbook_base_url=os.getenv("MOLTBOOK_BASE_URL", "https://www.moltbook.com/api/v1"),
            moltbook_api_key=_get_secret("moltbook_api_key", ""),
            ollama_url=os.getenv("OLLAMA_OPENAI_URL", "http://localhost:11434/v1/chat/completions"),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
            ollama_timeout=int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
            deepseek_url=os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions").strip(),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip(),
            deepseek_timeout=int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "90")),
            deepseek_pro_api_key=os.getenv("DEEPSEEK_PRO_API_KEY", "").strip(),
            deepseek_pro_url=os.getenv("DEEPSEEK_PRO_URL", "https://api.deepseek.com/v1/chat/completions").strip(),
            deepseek_pro_model=os.getenv("DEEPSEEK_PRO_MODEL", "deepseek-v4-pro").strip(),
            deepseek_priority_model=os.getenv("DEEPSEEK_PRIORITY_MODEL", "deepseek-v4-pro").strip(),
            deepseek_flash_api_key=os.getenv("DEEPSEEK_FLASH_API_KEY", "").strip(),
            deepseek_flash_url=os.getenv("DEEPSEEK_FLASH_URL", "https://api.deepseek.com/v1/chat/completions").strip(),
            deepseek_flash_model=os.getenv("DEEPSEEK_FLASH_MODEL", "deepseek-v4-flash").strip(),
            cerebras_api_key=os.getenv("CEREBRAS_API_KEY", ""),
            cerebras_url=os.getenv("CEREBRAS_API_URL", "https://api.cerebras.ai/v1/chat/completions"),
            cerebras_model=os.getenv("CEREBRAS_MODEL", "llama-3-8b"),
            cerebras_timeout=int(os.getenv("CEREBRAS_TIMEOUT_SECONDS", "30")),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            telegram_alerts_enabled=bool(int(os.getenv("TELEGRAM_ALERTS_ENABLED", 0))),
        )