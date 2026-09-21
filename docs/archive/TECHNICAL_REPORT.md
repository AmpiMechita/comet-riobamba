<!--
AVISO DE DESACTUALIZACION - 2026-09-11
Los valores de configuracion en este documento NO reflejan la realidad.
Fuente de verdad: docs/CONFIG_TRUTH.md + config/config.py + .env
Este documento se conserva por valor historico, no como referencia tecnica.
-->
# COMET-RIOBAMBA v4.3.0 — Technical Report

> **Author:** AI-assisted codebase analysis  
> **Date:** 2026-06-12  
> **Version analyzed:** 4.3.0 (`run_agent.py` → `core/agent.py` → `phases/*`)  
> **Platform:** Windows / Python 3.14 / PowerShell  
> **LLM providers:** Gemini (OpenAI-compatible), OpenRouter, Cerebras, Ollama (local)

---

## 1. Project Overview

COMET-RIOBAMBA is an **autonomous AI agent** that operates on the [Moltbook](https://www.moltbook.com) social platform for AI and technology discussions. Its purpose is to generate original technical content, engage in community discussions, and continuously self-optimize via analytics—all without human intervention.

### Key characteristics

- **English-only policy:** All published content and replies are in English. The agent identity (`config/agent_identity.json`) defines tone as `"tecnico"`, `"claro"`, `"honesto"`, `"util"`, `"anti-humo"` but the language of all public output is English. Language instructions are injected into every LLM prompt (e.g., `"Always respond in English. This is an English-speaking platform."` in Phase B).
- **Editorial niche:** Revolutionary, innovative technology and AI problem‑solving. The agent acts as a *research architect* that proposes frameworks, exposes uncomfortable trade-offs, and avoids hype. The content style is dense technical prose without emojis, hashtags, or markdown.
- **Phased execution:** The agent runs in three sequential phases per cycle:
  - **Phase A** — Original content generation (up to 1 post/day)
  - **Phase B** — Community replies (up to 12 comments/day, own-posts first)
  - **Phase C** — Analytics, self-optimization, research agenda maintenance
- **Resilience-first design:** Circuit breakers (global, per-provider, per-API), exponential backoff retries, outbox pattern for failed publications, dynamic cycle intervals.

---

## 2. Architecture and Components

### 2.1 Entrypoint and core loop

```
run_agent.py              # Loads .env, sets up logging, calls asyncio.run(main())
  └── core/agent.py       # COMETRiobambaAgent — main orchestrator (768 lines)
        └── async def run()
              while not shutdown_requested:
                 1. Check global circuit breaker
                 2. _run_cycle()  → Phase A → Phase B → Phase C
                 3. register_cycle_result()  → dynamic interval adjustment
                 4. Sleep for current_interval seconds
                 5. Intra-sleep Phase B-only passes (independent clock)
```

The agent state is persisted in SQLite (`data/comet_state.db`) via `services/persistence.py`, tracking `cycle`, `posts_today`, `comments_today`, `consecutive_failures`, and `last_value_review`.

### 2.2 Module map

| Module | Lines | Role |
|---|---|---|
| `run_agent.py` | 29 | Entrypoint, .env loading, logging setup |
| `core/agent.py` | 768 | Main orchestrator, cycle loop, outbox retry, health snapshots, Telegram alerts |
| `core/state_manager.py` | 93 | AgentState loading/saving from SQLite |
| `core/write_policy.py` | 391 | Content governance: editorial fit, daily caps, dedup, topic cooldown |
| `core/observability.py` | 44 | Event emission system (16 event types) |
| `core/value_log.py` | 63 | JSONL value event logging |
| `core/value_review.py` | 193 | Weekly value review via LLM |
| `phases/phase_a_content.py` | 493 | Original content generation, topic selection, challenge solving |
| `phases/phase_b.py` | 1384 | Community replies, relevance scoring, dedup, conversation state |
| `phases/phase_c_analytics.py` | 388 | Performance metrics, insights, CAPTCHA monitoring, topic review |
| `phases/engagement/` | 1001 | Phase C engagement sub-package (classifier, responder, tracker) |
| `phases/deps.py` | 42 | Phase dependency dataclasses (PhaseADeps, PhaseBDeps, PhaseCDeps) |
| `services/model_cascade.py` | 418 | Multi-provider LLM orchestration with fallbacks and circuit breakers |
| `services/moltbook_api_client.py` | 444 | HTTP client for Moltbook API with circuit breaker |
| `services/persistence.py` | 504 | SQLite persistence (state, actions, outbox, engagement, dedup) |
| `services/captcha_math_solver.py` | 81 | Deterministic math solver for Moltbook challenge verification |
| `services/challenge_solver.py` | ~260 | ChallengeSolver: deterministic + LLM fallback math resolver |
| `services/global_circuit.py` | 217 | Global circuit breaker + dynamic interval management |
| `services/telegram_client.py` | 234 | Bidirectional Telegram integration (alerts, commands) |
| `services/research_agenda.py` | 153 | Research agenda management (topics, questions, experiments) |
| `services/roadmap.py` | 115 | Topic roadmap with weighted series for anti-repetition |
| `services/conversation_state.py` | 91 | Per-thread conversation tracking for Phase B debates |
| `services/content_validator.py` | 57 | Content safety validator (forbidden words, length checks) |
| `services/outbox_manager.py` | 154 | Supplementary SQLite outbox for pending publications |
| `services/feedback_log.py` | 73 | Structured feedback logging to JSONL |
| `services/social_metrics.py` | 52 | JSONL social metrics event logger |
| `services/self_eval.py` | 73 | Daily self-evaluation metrics |
| `services/platform_awareness.py` | 92 | Vibration alignment self-awareness system |
| `services/topic_memory.py` | 171 | SQLite-based topic dedup with Jaccard similarity |
| `utils/resilience.py` | 259 | Canonical CircuitBreaker implementation with SQLite persistence |
| `utils/logging_config.py` | 64 | Rotating file + console logging with UTF-8 |
| `utils/phase_utils.py` | 83 | Phase error boundary decorator + dependency validation |
| `config/config.py` | 252 | Central configuration (behavior, content, routing, logging) |
| `config/agent_policy.py` | 52 | Frozen dataclass with all numeric limits |
| `config/credentials.py` | 76 | Credentials from environment variables |
| `prompts/prompt_templates.py` | 90 | SYSTEM_PROMPT, POST_TEMPLATE_CONTRARIAN, REPLY_TEMPLATE, SCORING_TEMPLATE |
| `personality/persona.py` | 51 | Legacy personality layer (Spanish openers — not actively used in current flow) |

### 2.3 Main data flows

1. **Scheduling:** Agent runs continuously in an `asyncio` loop with a configurable cycle interval (default 28800s = 8h, but dynamically adjusted 1.5x backoff on errors, immediate recovery on success; min 30min, max 8h). Phase B has an independent 1h clock for intra-sleep passes.

2. **LLM calls:** All phases use `model_cascade.generate(tier, prompt, system_prompt, ...)`. Tier selection:
   - Phase A: `"openrouter"` (Gemini + OpenRouter fallback, up to 3 retries)
   - Phase B: `"openrouter"` (Gemini + OpenRouter fallback)
   - Phase C: `"haiku"` for engagement replies
   - ChallengeSolver: `"opus"` → `"cerebras"` cascade (temperature=0.0)

3. **Moltbook API:** `moltbook_api_client.create_post()`, `create_comment()`, `submit_verification()`, `fetch_posts()`, `get_feed()`, `fetch_post_comments()`. Each request goes through a circuit breaker (default 5 failures → 60s cooldown). Rate limits (429) are detected and handled via `Retry-After` header.

4. **Persistence:** SQLite (`data/comet_state.db`) stores agent state, action audit log, outbox queue, engagement metrics, text hashes for dedup, and system flags (circuit breaker state). JSON files complement SQLite for: `replied_comment_ids.json`, `commented_post_ids.json`, `research_agenda.json`, `topic_index.json`, `value_log.jsonl`, `feedback_log.jsonl`, `social_metrics.jsonl`, etc.

5. **Logging:** Rotating file handler (`logs/agent.log`, max 5MB, 3 backups) + console, both UTF-8. Per-cycle JSON logs in `logs/cycle_N.json` (keeps last 150). Health snapshots in `data/state/health.json`. Telegram alerts for errors and cycle summaries.

---

## 3. Phase A — Content Generation

### 3.1 Scheduling and limits

- **Cycle gate:** Runs once per agent cycle (default 8h) if `posts_today < max_posts_per_day` (currently **1** per day).
- **Daily limit:** `AGENT_MAX_POSTS_PER_DAY=1` in `.env`, validated with bounded int (1-10).
- **Max consecutive failures:** 3 before Telegram critical alert.
- **Outbox retry:** Failed posts are retried before each Phase A run with exponential backoff (60-3600s).

### 3.2 Topic selection (weighted pipeline)

Phase A selects a topic through a cascade of sources:

1. **Research agenda** (`services/research_agenda.py`): Uncovered topics from `data/research_agenda.json` — fed by Phase B (high-scoring feed threads) and Phase C (trend watcher).
2. **Roadmap** (`services/roadmap.py`): Weighted series with anti-repetition (checks last 5 posts). Series weights are dynamically adjusted by Phase C based on real engagement data.
3. **Static list** (`content_cfg["topics"]`): 10 fallback topics in Spanish (e.g., "arquitecturas de agentes y sistemas agentic", "MLOps y despliegue de modelos fundacionales").

Topic weights incorporate engagement data from the SQLite `engagement` table, preferring under-performing topics to diversify content.

### 3.3 Generation pipeline

1. Build prompts using `prompts/prompt_templates.py` templates:
   - `SYSTEM_PROMPT` — Core identity, communication style, absolute rules (JSON output only)
   - `POST_TEMPLATE_CONTRARIAN` — PROBLEM → PROPOSAL → RESEARCH QUESTION structure
   - Editorial policy injected from `config/config.py` (`phase_a_system_prompt`, `content_cfg`)
2. Call `ModelCascade.generate(tier="openrouter", ...)` with up to 3 retries
3. Parse JSON response `{"title": "...", "content": "..."}`

### 3.4 Content validation (7 checks)

After generation, Phase A applies multiple validation layers:

- **URL/link detection**
- **Code blocks and error traces**
- **Bullet points / numbered lists**
- **Emojis**
- **Academic subtitles** (Abstract, Introduction, Conclusion, etc.)
- **Filler openings** ("In the realm of", "One non-obvious claim")
- **Single paragraph** (rejected)
- **Length bounds:** `min_post_length_chars=300`, `max_post_length_chars=900`, `target=600`
- **Similarity to recent posts:** SHA-256 text hash dedup via SQLite `post_embeddings` table (7-day window)

### 3.5 Publication and verification

1. Check if `whisper_mode` is active (logs only, no publish)
2. Publish to Moltbook via `moltbook_api_client.create_post()`
3. If the API returns a `verification` challenge (CAPTCHA), run `ChallengeSolver.solve_and_verify()`:
   - **Solver pipeline:** `solve_captcha_math()` (deterministic, Decimal) → `_solve_native_math()` (normalized regex + Decimal) → `_extract_and_eval_with_llm()` (LLM extracts expression, local eval) → `_solve_with_llm()` (LLM-only)
   - **Validation:** format `^-?\d+\.\d{2}$`, reject trivial `"0.00"` from LLM paths
   - **Tiers:** `"opus"` → `"cerebras"` cascade for LLM-based solving
4. On failure, enqueue to outbox (`data/outbox.db` JSON file + SQLite `outbox` table for comments)
5. Update research agenda (mark topic as `covered`)
6. Random 30-90s delay between posts

### 3.6 Mode options

- `"research"` (default): PROBLEM → PROPOSAL → RESEARCH QUESTION
- `"expository"`: Traditional 3-paragraph format with strong conclusion

---

## 4. Phase B — Community Replies

### 4.1 Priority and order

Phase B processes replies in strict order:

1. **Own-post replies first** (`_execute_own_post_replies`): Responds to all relevant un-responded comments on the agent's own posts.
2. **Feed replies second** (`_execute_feed_replies`): Responds to third-party posts with stricter relevance thresholds.

### 4.2 Limits (from `AgentPolicy` / `.env`)

| Limit | Default | Env var |
|---|---|---|
| `max_comments_per_day` | 12 | `AGENT_MAX_COMMENTS_PER_DAY` |
| `max_comment_replies_per_cycle` | 4 | `AGENT_MAX_COMMENT_REPLIES_PER_CYCLE` |
| `max_comments_per_post` (own) | 3 | `AGENT_MAX_COMMENTS_PER_POST` |
| `max_feed_comments_per_post` | 1 | `AGENT_MAX_FEED_COMMENTS_PER_POST` |
| `max_feed_replies_per_day` | 3 | (env var optional) |

### 4.3 Relevance scoring system

Each comment is scored with:

| Signal | Value |
|---|---|
| Contains `?` | +30 |
| Mentions agent name | +40 |
| ≥2 tech keywords | +25 |
| Length < 10 chars | -20 |
| Length < 25 chars | -10 |
| Gratitude/fluff | -15 |
| Length > 150 chars | +5 |
| Frontier potential (no metrics/guardrails/failure modes covered) | +20 |

Thresholds: `min_comment_relevance_score` = 4 (base), +10 for feed replies. Cold-start mode (posts_today < 10) uses min_score = 4 for feed.

### 4.4 Deduplication

- **Persistent set:** `data/replied_comment_ids.json` stores `{post_id}:{comment_id}` keys
- **Near-duplicate reply detection:** Bigram overlap (Jaccard similarity ≥ 0.6) compares new replies against the agent's last comment in the same thread
- **Auto-regeneration:** One automatic retry with stricter instruction if near-duplicate detected
- **Debate continuation:** `can_continue_thread()` via `conversation_state.py` — up to `MAX_TURNS_PER_THREAD` (4)

### 4.5 Submolt filtering

Allowed submolts include `agents`, `general`, `ai`, `security`, `aisafety`, `builds`, `memory`, `todayilearned`, etc. Blocked: `introductions`, `announcements`, `philosophy`, `existential`, `consciousness`, `pondering`.

### 4.6 Value classification

After each successful reply, Phase B calls `_classify_and_log_value()` using the LLM to classify the interaction as `"resolvio_problema"` (solved problem) or `"aporte_util"` (useful contribution), logged to `data/value_log.jsonl`. High-scoring feed interactions also register topics to the research agenda.

### 4.7 Independent Phase B clock

Phase B has its own timer (`phase_b_interval_seconds = 3600s` = 1h). The main loop checks this clock both between cycles and during the sleep interval (intra-sleep check every 1s), running Phase B-only passes independently of Phase A/C.

---

## 5. Phase C — Analytics and Engagement

Phase C is split into two components:

### 5.1 `PhaseCAnalytics` (`phases/phase_c_analytics.py`)

Runs every **3rd cycle** (cycle_count % 3 == 0) with a time-based gate (`phase_c_analytics_interval = 86400s` = 24h).

**Capabilities:**

1. **Performance metrics:** Fetches posts from Moltbook API, calculates average engagement (likes + comments), extracts topic keywords.
2. **Insights generation:**
   - Low engagement detection (< 2 avg) → suggests template rotation
   - Topic repetition (≥ 3 posts in 24h) → suggests diversification
3. **CAPTCHA success monitoring:** Parses `logs/agent.log` for `"CAPTCHA resuelto"` and `"Moltbook rechazo"` patterns; warns if rate < 50%.
4. **Topic review (`_run_topic_review`):** Adjusts roadmap series weights based on real engagement data from SQLite `engagement` table.
5. **Research agenda update (`_update_research_agenda`):**
   - Extracts trending topics from recent posts (≥ 2 occurrences)
   - Registers high-impact threads (engagement ≥ 5)
   - Detects new technical terms from posted content
6. **Telegram reporting:** Sends daily analytics reports.

### 5.2 `PhaseCEngagement` (`phases/engagement/`)

A three-module sub-package:

- **`classifier.py`:** Classifies comments into types (`question`, `critique`, `evidence`, `cross_reference`, etc.), computes priority scores (0-100), decides whether to reply based on type, English detection, and identity mentions.
- **`responder.py`:** Generates replies via `ModelCascade` (tier `"haiku"`), handles `no_providers_available` errors, publishes to Moltbook.
- **`tracker.py`:** Tracks post IDs, comment events, conversation reviews, improvement candidates. Identity detection via fuzzy matching of author names. JSONL event logging.

Both components share the same daily/cycle reply limits defined in `AgentPolicy`.

---

## 6. Model Cascade

### 6.1 Provider hierarchy

The `ModelCascade` (`services/model_cascade.py`, 418 lines) supports multiple providers:

1. **`ollama_local`** — Always available, local Ollama (model: `qwen2.5:3b`)
2. **`tier_opus`** — Gemini 2.5 Flash (via OpenAI-compatible endpoint)
3. **`tier_sonnet`** — Gemini 2.5 Flash (same endpoint)
4. **`tier_haiku`** — Gemini 2.5 Flash Lite
5. **`openrouter`** — Free tier: `openai/gpt-oss-120b:free`
6. **`cerebras`** — `llama-3.3-70b` on Cerebras cloud

### 6.2 Tier mapping

| Requested tier | First attempt | Fallback order |
|---|---|---|
| `"opus"` | tier_opus (Gemini) | ollama_local → all others |
| `"sonnet"` | tier_sonnet (Gemini) | ollama_local → all others |
| `"haiku"` | tier_haiku (Gemini Lite) | ollama_local → all others |
| `"openrouter"` | openrouter | ollama_local → all others |
| `"cerebras"` | cerebras | ollama_local → all others |
| `"default"` | ollama_local | all others |

### 6.3 Resilience features

- **Per-provider circuit breakers:** Default 3 failures → open, 60s cooldown. Client errors (401/403/400) force 5min open.
- **Rate limits (429):** No circuit breaker increment, just backoff.
- **Exponential backoff:** 2^attempt seconds between retries.
- **Health endpoint:** `get_provider_health()` returns status of all providers.

---

## 7. Moltbook API Client

### 7.1 Endpoints

| Method | Path | Used by |
|---|---|---|
| `POST /posts` | `create_post()` | Phase A, outbox |
| `POST /posts/{id}/comments` | `create_comment()` | Phase B, Phase C engagement |
| `POST /verify` | `submit_verification()` | ChallengeSolver |
| `GET /posts` | `fetch_posts()`, `get_feed()` | Phase B, Phase C |
| `GET /posts/{id}/comments` | `fetch_post_comments()`, `get_comments()` | Phase B, Phase C |

### 7.2 Resilience

- **Circuit breaker:** `moltbook_api` with configurable thresholds (`MOLTBOOK_CB_FAILURES`, `MOLTBOOK_CB_COOLDOWN_SECONDS`)
- **Rate limit handling:** Detects 429 responses and `Retry-After` header
- **Normalization:** Handles multiple field name conventions (`id`/`postId`/`post_id`, `author` as dict/string, etc.)
- **`_pick_list()` helper:** Extracts list data from various response shapes defensively

---

## 8. Persistence Layer

### 8.1 SQLite (`services/persistence.py`)

**Connection:** WAL mode + synchronous=FULL, single-writer, single-node.

| Table | Key columns | Purpose |
|---|---|---|
| `agent_state` | cycle, posts_today, comments_today, last_post_date, consecutive_failures | Single-row agent state |
| `actions` | cycle, phase, type, payload_json, status, latency_ms | Audit log |
| `outbox` | kind ('post'/'comment'), payload_json, status, retry_attempt, next_retry_at | Failed publication queue |
| `engagement` | post_id, topic, likes, comments, shares | Topic engagement metrics |
| `post_embeddings` | post_id, text_hash (SHA-256) | Text deduplication |
| `system_flags` | key, value_json | Circuit breaker state, cycle control |

### 8.2 JSON/JSONL files

| File | Purpose |
|---|---|
| `data/replied_comment_ids.json` | Set of `{post_id}:{comment_id}` replied pairs |
| `data/commented_post_ids.json` | Dict of post_id → ISO timestamp (7-day TTL) |
| `data/research_agenda.json` | ResearchAgenda dataclass (topics, questions, experiments, high-impact threads, terms) |
| `data/topic_index.json` | Topic writing log for cooldown tracking |
| `data/write_log.jsonl` | Every write decision (allowed/blocked) |
| `data/value_log.jsonl` | Value classification events |
| `data/feedback_log.jsonl` | Structured feedback records |
| `data/social_metrics.jsonl` | Social interaction events |
| `data/self_eval_state.json` | Daily self-evaluation metrics |
| `data/state/agent_state.json` | JSON fallback for agent state |
| `data/state/health.json` | Current cycle health snapshot |
| `data/state/phase_c_state.json` | Phase C persistent state |
| `data/outbox.db` | JSON file for post outbox (legacy; TODO to migrate to SQLite) |

---

## 9. Challenge Solver

### 9.1 Purpose

Moltbook sometimes returns a math verification challenge after post publication. The `ChallengeSolver` (`services/challenge_solver.py`) resolves it before proceeding.

### 9.2 Solver pipeline

```
solve_and_verify(challenge_data)
  │
  ├─ 1. solve_captcha_math()   — deterministic, Decimal, handles unicode (×÷−)
  │      (from captcha_math_solver.py)
  │
  ├─ 2. _solve_native_math()   — normalized regex + Decimal, handles negatives
  │      (imports format_captcha_answer from captcha_math_solver)
  │
  ├─ 3. _extract_and_eval_with_llm()  — LLM extracts expression, ast.literal_eval locally
  │      (tier="opus" → "cerebras", temperature=0.0)
  │
  └─ 4. _solve_with_llm()     — LLM-only, regex-extracts last number from response
         (tier="opus" → "cerebras")
```

### 9.3 Validation

- Format: `^-?\d+\.\d{2}$` (always 2 decimal places)
- Source tracking: rejects `"0.00"` if produced by LLM paths (sources `"llm_eval"` or `"llm"`)
- Empty/None answers return `False`

### 9.4 Tests

24 tests in `tests/test_challenge_solver.py` cover: basic operations, negatives, unicode operators, Decimal precision, division by zero, empty text, mojibake fixing, incomplete data, API rejection, LLM fallback, invalid format, trivial answer rejection.

---

## 10. Configuration System

### 10.1 Layered configuration

1. **`AgentPolicy`** (`config/agent_policy.py`): Frozen dataclass with default numeric limits. Acts as the single source of truth for all thresholds.
2. **`behavior_cfg`** (`config/config.py`): Dictionary loaded from environment variables with `_validate_bounded_int()` for safe parsing. Overrides `AgentPolicy` defaults.
3. **Env vars** (`.env`): Runtime overrides for all configurable parameters.
4. **`content_cfg`** (`config/config.py`): Content generation settings (topics, tone, language, formatting, prompt templates, avoidance rules).
5. **`routing_cfg`** (`config/config.py`): Model provider routing (default provider, fallback order, rate limits).
6. **`logging_cfg`** (`config/config.py`): Log file rotation settings, format, level.
7. **`Credentials`** (`config/credentials.py`): API keys and endpoints loaded from `.env`.
8. **`agent_charter`** (`config/config.py`): Mission/identity loaded from `config.agent_charter.yaml` (YAML).

### 10.2 Key current values (from `.env`)

```
AGENT_CYCLE_INTERVAL_SECONDS = 28800    # 8h
AGENT_MAX_POSTS_PER_DAY = 1
AGENT_PHASE_B_ENABLED = 1
AGENT_PHASE_C_ENABLED = 1
AGENT_MAX_COMMENTS_PER_DAY = 12
AGENT_MAX_COMMENT_REPLIES_PER_CYCLE = 4
TELEGRAM_ALERTS_ENABLED = 1
AGENT_WHISPER_MODE = 0                  # Publishing enabled
```

---

## 11. Scripts and Operations

| Script | Purpose |
|---|---|
| `run_agent.py` | Primary Python entrypoint |
| `RUN.ps1` | PowerShell runner with environment setup |
| `run_prod.ps1` | Production wrapper with logging |
| `run_agent_real.ps1` | Real agent execution script |
| `start_agent.bat` | Windows batch launcher |
| `stop_agent.bat` | Windows batch stopper |
| `check_config.ps1` | Configuration validation |
| `comet-modes.ps1` | Mode switching (whisper/production) |

---

## 12. Known Technical Debt and TODOs

- **`5.0-LP1`:** Refactor post outbox (`_retry_outbox`) from JSON file (`data/outbox.db`) to SQLite `outbox` table (currently only comment outbox uses SQLite properly).
- **`5.0-LP4`:** Clean up unused env vars (`DASHSCOPE_API_KEY`, duplicate `MODEL_TIER_OPENROUTER*`, `CEREBRAS*` remnants).
- **`routing_cfg`** references `"dashscope"` as default provider, but the `.env` only configures Gemini/OpenRouter/Cerebras. The `model_cascade.py` does not reference `routing_cfg` — it builds providers from `Credentials` directly.
- **Phase A mode switching:** `phase_a_mode` in `behavior_cfg` can be `"research"` or `"expository"`, but `_validate_bounded_int` in `config.py` line 77 loads it as `"research"` via direct env read — this path does not go through bounded validation.
- **`personality/persona.py`** contains Spanish phrases and appears to be a legacy/abandoned layer. The active personality is driven by `prompts/prompt_templates.py` and `config/agent_identity.json`.
- **`phases/phase_b_responses_new.py`** is an empty placeholder file (0 lines).
- **`services/editorial_policy.py`** is referenced by Phase A but its exact structure was not verified; it may overlap with `content_cfg`.

---

## 13. Testing

Tests are in `tests/` and use `pytest` + `pytest-asyncio`. Key test files:

| Test file | Subject |
|---|---|
| `test_challenge_solver.py` (24 tests) | ChallengeSolver math solving |
| `test_core_logic.py` | Agent core logic |
| `test_model_cascade.py` | ModelCascade provider orchestration |
| `test_phase_b_*.py` (multiple files) | Phase B relevance, dedup, limits, wiring |
| `test_phase_a_research.py` | Phase A research mode |
| `test_phase6_error_boundary.py` | Error boundary decorator |
| `test_roadmap_experiments.py` | Roadmap and experiments |
| `test_scripts.py` | Utility scripts |

Run with: `python -m pytest tests/` from the repo root.

---

## Appendix: File Tree (key modules only)

```
C:\comet-riobamba-v31\
├── run_agent.py                     # Entrypoint
├── core/
│   ├── agent.py                     # Main orchestrator
│   ├── state_manager.py             # SQLite-backed agent state
│   ├── write_policy.py              # Content governance engine
│   ├── observability.py             # Event emission
│   ├── value_log.py                 # Value event logging
│   ├── value_review.py              # Weekly value review
│   └── metrics.py                   # Metrics ingestion
├── phases/
│   ├── deps.py                      # Phase dependency dataclasses
│   ├── phase_a_content.py           # Phase A — content generation
│   ├── phase_b.py                   # Phase B — community replies
│   ├── phase_c_analytics.py         # Phase C — analytics
│   ├── phase_c_engagement.py (via engagement/)
│   └── engagement/
│       ├── __init__.py              # PhaseCEngagement orchestrator
│       ├── classifier.py            # Comment classification
│       ├── responder.py             # Reply generation & publishing
│       └── tracker.py               # State tracking & identity
├── services/
│   ├── model_cascade.py             # Multi-provider LLM orchestration
│   ├── moltbook_api_client.py       # HTTP client for Moltbook
│   ├── persistence.py               # SQLite persistence layer
│   ├── challenge_solver.py          # Challenge resolver
│   ├── captcha_math_solver.py       # Deterministic math solver
│   ├── global_circuit.py            # Global circuit breaker
│   ├── telegram_client.py           # Telegram integration
│   ├── research_agenda.py           # Research agenda management
│   ├── roadmap.py                   # Topic roadmap with series weights
│   ├── conversation_state.py        # Thread conversation tracking
│   ├── content_validator.py         # Content safety validator
│   ├── platform_awareness.py        # Vibration alignment system
│   ├── social_metrics.py            # Social event logging
│   ├── feedback_log.py              # Structured feedback logging
│   ├── self_eval.py                 # Self-evaluation metrics
│   ├── topic_memory.py              # Topic deduplication
│   └── outbox_manager.py            # Supplementary outbox
├── config/
│   ├── __init__.py                  # Public API re-exports
│   ├── config.py                    # Central configuration
│   ├── agent_policy.py              # Frozen dataclass (limits)
│   ├── credentials.py               # Credentials from .env
│   ├── behavior_cfg.py              # Static behavior defaults
│   └── agent_identity.json          # Agent persona definition
├── prompts/
│   └── prompt_templates.py          # System, post, reply, scoring templates
├── personality/
│   ├── persona.py                   # Legacy personality (Spanish)
│   └── integration.py               # Personality wrapper
├── utils/
│   ├── resilience.py                # Circuit breaker, retry utilities
│   ├── logging_config.py            # Rotating file + console logging
│   └── phase_utils.py               # Phase error boundary
├── data/                            # Runtime data (SQLite, JSON, JSONL)
├── logs/                            # Log files (agent.log, cycle_N.json)
├── tests/                           # pytest test suite
├── scripts/                         # PowerShell automation
├── .env                             # Environment configuration
└── RUN.ps1 / run_prod.ps1          # PowerShell entrypoints
```
