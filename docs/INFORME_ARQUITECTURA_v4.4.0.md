# 📊 INFORME EXHAUSTIVO — COMET-RIOBAMBA v4.4.0

> Generado: 2026-06-29 | Auditoría completa del repositorio post-refactorización

---

## 7.1 RESUMEN EJECUTIVO

**COMET-RIOBAMBA** es un agente autónomo Python que opera en Moltbook (plataforma social de agentes AI). Ejecuta ciclos de 5 minutos con 3 fases: genera posts técnicos (A), responde a la comunidad (B), y auto-optimiza (C). Usa una cascada de 8 proveedores LLM (DeepSeek → Gemini → Groq → OpenRouter → Cerebras → Ollama) con circuit breakers. Tiene 228+ tests pasando, Telegram integrado para control remoto, y un pipeline de distribución a LinkedIn/Twitter.

**Stack**: Python 3.14, SQLite (WAL), REST API (Moltbook), requests, sklearn, pytest.

**3 problemas críticos resueltos en v4.4.0:**
1. CAPTCHA solver siempre extraía "32 + 8" → Reescrito con deobfuscation + word parsing + LLM fallback
2. Phase B monolito (2724 LOC) → Convertido a paquete con constants.py + scoring.py + candidate_scorer.py
3. Token bucket compartido (1 write/150s) → Separado: posts=300s, comments=60s, actions=30s

**Problemas residuales:**
1. `energy_intel.db` y `EIN.docx` aún en raíz (locked por otro proceso)
2. Phase B orchestrator sigue siendo ~2500 LOC (clase PhaseB no se partió en métodos separados)
3. No hay CI/CD — los 228 tests se corren manualmente

---

## 7.2 ARQUITECTURA

```
┌─────────────────────────────────────────────────────────────────┐
│                    run_agent.py (entrypoint)                      │
│                         ↓                                        │
│              core/agent.py (COMETRiobambaAgent)                  │
│                    ┌────┼────┐                                   │
│                    ↓    ↓    ↓                                   │
│    ┌──────────┐ ┌──────────┐ ┌──────────────┐                   │
│    │ Phase A  │ │ Phase B  │ │   Phase C    │                   │
│    │ Content  │ │ Replies  │ │  Analytics   │                   │
│    │ 743 LOC  │ │ 2500 LOC │ │   620 LOC   │                   │
│    └────┬─────┘ └────┬─────┘ └──────┬───────┘                   │
│         │            │               │                           │
│    ┌────┴────────────┴───────────────┴────┐                     │
│    │         services/ (42 modules)        │                     │
│    │  model_cascade │ moltbook_api_client  │                     │
│    │  dedup_store   │ telegram_client      │                     │
│    │  claim_checker │ topic_evolution      │                     │
│    │  reply_feedback│ content_distributor  │                     │
│    │  telegram_ctrl │ content_curator      │                     │
│    └──────────────────────────────────────┘                     │
│                         ↕                                        │
│    ┌──────────────────────────────────────┐                     │
│    │    data/ (SQLite + JSONL + JSON)      │                     │
│    │  comet_state.db │ comet_dedup.db      │                     │
│    │  published_posts│ claims_tracker      │                     │
│    └──────────────────────────────────────┘                     │
└─────────────────────────────────────────────────────────────────┘
```

### Ciclo de vida completo

```
Startup
  → Load .env + Credentials
  → Init ModelCascade (8 providers + circuit breakers)
  → Init MoltbookAPIClient (3 token buckets)
  → Init TelegramClient
  → Check pause flag (data/.agent_paused)
  → Send DeepSeek balance (1x/day)

Cycle Loop (every 300s):
  → Phase A: Topic selection → Dedup check → LLM generation → Validation → Publish → CAPTCHA verify
  → Phase B: Own-post replies → Feed replies (ranked by candidate_scorer) → Quality gate → Publish
  → Phase C (periodic): Analytics → Reply feedback → Topic evolution → Energy Intel → Distribution → Briefing

  → Log cycle summary → Telegram notify (if activity) → Sleep
```

### Módulos con responsabilidad

| Directorio | Archivos activos | Responsabilidad |
|-----------|-----------------|-----------------|
| `core/` | 15 | Orquestación, estado, métricas, health, tracing, claims |
| `phases/phase_b/` | 4 (package) | Replies: constants, scoring, candidate_scorer, orchestrator |
| `phases/` | 6 adicionales | Phase A content, Phase C analytics, engagement sub-package, deps |
| `services/` | 42 | LLM cascade, API client, dedup, telegram, feedback, distribution, curator |
| `utils/` | 6 | Circuit breaker, validators, formatters, phase error boundary |
| `config/` | 5 activos | Policy, credentials, identity, persona, topic_matrix |
| `prompts/` | 3 | Templates: system, posts, replies, value classifier |
| `personality/` | 1 | 5 communication modes (architect, empiricist, historian, provocateur, synthesizer) |

---

## 7.3 INVENTARIO DE PROMPTS

| Archivo | Fase | Rol | Objetivo | Variables |
|---------|------|-----|----------|-----------|
| `prompts/prompt_templates.py` SYSTEM_PROMPT | A | System | Identidad core para generación | `{min}`, `{max}`, `{hook}` |
| `prompts/prompt_templates.py` POST_TEMPLATE_CONTRARIAN | A | User | Template para posts research mode | `{topic_area}`, `{hook_requirement}`, `{forbidden_topics}`, `{min}`, `{max}` |
| `prompts/prompt_templates.py` REPLY_TEMPLATE | B | User | Template para feed replies | `{title}`, `{content}`, `{min}`, `{max}` |
| `prompts/prompt_templates.py` DEBATE_CONTINUATION_TEMPLATE | B | User | Continuación de debates | `{title}`, `{content}`, `{thread_history}` |
| `phases/phase_b/constants.py` COMMENT_STYLE_INSTRUCTIONS | B | System suffix | 9 reglas + forbidden openers + good/bad examples | Ninguna |
| `phases/phase_b/orchestrator.py` system_prompt (L~1484) | B | System | Estructura ANCHOR→EVIDENCE→FRAMEWORK + response angles A-E | `{lang_instruction}`, `{COMMENT_STYLE_INSTRUCTIONS}` |
| `phases/phase_a_content.py` EDITORIAL_CONFIG | A | Config | Mission + 10 core principles (CLAIM→EVIDENCE→LIMIT→IMPLICATION) | Ninguna |
| `config/agent_identity.json` | Global | Config | Bio, tagline, anti-patterns, topic verticals | Ninguna |
| `personality/modes.py` COMMUNICATION_MODES | B | System modifier | 5 modos con tone + structural_rules + forbidden por modo | Ninguna |
| `core/challenge_solver.py` SOLVER_PROMPT | Verification | System | Solver de CAPTCHA matemático ofuscado | `{challenge_text}` |

### Prompt principal de Phase A (mission):
```
"You are a field engineer who operates autonomous agent systems in production.
You write dispatches about what you observe, what breaks, and what you fixed."
```

### Prompt principal de Phase B (feed replies):
```
"You are a senior systems engineer who publishes original research.

RESPONSE FORMAT (mandatory structure):
1. ANCHOR: Quote or reference one specific claim from the post (1 sentence).
2. EVIDENCE: State what you measured, observed, or built (1-2 sentences).
3. FRAMEWORK: Propose a pattern, architecture change, or design principle (1-2 sentences).
4. EDGE CASE (optional): Name one failure mode or counter-example (1 sentence).

HARD CONSTRAINTS:
- Every reply MUST contain at least one concrete number, metric, or threshold.
- Every reply MUST propose or name a pattern/framework/architecture explicitly.
- Maximum 4 sentences. Density over length."
```

---

## 7.4 CONFIGURACIÓN ACTUAL

| Variable | Valor | Fuente |
|----------|-------|--------|
| `max_posts_per_day` | 6 | POLICY + .env |
| `max_comment_replies_per_cycle` | 6 | POLICY + .env |
| `max_comments_per_post` | 10 | POLICY + .env |
| `max_feed_comments_per_post` | 5 | POLICY |
| `max_feed_initiations_per_day` | 6 | POLICY |
| `max_feed_replies_per_day` | 20 | .env override |
| `max_comments_per_day` | 30 | POLICY |
| `disengage_after_no_value_replies` | 2 | POLICY |
| `max_thread_depth` | 5 | POLICY |
| `cycle_interval_seconds` | 300 | .env |
| `MOLTBOOK_POST_RATE_LIMIT_SECONDS` | 300 | moltbook_api_client default |
| `MOLTBOOK_COMMENT_RATE_LIMIT_SECONDS` | 60 | moltbook_api_client default |
| `MOLTBOOK_ACTION_RATE_LIMIT_SECONDS` | 30 | moltbook_api_client default |
| `MODEL_TIER_OPUS` | deepseek-chat | .env |
| `MODEL_TIER_SONNET` | gemini-2.5-flash | .env |
| `MODEL_TIER_HAIKU` | gemini-2.0-flash (circuit OPEN) | .env (last in cascade) |
| `GROQ_MODEL` | llama-3.3-70b-versatile | .env |
| `CEREBRAS_MODEL` | llama-3.3-70b | .env |
| `OLLAMA_MODEL` | qwen2.5:3b | .env |
| `COLD_START_MIN_SCORE` | 3 | .env |
| `TELEGRAM_ALERTS_ENABLED` | 1 | .env |
| `TELEGRAM_DAILY_REPORT` | 1 | .env |
| `POST_RATE_LIMIT_SECONDS` (write_policy) | 300 | env default |
| `COMMENT_RATE_LIMIT_SECONDS` (write_policy) | 120 | env default |

### Modelo de cascada (orden de intento):
```
1. tier_opus      (deepseek-chat)       ← Primary
2. tier_sonnet    (gemini-2.5-flash)    ← Fallback
3. openrouter     (gpt-oss-120b:free)   ← Free fallback
4. tier_haiku     (gemini-2.0-flash)    ← Quota=0, last resort
5. cerebras       (llama-3.3-70b)       ← Fast fallback
6. groq           (llama-3.3-70b)       ← Ultra-fast
7. ollama_local   (qwen2.5:3b)          ← Local
8. ollama_native  (qwen2.5:3b /api/gen) ← Native endpoint
```

---

## 7.5 SISTEMA DE MEMORIA

| Store | Tipo | Ubicación | Contenido | TTL |
|-------|------|-----------|-----------|-----|
| Agent state | SQLite | `data/comet_state.db` | cycle_count, posts_today, comments_today, outbox, flags | Permanent |
| Dedup store | SQLite | `data/comet_dedup.db` | replied_comments, commented_posts, agent_comments, upvoted, followed | 24h (replied/fingerprint), 7d (commented), permanent (upvoted/followed) |
| Published posts | JSON | `data/published_posts.json` | post_id, topic, body, published_at | Permanent (append-only) |
| Claims tracker | JSON | `data/claims_tracker.json` | claims with text, cluster, reinforcement_count, evolution_stage | Permanent (purged of clichés at startup) |
| Topic history | JSON | `data/topic_history.json` | Last 50 topics used (dedup) | Rolling 50 |
| Reply strategy | JSON | `data/reply_strategy_hint.json` | best/worst content types from dual_score analysis | Recomputed weekly |
| Topic evolution | JSON | `data/topic_evolution_state.json` | Series of 3-post evolution chains from mature claims | Permanent |
| Dual scores | JSONL | `data/dual_scores.jsonl` | content_type + composite score per reply | Append-only |
| Cascade telemetry | JSONL | `data/cascade_telemetry.jsonl` | provider, tier, latency_ms, success per LLM call | Append-only |
| Self-eval | JSON | `data/self_eval_state.json` | Daily metrics: comments, upvotes, follows, searches | Per-day keys |
| Energy intel | SQLite | `data/energy_intel.db` | Claims from papers/patents/press (ArXiv, USPTO, CleanTechnica) | Permanent |
| Distribution queue | JSON | `data/distribution_queue.json` | Posts selected for LinkedIn/Twitter repurposing | Overwritten daily |
| Balance check | TXT | `data/last_balance_check.txt` | Date of last DeepSeek balance notification | Overwritten daily |
| Telegram briefing | JSON | `data/telegram_briefing_state.json` | Timestamp of last daily briefing | Overwritten daily |
| Agent pause | Flag file | `data/.agent_paused` | Exists = paused (via Telegram /pause) | Deleted on /resume |

---

## 7.6 PROBLEMAS DETECTADOS

| Problema | Archivo | Severidad | Estado |
|----------|---------|-----------|--------|
| `energy_intel.db` in root (should be data/) | raíz | Low | Blocked by file lock |
| `EIN.docx` in root (should be docs/ein/) | raíz | Low | Blocked by Word lock |
| Phase B orchestrator ~2500 LOC single file | `phases/phase_b/orchestrator.py` | Medium | Acceptable (methods too coupled) |
| No CI/CD pipeline | — | Medium | Manual pytest only |
| BOM characters reappear on file edits | Multiple | Low | Editor config issue |
| `_lab/` and `exports/` empty dirs in root | raíz | Trivial | Can delete |
| Test data accumulated in production dedup DB | `data/comet_dedup.db` | Low | Cleanup with DedupStore.cleanup() |
| README.md outdated (says 78 tests, actually 228) | `README.md` | Low | Update text |

---

## 7.7 PUNTOS DE EXTENSIÓN

| Extensión | Archivo | Función/Punto | Cómo modificar |
|-----------|---------|---------------|----------------|
| **Rotación temática** | `phases/phase_a_content.py` | `_is_topic_recently_used()` | Ya implementado. Ajustar `_TOPIC_COOLDOWN_POSTS` o threshold 0.6 |
| **Selección de agentes target** | `phases/phase_b/candidate_scorer.py` | `score_comment(known_debaters=...)` | Populate `known_debaters` from engagement tracker |
| **Distribución por submolts** | `phases/phase_b/orchestrator.py` | `ALLOWED_SUBMOLTS`, `BLOCKED_SUBMOLTS` | Modify sets |
| **Nuevos tipos de comment** | `phases/phase_b/constants.py` | `COMMENT_STYLE_INSTRUCTIONS` | Add new rules or response angles |
| **Nuevas fuentes RSS** | `services/energy_intel_telegram.py` | `_FUNDING_FEEDS`, `_TECH_RADAR_FEEDS` | Add URLs |
| **Nuevos LLM providers** | `services/model_cascade.py` | `_load_providers()` | Add ProviderConfig with env vars |
| **Nuevas plataformas** | `services/platform_client.py` | Implement `PlatformClient` ABC | Create new client inheriting interface |
| **Topic evolution series** | `services/topic_evolution.py` | `_generate_series_entries()` | Modify angles or series length |
| **Telegram commands** | `services/telegram_control.py` | `handle_command()` | Add elif + handler function |
| **A/B experiments** | `services/experiments.py` | `record_result()` + `analyze_experiment()` | Create experiment config in `data/experiments.json` |
| **Content curation rules** | `services/content_curator.py` | `_ACTIONABLE_SIGNALS`, `_META_SIGNALS` | Add/remove signal lists |
| **Scientific value gate** | `phases/phase_b/scoring.py` | `SCIENCE_SIGNALS`, `LOW_VALUE_SIGNALS` | Add terms to frozensets |
| **Quality gate signals** | `phases/phase_b/orchestrator.py` | `_passes_quality_gate()`, `_meets_minimum_quality()` | Modify signal lists |
| **Safety filters** | `phases/phase_b/orchestrator.py` | `_safe_publish_comment()` | Add checks before publish |
| **Daily briefing content** | `services/telegram_control.py` | `generate_daily_briefing()` | Add sections to briefing |

---

## 7.8 RECOMENDACIONES PRIORIZADAS

| # | Acción | Impacto | Esfuerzo | Estado |
|---|--------|---------|----------|--------|
| 1 | ~~CAPTCHA solver rewrite~~ | Crítico | Medio | ✅ Done (P0-1) |
| 2 | ~~Separar rate limiters~~ | Alto | Bajo | ✅ Done (Prompt 5) |
| 3 | ~~Quality gate + safety filters~~ | Alto | Medio | ✅ Done (Prompt 15) |
| 4 | ~~Editorial overhaul~~ | Alto | Bajo | ✅ Done (Prompt 16) |
| 5 | ~~Topic dedup~~ | Alto | Bajo | ✅ Done (Prompt 21) |
| 6 | ~~Company-deployment pattern ban~~ | Alto | Bajo | ✅ Done (Prompt 21) |
| 7 | ~~Claims self-cliché filter~~ | Medio | Bajo | ✅ Done (Prompt 21) |
| 8 | ~~Telegram control center~~ | Medio | Medio | ✅ Done (Prompt 20) |
| 9 | ~~Scientific value gate~~ | Medio | Bajo | ✅ Done (Prompt 19) |
| 10 | Add GitHub Actions CI | Medio | Bajo | **Pendiente** |
| 11 | Engagement-based topic weighting | Medio | Medio | Infrastructure ready |
| 12 | Reddit/HN client via PlatformClient | Alto | Alto | Interface ready |
| 13 | Update README.md (78→228 tests, new commands) | Low | Trivial | **Pendiente** |

---

## APÉNDICE: Archivos clave para orientación rápida

```
LEER PRIMERO:
  core/agent.py                    — Loop principal, orchestration (938 LOC)
  phases/phase_b/orchestrator.py   — Replies monolith (2500 LOC)  
  phases/phase_b/constants.py      — FORBIDDEN_PHRASES + COMMENT_STYLE
  phases/phase_a_content.py        — Post generation + editorial config
  services/model_cascade.py        — LLM cascade con circuit breakers
  services/moltbook_api_client.py  — API client + rate limiters
  config/agent_policy.py           — Todos los límites numéricos
  config/agent_identity.json       — Bio + personalidad

TESTING:
  pytest tests/ -x -q              — Run all 228 tests
  pytest tests/test_claim_checker.py -v  — Claims pipeline
  pytest tests/test_phase_b_wiring.py -v — Phase B integration

OPERATION:
  python run_agent.py              — Start agent
  .\run-prod.ps1                   — Production (with lock file)
  Telegram: /stats /health /pause /resume /next /claims
```
