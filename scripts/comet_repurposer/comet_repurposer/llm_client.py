"""
Minimal OpenAI-compatible LLM client with provider cascade.

Matches the cascade pattern comet_riobamba already uses in
``services/model_cascade.py``: try primary provider, fall back to others
on transient errors. No SDK dependency - just ``requests`` so it works
with Gemini/Groq/OpenRouter/Cerebras/OpenAI/Ollama without any extra
install.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import List, Optional

import requests


class LLMCallError(RuntimeError):
    """Raised when every provider in the cascade failed."""


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    elapsed_s: float
    raw: dict


class LLMClient:
    """OpenAI-compatible chat completions client with cascade.

    Parameters
    ----------
    providers : list[dict]
        Ordered list of provider dicts with keys:
        ``name``, ``base_url``, ``model``, ``api_key``.
    temperature : float
    max_tokens : int
    timeout : float
        Per-request timeout in seconds.
    max_retries : int
        Retries per provider before falling back to the next.
    """

    def __init__(
        self,
        providers: List[dict],
        temperature: float = 0.7,
        max_tokens: int = 1200,
        timeout: float = 60.0,
        max_retries: int = 1,
    ) -> None:
        if not providers:
            raise ValueError("At least one LLM provider is required.")
        self.providers = providers
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries

    def chat(self, system: str, user: str) -> LLMResponse:
        """Call ``/chat/completions`` on each provider until one succeeds."""
        last_error: Optional[Exception] = None
        for provider in self.providers:
            for attempt in range(self.max_retries + 1):
                try:
                    return self._call_one(provider, system, user)
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    # small backoff before retry / next provider
                    time.sleep(0.6 * (attempt + 1))
                    continue
        raise LLMCallError(
            f"All {len(self.providers)} providers failed. Last error: {last_error}"
        )

    def _call_one(self, provider: dict, system: str, user: str) -> LLMResponse:
        url = provider["base_url"].rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json",
        }
        # OpenRouter likes extra headers but they are optional.
        if "openrouter" in provider["base_url"]:
            headers["HTTP-Referer"] = "https://comet-riobamba.local"
            headers["X-Title"] = "comet_riobamba repurposer"

        payload = {
            "model": provider["model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        t0 = time.monotonic()
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        elapsed = time.monotonic() - t0

        if resp.status_code >= 400:
            raise RuntimeError(
                f"{provider['name']} HTTP {resp.status_code}: {resp.text[:300]}"
            )

        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(
                f"{provider['name']} malformed response: {json.dumps(data)[:300]}"
            ) from exc

        return LLMResponse(
            text=text.strip(),
            provider=provider["name"],
            model=provider["model"],
            elapsed_s=round(elapsed, 2),
            raw=data,
        )
