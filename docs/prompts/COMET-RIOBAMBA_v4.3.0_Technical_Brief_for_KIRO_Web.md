# COMET-RIOBAMBA v4.3.0 — Technical Brief for KIRO Web (Claude Opus 4.8)

> **Purpose**: This document provides complete context for continuing development of the COMET-RIOBAMBA autonomous social media agent. It covers architecture, current state, all fixes applied, known issues, and pending roadmap. The codebase is at `C:\comet-riobamba-v31`, executed via `python run_agent.py`.

---

## 1. PROJECT OVERVIEW

COMET-RIOBAMBA is an autonomous agent that operates on **Moltbook** (a social platform similar to Reddit/HackerNews for AI and tech discussions). It runs continuous 3-phase cycles every 5 minutes:

| Phase | Function | Output |
|-------|----------|--------|
| **Phase A** | Generate and publish original content | Posts on Moltbook |
| **Phase B** | Reply to community (own posts + feed) | Comments on Moltbook |
| **Phase C** | Analytics, self-diagnosis, optimization, energy intel | Internal state + Telegram alerts |

### Tech Stack
- **Language**: Python 3.11+
- **State**: SQLite (`comet_state.db` for global state, `comet_dedup.db` for reply dedup)
- **Platform API**: REST client to `https://www.moltbook.com/api/v1`
- **LLM Cascade**: 8 providers with circuit breakers and automatic failover
- **Rate Limiting**: Token bucket — 1 write per 150 seconds (shared between posts and comments)
- **Observability**: Structured JSON events, wire-check files, ValueLog for reply quality tracking
- **Telegram**: `services/telegram_client.py` (existing, robust) — alerts and daily balance
- **Energy Intel**: `energy_intel_node.py` (standalone FastAPI + scrapers) — papers, patents, funding

### Current Configuration
```
version=4.3.0, config_version=4.2
max_posts_per_day=6
cycle_interval_seconds=300 (5 min)
max_comments_per_day=999
max_comment_replies_per_cycle=8
max_comments_per_post=3
max_feed_replies_per_day=20 (AGENT_MAX_FEED_REPLIES_PER_DAY in .env line 16)
token_bucket=1 write / 150s
```

### Model Cascade (8 providers, failover order)
| Tier | Provider | Model | Status |
|------|----------|-------|--------|
| tier_opus | DeepSeek | deepseek-chat | **Active** (primary) |
| tier_sonnet | Google | gemini-2.5-flash | Rate-limited (backup) |
| tier_haiku | Google | gemini-2.0-flash | **PERMANENTLY OPEN** (free tier quota=0) |
| openrouter | OpenRouter | openai/gpt-oss-120b:free | Rate-limited |
| cerebras | Cerebras | llama-3.3-70b | 404 (model not found) |
| groq | Groq | llama-3.3-70b-versatile | 401 (invalid API key) |
| ollama_local | Local | qwen2.5:3b | Last resort fallback |
| ollama_native | Local | qwen2.5:3b | Last resort fallback |

**Effective reality**: Only `tier_opus` (deepseek-chat) is reliably functional. Every LLM call first tries tier_haiku, gets circuit breaker skip (~2s wasted), then falls to tier_opus with a DEGRADED warning.

---

## 2. ARCHITECTURE

### File Structure
```
C:\comet-riobamba-v31\
├── run_agent.py                    # Main entry point
├── .env                            # Config (API keys, tiers, limits, Telegram)
├── core/
│   ├── agent.py                    # Orchestrator: A→B→C cycle, PhaseBDeps, outbox retry
│   ├── state_manager.py            # comet_state.db persistence (cycle, counters)
│   ├── value_log.py                # ValueLog event registration
│   └── platform_awareness.py       # Vibration/success metrics
├── phases/
│   ├── phase_a_content.py          # Original content generation + CAPTCHA verification
│   ├── phase_b.py                  # Community replies (~2000+ lines, THE core file)
│   └── phase_c_analytics.py        # Analytics, self-diagnosis, energy intel hook
├── services/
│   ├── moltbook.py                 # MoltbookAPIClient (REST, rate limiter, auth)
│   ├── model_cascade.py            # 8-provider LLM cascade with circuit breakers
│   ├── challenge_solver.py         # CAPTCHA solver (native eval → word parsing → LLM)
│   ├── claim_checker.py            # Claim extraction & on-topic validation
│   ├── dedup_store.py              # DedupStore (comet_dedup.db) with 24h TTL cleanup
│   ├── own_post_store.py           # published_posts.json tracker
│   ├── telegram_client.py          # TelegramClient (send, alert, commands listener)
│   ├── deepseek_balance.py         # DeepSeek API balance checker (daily)
│   ├── energy_intel_telegram.py    # Energy intel → Telegram bridge (1x/hour in Phase C)
│   ├── platform_awareness.py       # Platform vibration metrics
│   └── energy_intel_node.py        # Standalone: FastAPI + scrapers (papers, patents, funding)
├── utils/
│   └── resilience.py               # CircuitBreaker implementation
├── data/                           # Runtime data (SQLite, JSON, JSONL)
├── modes.py                        # 5 communication modes (architect, historian, etc.)
├── prompt_templates.py             # SYSTEM_PROMPT, AGENT_CHARTER
├── content_validators.py           # Validators (clean_llm_output integrated into phase_b)
├── agent_policy.py                 # Behavior policy configuration
├── deps.py                         # PhaseBDeps dependency injection container
└── tests/                          # 212+ unit tests (all passing)
```

### Phase B Pipeline Detail (the most complex component)
```
Feed Scan (50 posts)
  ↓
Body Extraction (title + body + text fallback, strip HL tags)
  ↓
Spam Gate (len < 100 → discard)
  ↓
_allow_feed_repeat_reply (24h max block, new comments bypass)
  ↓
Scoring (tech_kw×10 max40 + len>100(+10) + frontier_boost(0|10|20) + base 30)
  ↓
Selection (top N by score, max cycle_budget=8)
  ↓
For each selected post:
  ├── Communication mode selection (architect/historian/etc.)
  ├── LLM draft generation (model cascade)
  ├── clean_llm_output() (strip special tokens, code fences)
  ├── Claim-check (on_topic validation, OR threshold ≥0.4)
  ├── Quality guardrails check
  ├── Length gate (≥40 chars)
  ├── Dedup fingerprint store
  ├── Token bucket wait (~150s)
  └── Publish comment → Moltbook
```

### Scoring Formula
```python
score = 30  # base score ("?" = question indicator)
      + min(count_tech_keywords(body) * 10, 40)  # max 40 from keywords
      + (10 if len(body) > 100 else 0)           # substance bonus
      + (20 if has_error_keywords(body) else 0)   # error/bug discussion
      - (30 if is_spam(body) else 0)              # spam penalty
      + frontier_boost                            # 0/10/20 based on roadmap match

# 49 English tech keywords for matching
_TECH_KEYWORDS = ["agent", "agents", "llm", "model", "models", "api", ...]
```

---

## 3. ALL FIXES APPLIED (Session History)

### Session 1: Critical Debugging (25 Jun 2026 — earlier session)

| # | Fix | File(s) | What Changed |
|---|-----|---------|-------------|
| F1 | _TECH_KEYWORDS was empty | phase_b.py:588-599 | Fixed import, restored 49 English keywords |
| F2 | is_replied→has_renamed | phase_b.py:1908 | Fixed attribute name mismatch |
| F3 | Body extraction fallback | phase_b.py:1056,1062-1064 | Added "text" to fallback chain |
| F4 | Spam gate | phase_b.py:1072-1078 | Added `len(post_body) < 100 → discard` |
| F5 | _allow_feed_repeat_reply | phase_b.py:822-896 | **Complete rewrite**: 24h max block, new comments bypass, reduced penalties |
| F6 | Dedup DB cleanup | data/comet_dedup.db | Deleted 370 accumulated rows |
| F7 | Budget logging | phase_b.py:1042-1051 | Fixed remaining_feed_daily calculation |
| F8 | PhaseBDeps.posts_today | deps.py, core/agent.py | Injected posts_today from state |
| F9 | Per-post selection log | phase_b.py:1107-1112 | Added post_id, score, body_preview to logs |

**Result**: Feed replies went from 0/0 to 8/8 per cycle.

### Session 2: KIRO Fixes (25 Jun 2026 — KIRO agent)

| Bug | File(s) | Fix Applied |
|-----|---------|-------------|
| **P0-1** CAPTCHA always extracts "32 + 8" | challenge_solver.py | Rewritten: native eval → word parsing ("twenty"→20) → LLM (English prompt, max_tokens=100, raw challenge logging). **Now extracts correctly**: `'23 + 7' = 30.00 ✅` |
| **P0-2** Architect "weakest link" opener | modes.py:9 | Structural rule #2 changed from "identify bottleneck" to "restate decision + trade-off". "weakest link" added to forbidden phrases |
| **P1-1** Claim-check 12.5% false positives | claim_checker.py, phase_b.py | Prompt relaxed (allows analogies), threshold changed from AND score≥0.6 to OR score≥0.4. **Result: 0 FP in next cycle** |
| **P1-2** content_validators.py disconnected | phase_b.py | `clean_llm_output()` integrated: strips special tokens, code fences, markdown headers |
| **P1-3** COMMENT_STYLE in Spanish | phase_b.py:~282 | "Stricter" regeneration instruction translated to English |
| **P2-1** max_feed=20 mysterious | .env line 16 | Documented: `AGENT_MAX_FEED_REPLIES_PER_DAY=20` was in .env all along |
| **P2-2** DedupStore no TTL | dedup_store.py, phase_b.py | `cleanup(older_than_hours=24)` added, called at cycle start |
| **P2-3** Over-prohibition analysis | N/A (analysis only) | 18 hard-blocked phrases are reasonable (LLM template patterns). Not excessive. |
| **P3-1** OLLAMA_FALLBACK bypasses QC | phase_b.py | Now returns "" (skip) with WARNING instead of publishing raw fallback |
| **P3-2** No degraded model notification | model_cascade.py | `WARNING ⚠️ ModelCascade: DEGRADED` log when serving from different provider than requested |

### Session 3: Telegram + Energy Intel Integration (KIRO)

| Component | File(s) | What Was Done |
|-----------|---------|---------------|
| Telegram enable | .env | `TELEGRAM_ALERTS_ENABLED=1`, `TELEGRAM_DAILY_REPORT=1` (user needs to set token) |
| DeepSeek balance | services/deepseek_balance.py (NEW) | Queries `GET https://api.deepseek.com/user/balance`, daily dedup, low balance alert <$2.00 |
| Balance in cycle | core/agent.py | `_maybe_send_daily_balance()` at cycle start, persists in `data/last_balance_check.txt` |
| Energy Intel hook | services/energy_intel_telegram.py (MODIFIED) | `run_energy_intel_with_alerts()`, 1-hour throttle, max 3 alerts per run |
| Phase C integration | phases/phase_c_analytics.py | `_maybe_run_energy_intel()` at end of execute(), lazy import, error-safe |
| Tests | tests/test_telegram_integration.py | 17 tests: send success/fail, balance parse, throttle, energy intel, error resilience |

**Test count**: 212 tests, 0 failures (after all sessions).

---

## 4. VERIFIED POST-FIX BEHAVIOR (Cycle #1 logs, 25 Jun 21:07)

```
✅ CAPTCHA: '23 + 7' = 30.00 → verified (was stuck on '32 + 8' = 40.00)
✅ Claim-check: 0 failures (was 12.5% FP rate)
✅ Comment outbox: 2 pending comments recovered
✅ DEGRADED warnings: 7x (tier_haiku → tier_opus) — P3-2 working
✅ Phase A: 1 post published with CAPTCHA verified
✅ Phase B: 5/5 feed replies published (budget: 20/20, 2 already used by outbox)
✅ Dedup cleanup: running (166 rows present from prior state)
✅ Cycle duration: 1055s (17.6 min) — dominated by token bucket waits
```

---

## 5. KNOWN ISSUES (Still Open)

### ACTIVE — Needs Attention

| # | Issue | Severity | Details |
|---|-------|----------|---------|
| K1 | **tier_haiku permanently open** | Medium | Gemini free tier quota=0. Every LLM call wastes ~2s attempting haiku before falling to opus. Should be moved to end of cascade or removed. |
| K2 | **Cycle duration 17.6 min vs 5 min target** | Medium | 5 replies × 150s token bucket = ~750s just in rate limit waits. Either reduce `max_comment_replies_per_cycle` to 2-3, or implement separate token buckets for posts vs comments. |
| K3 | **Dedup 166 rows at startup** | Low | After P2-2 fix (24h TTL cleanup), the cleanup may be running after the scan instead of before. Verify execution order in Phase B. |
| K4 | **⟦HL⟧ tagged posts being selected** | Low | Moltbook feed returns posts with highlighting markup `⟦HL⟧...⟦/HL⟧`. These get low scores but pass cold start (min_score=1). Consider filtering posts where >20% of body is HL tags. |
| K5 | **Energy intel not yet enhanced** | Medium | Current scrapers only detect papers/patents. Funding, VC tracking, technology radar, and weekly strategic digest are designed but not yet implemented (prompt prepared). |

### MONITORED — Acceptable Risk

| # | Issue | Why Acceptable |
|---|-------|----------------|
| M1 | Single-model dependency (deepseek-chat) | Working reliably. Would be critical if DeepSeek starts failing. Telegram balance alert will warn when funds run low. |
| M2 | OLLAMA_FALLBACK returns "" | Agent goes silent instead of publishing garbage. Acceptable trade-off. Monitor for consecutive 0-reply cycles. |
| M3 | tier_sonnet = gemini-2.5-flash (same as tier_opus was) | Not a problem since tier_opus is now deepseek-chat. But if opus is changed back, they'd duplicate. |

---

## 6. PENDING ROADMAP (v5.0+)

### Phase A: Short-Term (Immediate)
1. **Implement energy intel evolution** — scrapers for DOE ARPA-E, NSF, EU Horizon, VC funds, accelerators. Technology radar with TRL tracking. Weekly strategic digest. (Prompt already prepared in `PROMPT_KIRO_Energy_Intel_Evolved.md`)
2. **Move tier_haiku to end of cascade** — saves ~2s per LLM call (currently 7 wasted attempts per cycle)
3. **Reduce max_comment_replies_per_cycle to 3** — brings cycle duration from ~18 min to ~8 min

### Phase B: Medium-Term
4. **Separate token buckets** — posts and comments should have independent rate limits
5. **Reply quality feedback loop** — track upvotes/karma on replies, feed back into Phase C for self-improvement
6. **HL tag filtering** — filter or clean ⟦HL⟧ markup from feed posts before scoring

### Phase C: Long-Term (v5.0)
7. **Multi-platform support** — abstract MoltbookAPIClient behind a platform interface
8. **A/B testing framework** — currently exists as experiment assignments but lacks statistical analysis
9. **Topic evolution engine** — Phase C should detect trending topics and auto-adjust the content strategy
10. **Financial intelligence module** — the energy intel evolution should culminate in automated grant application drafting, proposal outlines, and funder matching

---

## 7. PERSONALITY AND BEHAVIOR

The agent communicates in **English** on Moltbook. Logs are in **Spanish**. It has 5 communication modes defined in `modes.py`:

| Mode | Style | Use Case |
|------|-------|----------|
| architect | Systems-thinking, trade-off focused | Technical infrastructure posts |
| historian | References past work, draws parallels | Academic/historical topics |
| scientist | Data-driven, methodical | Research papers, empirical claims |
| pragmatist | Practical, action-oriented | How-to, tooling, deployment |
| provocateur | Contrarian, challenges assumptions | Hot takes, debate starters |

**SYSTEM_PROMPT** and **AGENT_CHARTER** are in `prompt_templates.py`. The agent's identity is a technical AI researcher focused on agent reliability, observability, and infrastructure — not a general-purpose chatbot.

---

## 8. ENERGY INTELLIGENCE MODULE — Current State & Evolution Plan

### Current State
- `energy_intel_node.py` is a **standalone FastAPI application** with CLI scrapers
- Scrapes: arXiv, Google Scholar, energy news sources
- Produces "claims" with title, source, metrics, URL
- **Integrated into agent cycle** via `services/energy_intel_telegram.py` (1x/hour in Phase C)
- Currently sends Telegram alerts for "frontier technology" claims (max 3 per run)
- Filter categories: solid-state-battery, perovskite-solar, fusion, thermophotovoltaic, flow-battery

### Evolution Plan (Not Yet Implemented)
A comprehensive prompt exists at `PROMPT_KIRO_Energy_Intel_Evolved.md` that specifies:
- **Funding scrapers**: DOE ARPA-E, DOE SBIR/STTR, EU Horizon Europe, NSF
- **VC tracking**: Crunchbase, TechCrunch, Climate Tech VC
- **Technology Radar** (`services/tech_radar.py`): TRL tracking, signal counting, trend detection
- **3-tier Telegram alerts**: 💰 Funding (high priority), 🔬 TRL changes (medium), 🏦 VC activity (low)
- **Weekly Strategic Digest**: auto-generated every Monday with recommendations
- **Filing Deadline Tracker**: calendar of active funding opportunities

### Strategic Vision
The user's stated goal: *"convertirnos en unos expertos en finanzas, proyectos y demás para captar recursos y ampliar nuestras capacidades."* The energy intel module should evolve from passive detection to **active resource capture**: identifying where the money is, who funds what, and how to apply.

---

## 9. DATA FILES

| File | Format | Purpose |
|------|--------|---------|
| `comet_state.db` | SQLite | Global state: cycle count, posts_today, comments_today, consecutive_failures |
| `comet_dedup.db` | SQLite | Reply dedup fingerprints (24h TTL cleanup) |
| `published_posts.json` | JSON | Own published posts tracker |
| `research_agenda.json` | JSON | Phase C topic agenda |
| `topic_matrix_state.json` | JSON | Topic rotation state (rotation_window=6) |
| `claims_tracker.json` | JSON | Claim tracking per reply |
| `dual_scores.jsonl` | JSONL | Dual scoring wire checks |
| `self_diagnosis.jsonl` | JSONL | Self-diagnostic data |
| `last_balance_check.txt` | Text | Timestamp of last DeepSeek balance Telegram send |
| `last_energy_intel_run.txt` | Text | Timestamp of last energy intel execution |
| `filing_deadlines.json` | JSON | (Planned) Active funding opportunity deadlines |
| `tech_radar_state.json` | JSON | (Planned) Technology readiness tracking |
| `weekly_digest_YYYY-MM-DD.md` | Markdown | (Planned) Weekly strategic digest |

---

## 10. WORKING WITH THIS CODEBASE

### Running the Agent
```powershell
cd C:\comet-riobamba-v31
python run_agent.py
```

### Running Tests
```powershell
cd C:\comet-riobamba-v31
python -m pytest tests/ -v
```

### Key Patterns
- **Dependency injection**: `PhaseBDeps` container in `deps.py`, constructed in `core/agent.py`
- **Circuit breakers**: `utils/resilience.py` — CLOSED→OPEN→HALF_OPEN, timeouts: 3600s (429), 300s (4xx), 60s (default)
- **Observability events**: `observability EVENT <name> | {"key": "value"}` — structured JSON for each significant action
- **Wire checks**: Files written at key decision points for debugging (`self_diagnosis.jsonl`, `dual_scores.jsonl`, `claims_tracker.json`)
- **Rate limiter**: Token bucket in `services/moltbook.py`, 1 token per 150s, shared across all write operations
- **Comment outbox**: `data/comment_outbox.json` — pending comments are retried at cycle start before Phase A

### Code Conventions
- Agent logs in **Spanish**, code in **English**
- All LLM prompts in **English**
- System prompts and personality in **English**
- Error messages and user-facing text in **Spanish**
- Commit messages descriptive, one per fix