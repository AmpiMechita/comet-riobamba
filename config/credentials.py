from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


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

    tier_opus: Optional[TierConfig] = None
    tier_sonnet: Optional[TierConfig] = None
    tier_haiku: Optional[TierConfig] = None
    tier_openrouter: Optional[TierConfig] = None

    cerebras_api_key: str = ""
    cerebras_url: str = ""
    cerebras_model: str = ""
    cerebras_timeout: int = 30

    groq_api_key: str = ""
    groq_url: str = ""
    groq_model: str = ""
    groq_timeout: int = 30

    ollama_cloud_model: str = ""
    ollama_cloud_timeout: int = 120

    anthropic_api_key: str = ""
    anthropic_url: str = ""
    anthropic_model: str = ""
    anthropic_timeout: int = 120

    deepseek_api_key: str = ""
    deepseek_url: str = ""
    deepseek_model: str = ""
    deepseek_timeout: int = 90

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_alerts_enabled: bool = False

    @classmethod
    def from_env(cls) -> Credentials:
        load_dotenv()

        def _tier(name: str, default_timeout: int = 60) -> Optional[TierConfig]:
            url = os.getenv(f"MODEL_TIER_{name}_URL", "").strip()
            model = os.getenv(f"MODEL_TIER_{name}_MODEL", "").strip()
            api_key = os.getenv(f"MODEL_TIER_{name}_API_KEY", "").strip()
            timeout = int(os.getenv(f"MODEL_TIER_{name}_TIMEOUT_SECONDS", str(default_timeout)))
            if url and model:
                return TierConfig(url=url, model=model, api_key=api_key, timeout_seconds=timeout)
            return None

        return cls(
            moltbook_base_url=os.getenv("MOLTBOOK_BASE_URL", "https://www.moltbook.com/api/v1"),
            moltbook_api_key=os.getenv("MOLTBOOK_API_KEY", ""),
            ollama_url=os.getenv("OLLAMA_OPENAI_URL", "http://localhost:11434/v1/chat/completions"),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
            ollama_timeout=int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")),
            tier_opus=_tier("OPUS", 120),
            tier_sonnet=_tier("SONNET", 60),
            tier_haiku=_tier("HAIKU", 30),
            tier_openrouter=_tier("OPENROUTER", 60),
            cerebras_api_key=os.getenv("CEREBRAS_API_KEY", ""),
            cerebras_url=os.getenv("CEREBRAS_API_URL", "https://api.cerebras.ai/v1/chat/completions"),
            cerebras_model=os.getenv("CEREBRAS_MODEL", "llama-3.3-70b"),
            cerebras_timeout=int(os.getenv("CEREBRAS_TIMEOUT_SECONDS", "30")),
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            groq_url=os.getenv("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions"),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            groq_timeout=int(os.getenv("GROQ_TIMEOUT_SECONDS", "30")),
            ollama_cloud_model=os.getenv("OLLAMA_CLOUD_MODEL", ""),
            ollama_cloud_timeout=int(os.getenv("OLLAMA_CLOUD_TIMEOUT_SECONDS", "120")),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
            anthropic_url=os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages").strip(),
            anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5").strip(),
            anthropic_timeout=int(os.getenv("ANTHROPIC_TIMEOUT_SECONDS", "120")),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
            deepseek_url=os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions").strip(),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro").strip(),
            deepseek_timeout=int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "90")),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            telegram_alerts_enabled=bool(int(os.getenv("TELEGRAM_ALERTS_ENABLED", 0))),
        )
