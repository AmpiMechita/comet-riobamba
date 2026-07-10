"""
comet_repurposer
================

Multi-platform content repurposing pipeline for the COMET-RIOBAMBA agent.

Takes the value-dense technical content the agent already produces
(Moltbook posts, ebooks, research agenda, social_content markdown) and
generates platform-adapted versions for:

  - Instagram   (caption + carousel slides + hashtags)
  - TikTok      (15-60s vertical video script)
  - YouTube     (Shorts script + long-form outline)
  - X / Twitter (thread of 3-7 tweets, <=280 chars each)
  - LinkedIn    (editorial post, ~1300 chars)
  - Facebook    (community post, conversational)

Output goes to ``exports/social_repurpose/<YYYY-MM-DD>/<slug>/<platform>.md``
so it lives alongside the existing ``exports/social_content/`` folder and
does not collide with ``social_distributor.py``.

The LLM client is OpenAI-compatible and works with the providers
comet_riobamba already configures in ``.env``:
  - Gemini via Google AI (OpenAI-compatible endpoint)
  - Groq
  - OpenRouter
  - Cerebras
  - Ollama (local)
"""

from .config import RepurposeConfig
from .llm_client import LLMClient, LLMCallError
from .sources import (
    SourceItem,
    iter_published_posts,
    iter_social_content,
    iter_ebooks,
    iter_research_agenda,
    iter_all_sources,
)
from .prompts import PLATFORMS, build_prompt
from .dedup import DedupStore
from .pipeline import repurpose_one, repurpose_batch

__version__ = "0.1.0"

__all__ = [
    "RepurposeConfig",
    "LLMClient",
    "LLMCallError",
    "SourceItem",
    "iter_published_posts",
    "iter_social_content",
    "iter_ebooks",
    "iter_research_agenda",
    "iter_all_sources",
    "PLATFORMS",
    "build_prompt",
    "DedupStore",
    "repurpose_one",
    "repurpose_batch",
]
