"""
Configuration loader.

Reads from the same ``.env`` that comet_riobamba already uses at the project
root, plus a few repurposer-specific keys with sensible defaults.

Usage
-----
    cfg = RepurposeConfig.from_env()
    # or override per call:
    cfg = RepurposeConfig.from_env(
        project_root=Path("C:/comet-riobamba-v31"),
        platforms=["instagram", "tiktok"],
        language="es",
    )
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional
    def load_dotenv(*args, **kwargs):
        return False


# LLM providers that comet_riobamba already configures.
# Order = priority. First key that is set in .env becomes the primary,
# the rest become fallbacks in the cascade.
DEFAULT_PROVIDER_KEYS = [
    "MODEL_TIER_OPUS_API_KEY",      # Gemini via Google AI (opus tier)
    "MODEL_TIER_SONNET_API_KEY",    # Gemini via Google AI (sonnet tier)
    "GROQ_API_KEY",                 # Groq (llama-3.3-70b)
    "MODEL_TIER_OPENROUTER_API_KEY",  # OpenRouter (gpt-oss-120b:free)
    "CEREBRAS_API_KEY",             # Cerebras (llama-3.3-70b)
]

# Base URLs for each provider when used in OpenAI-compatible mode.
PROVIDER_BASE_URLS = {
    "MODEL_TIER_OPUS_API_KEY": "https://generativelanguage.googleapis.com/v1beta/openai",
    "MODEL_TIER_SONNET_API_KEY": "https://generativelanguage.googleapis.com/v1beta/openai",
    "MODEL_TIER_HAIKU_API_KEY": "https://generativelanguage.googleapis.com/v1beta/openai",
    "GROQ_API_KEY": "https://api.groq.com/openai/v1",
    "MODEL_TIER_OPENROUTER_API_KEY": "https://openrouter.ai/api/v1",
    "CEREBRAS_API_KEY": "https://api.cerebras.ai/v1",
    "OPENAI_API_KEY": "https://api.openai.com/v1",
}

# Default model per provider (matches comet_riobamba's cascade).
PROVIDER_DEFAULT_MODELS = {
    "MODEL_TIER_OPUS_API_KEY": "gemini-2.5-pro",
    "MODEL_TIER_SONNET_API_KEY": "gemini-2.5-flash",
    "MODEL_TIER_HAIKU_API_KEY": "gemini-2.5-flash-lite",
    "GROQ_API_KEY": "llama-3.3-70b-versatile",
    "MODEL_TIER_OPENROUTER_API_KEY": "openai/gpt-oss-120b:free",
    "CEREBRAS_API_KEY": "llama-3.3-70b",
    "OPENAI_API_KEY": "gpt-4o-mini",
}

ALL_PLATFORMS = [
    "instagram",
    "tiktok",
    "youtube",
    "x",
    "linkedin",
    "facebook",
]


@dataclass
class RepurposeConfig:
    """Runtime configuration for the repurposer."""

    project_root: Path = Path(".")
    output_root: Path = Path("exports/social_repurpose")
    platforms: List[str] = field(default_factory=lambda: list(ALL_PLATFORMS))
    language: str = "en"  # 'en' (default, matches agent) or 'es'

    # LLM cascade: list of (provider_key, base_url, model, api_key)
    llm_providers: List[dict] = field(default_factory=list)

    # Generation knobs
    temperature: float = 0.7
    max_tokens: int = 1200
    request_timeout: float = 60.0

    # Dedup
    dedup_db_path: Path = Path("data/repurpose_dedup.db")

    # Logging
    log_path: Path = Path("logs/repurpose.jsonl")

    # --- Publisher settings ---------------------------------------------
    publish_queue_db_path: Path = Path("data/publish_queue.db")
    kill_switch_path: Path = Path("data/KILL_SWITCH")
    publish_dry_run_default: bool = True   # safety: never auto-publish
    publish_min_gap_hours: int = 2
    linkedin_credentials: dict = field(default_factory=dict)
    twitter_credentials: dict = field(default_factory=dict)
    linkedin_optimal_slots: List[str] = field(default_factory=lambda: ["09:00", "12:00", "17:00"])
    x_optimal_slots: List[str] = field(default_factory=lambda: ["08:00", "12:00", "18:00", "21:00"])

    @classmethod
    def from_env(
        cls,
        project_root: Optional[Path] = None,
        platforms: Optional[List[str]] = None,
        language: Optional[str] = None,
        env_file: Optional[Path] = None,
    ) -> "RepurposeConfig":
        """Load config from ``.env`` plus optional CLI overrides.

        ``project_root`` defaults to the current working directory. In
        production this is ``C:\\comet-riobamba-v31``.
        """
        project_root = Path(project_root or os.getcwd()).resolve()
        env_path = env_file or (project_root / ".env")
        if env_path.exists():
            load_dotenv(env_path)

        # Build provider cascade from .env
        providers: List[dict] = []
        for key in DEFAULT_PROVIDER_KEYS:
            api_key = os.getenv(key, "").strip()
            if not api_key:
                continue
            base_url = os.getenv(f"{key}_BASE_URL", PROVIDER_BASE_URLS.get(key, "")).strip()
            model = os.getenv(f"{key}_MODEL", PROVIDER_DEFAULT_MODELS.get(key, "")).strip()
            if not base_url or not model:
                continue
            providers.append({
                "name": key,
                "base_url": base_url,
                "model": model,
                "api_key": api_key,
            })

        # Allow an explicit OPENAI_API_KEY override at the front.
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if openai_key and not any(p["name"] == "OPENAI_API_KEY" for p in providers):
            providers.insert(0, {
                "name": "OPENAI_API_KEY",
                "base_url": os.getenv("OPENAI_BASE_URL", PROVIDER_BASE_URLS["OPENAI_API_KEY"]),
                "model": os.getenv("OPENAI_MODEL", PROVIDER_DEFAULT_MODELS["OPENAI_API_KEY"]),
                "api_key": openai_key,
            })

        if not providers:
            raise RuntimeError(
                "No LLM provider configured. Set at least one of: "
                + ", ".join(DEFAULT_PROVIDER_KEYS) +
                " (or OPENAI_API_KEY) in your .env"
            )

        # LinkedIn publisher credentials (all optional until first publish).
        linkedin_creds = {
            "client_id": os.getenv("LINKEDIN_CLIENT_ID", "").strip(),
            "client_secret": os.getenv("LINKEDIN_CLIENT_SECRET", "").strip(),
            "access_token": os.getenv("LINKEDIN_ACCESS_TOKEN", "").strip(),
            "access_token_expires_at": os.getenv("LINKEDIN_ACCESS_TOKEN_EXPIRES_AT", "").strip(),
            "refresh_token": os.getenv("LINKEDIN_REFRESH_TOKEN", "").strip(),
            "refresh_token_expires_at": os.getenv("LINKEDIN_REFRESH_TOKEN_EXPIRES_AT", "").strip(),
            "person_id": os.getenv("LINKEDIN_PERSON_ID", "").strip(),
        }

        # Twitter/X publisher credentials.
        twitter_creds = {
            "api_key": os.getenv("TWITTER_API_KEY", "").strip(),
            "api_key_secret": os.getenv("TWITTER_API_KEY_SECRET", "").strip(),
            "access_token": os.getenv("TWITTER_ACCESS_TOKEN", "").strip(),
            "access_token_secret": os.getenv("TWITTER_ACCESS_TOKEN_SECRET", "").strip(),
            "bearer_token": os.getenv("TWITTER_BEARER_TOKEN", "").strip(),
        }

        def _parse_slots(name: str, default: List[str]) -> List[str]:
            raw = os.getenv(name, "").strip()
            if not raw:
                return default
            return [s.strip() for s in raw.split(",") if s.strip()]

        cfg = cls(
            project_root=project_root,
            output_root=project_root / os.getenv("REPURPOSE_OUTPUT_ROOT", "exports/social_repurpose"),
            platforms=platforms or list(ALL_PLATFORMS),
            language=language or os.getenv("REPURPOSE_LANGUAGE", "en"),
            llm_providers=providers,
            temperature=float(os.getenv("REPURPOSE_TEMPERATURE", "0.7")),
            max_tokens=int(os.getenv("REPURPOSE_MAX_TOKENS", "1200")),
            request_timeout=float(os.getenv("REPURPOSE_TIMEOUT", "60")),
            dedup_db_path=project_root / os.getenv("REPURPOSE_DEDUP_DB", "data/repurpose_dedup.db"),
            log_path=project_root / os.getenv("REPURPOSE_LOG", "logs/repurpose.jsonl"),
            publish_queue_db_path=project_root / os.getenv("PUBLISH_QUEUE_DB", "data/publish_queue.db"),
            kill_switch_path=project_root / os.getenv("PUBLISH_KILL_SWITCH", "data/KILL_SWITCH"),
            publish_dry_run_default=os.getenv("PUBLISH_DRY_RUN_DEFAULT", "1") not in ("0", "false", "False"),
            publish_min_gap_hours=int(os.getenv("PUBLISH_MIN_GAP_HOURS", "2")),
            linkedin_credentials=linkedin_creds,
            twitter_credentials=twitter_creds,
            linkedin_optimal_slots=_parse_slots("LINKEDIN_OPTIMAL_SLOTS", ["09:00", "12:00", "17:00"]),
            x_optimal_slots=_parse_slots("X_OPTIMAL_SLOTS", ["08:00", "12:00", "18:00", "21:00"]),
        )
        return cfg

    def resolve_output(self, date_str: str, slug: str) -> Path:
        """Compute the per-item output directory."""
        return self.output_root / date_str / slug

    def ensure_dirs(self) -> None:
        """Create output, dedup, and log directories."""
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.dedup_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
