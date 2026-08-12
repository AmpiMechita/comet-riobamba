# COMET-RIOBAMBA — Agent Guidance

## Estado Vivo Actual (v5.2+) — LEER PRIMERO

> Esta sección es la fuente de verdad operativa. Si algún doc antiguo (v5.0/v5.1
> "Sniper Técnico", README, ARCHITECTURE.md) la contradice, esto gana.
> Última actualización: 2026-08-12, cubre los commits be02c3c→bbeca4f.

### Identidad
- COMET-RIOBAMBA es un **inventor**, no un erudito que cita/recita.
- Misión: construir tecnología nueva a partir de literatura + comunidad.
- **Regla anti-fabricación:** *"Invent the mechanism, never the evidence."*
  Nunca inventar un resultado concreto o war-story ("caught 3 cases in two
  weeks", "ran for 30 days") salvo que sea un número real de los propios datos.
- Voz: ampliada con referencias reales y contexto; **sin** template rígido de
  4 pasos (commit 206cfd1).

### Estrategia
- **Post-pairing con watchlist** (`phases/phase_b/orchestrator.py`): cada reply
  exitosa a un autor watchlist registra un topic `watchlist_pairing` (counter-claim)
  para que Fase A publique un refute 6-24h después.
- **CTA generativo**: replies a autores watchlist (tier_quality) cierran con una
  pregunta de co-diseño provocadora sobre el threshold central.
- **Prioridad máxima** en `choose_topic`: topics watchlist_pairing valen 2 vs 1.
- **Métrica inbound**: `data/watchlist_inbound_today.json` cuenta referentes que
  comentan en posts de COMET; objetivo >0/día; se muestra en el cycle summary.

### Límites operativos reales (v5.2+)
- **Libre albedrío**: caps de comportamiento eliminados; la comunidad decide.
- **Anti-baneo**: token bucket en `MoltbookAPIClient` (~1 write/150s) + rate
  limiter de modelos (45 rpm).
- Valores de producción en `.env`:
  - `AGENT_MAX_POSTS_PER_DAY=15`
  - `AGENT_MAX_COMMENTS_PER_DAY=300`
  - `AGENT_MAX_COMMENTS_PER_POST=30`
  - `AGENT_FEED_BUDGET_PCT=25` (25% del presupuesto diario a feed ajeno, 75% a posts propios)
- Defaults de `config/agent_policy.py` sin .env: max_comments_per_day=150,
  feed_budget_pct=40. **Siempre verificar `.env` antes de asumir valores.**
- **Anti-dogpile (3/3) aplica SOLO a posts ajenos del feed**; posts propios con
  debate activo usan `skip_anti_dogpile=True` (commit 2ec4f41).

### Fixes clave que NO regresar
- **Dedup inbound** (f1197db): `watchlist_inbound` no infla conteo por re-scan de posts.
- **Parser karma real** (489a074): `fetch_home_dashboard` normaliza
  `your_account.karma`, `your_account.unread_notification_count` y
  `activity[].latest_commenters`. El agente creía karma=0 cuando era 2204.
  **Nunca** leer campos planos.
- **Alto valor en scoring** (be02c3c): comentarios de autores watchlist o con
  historial real se responden pese a baja densidad (capital de relación, no ruido).

### Directrices para el modelo ayudante (opencode/claude)
- NO regresar a la voz antigua de "erudito citador" ni al template rígido.
- NO reintroducir caps viejos (12 comments/día, "Sniper Técnico", límites de 3 por autor).
- NO "arreglar" el parser de karma a campos planos.
- Al proponer configs: respetar libre albedrío + anti-baneo; consultar `.env`.

## Run

| Task | Command |
|------|---------|
| Dev | `python run_agent.py` |
| Prod | `.\run-prod.ps1` |
| Stop (graceful) | `New-Item data/stop.flag` |
| All tests | `pytest tests/ -q` |
| Single test | `pytest tests/test_phase_b_dedup_limits.py -v` |
| Daily report | `python -m scripts.print_daily_report` |
| Historical metrics | `python -m scripts.metrics_last_n_days` |

## Architecture

- **Entrypoint:** `run_agent.py` → `core.agent.main()`, **not** `agent.py` at root (that file does not exist).
- **Not a standard package.** No `pyproject.toml`, `setup.py`, or `setup.cfg`. Dependencies: `python-dotenv`, `requests`, `pyyaml`, `pytest`.
- **State persistence:** Two SQLite databases: `data/comet_state.db` (agent_state, outbox) via `services/persistence.py`, and `data/comet_dedup.db` (Phase B dedup sets/dicts) via `services/dedup_store.py`.
- **Model cascade:** `services/model_cascade.py` — providers tried in order: `ollama_local` → `tier_opus` → `tier_sonnet` → `tier_haiku` → `openrouter` → `cerebras` → `ollama_cloud`. Circuit breaker per provider.
- **Phase B** is monolithic (`phases/phase_b.py`). **Phase C** is split: `phases/phase_c_analytics.py` + `phases/engagement/` sub-package.

## Critical Toggles

- **Graceful stop (no OS signals):** create the file `data/stop.flag` (e.g. `New-Item data/stop.flag`). The agent detects it on its next check (max 1s latency) and shuts down cleanly, including final state save. The flag is auto-deleted so it does not linger for the next startup. Preferred on Windows, where sending SIGINT/CTRL_BREAK to a background child process is unreliable.
- **Whisper mode** (`config/config.py` or env `AGENT_WHISPER_MODE=1`): when True, all Moltbook API calls are simulated. Used for lab/dev. Toggle via env var or editing `config/config.py` line 71.
- **Auto-pause:** after 3 consecutive post failures the agent pauses itself (`behavior_cfg["auto_pause_after_failures"]`).
- **Rate limiter:** token bucket in `MoltbookAPIClient`, 1 write per 150s default.

## File Conventions

- **Never modify** `.bak`, `.backup`, `.broken-*`, `.pre-*`, `.bak-*` files. These are historical snapshots (dozens exist across `core/`, `phases/`, `services/`, `config/`).
- **Never commit** `.env` (contains real API keys — already in `.gitignore`).
- **Phase A** rejects non-English content (Spanish keyword detection + `_is_mostly_english()` check).
- **Phase B cold start:** lower relevance threshold until agent has published ≥10 posts (`COLD_START_POST_THRESHOLD`).

## Testing & Quality

- No CI/CD pipelines, no linter config, no type checker config. `pytest` runs with defaults.
- 61 test files, ~962 tests total. No external services required for tests.

## Existing Context

- `CLAUDE.md` covers team conventions, stack, and LLM model recommendations.
- `README.md` covers env vars and quick start.
- `ARCHITECTURE.md` documents the v5.0 design.
