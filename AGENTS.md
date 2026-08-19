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

### Monitoreo en tiempo real (watchdog, 18/08/2026) — LEER ANTES DE ACTUAR
- **Al inicio de cualquier sesión/tarea, correr `.\monitoring\status.ps1`**
  (o leer `monitoring/latest.json` + `monitoring/watchdog-state.json`) y ACTUAR
  sobre las alertas pendientes antes de tocar código. El operador quiere que
  tanto él (Telegram) como el asistente lean los avisos para actuar de inmediato.
- **`monitoring/watchdog.py`**: proceso continuo (tick 60s) que vigila:
  agente vivo (auto-reinicio si cayó sin stop.flag, cooldown 30 min, máx 2/h),
  circuitos LLM (3+ fallos/10 min en `data/cascade_telemetry.jsonl`), errores
  de log (1h), modo degradado, saldos DeepSeek/OpenRouter (15 min), fallos de
  Telegram (reintenta `data/telegram_outbox.json`), inactividad de publicación.
  - Estado: `monitoring/watchdog-state.json` · Alertas: `monitoring/alerts.jsonl`
    (compartido con health-check.ps1 → cooldown único, sin spam) · Log:
    `logs/watchdog.log` · Lock: `.watchdog.lock` (creación atómica O_EXCL).
  - El AGENTE supervisa al watchdog: `_maybe_supervise_watchdog()` en
    `core/agent.py` lo relanza si su lock está muerto (intervalo 300s, env
    `WATCHDOG_SUPERVISION_S`). El guard `monitoring/guard-watchdog.ps1`
    (Task Scheduler `COMET-WatchdogGuard`, cada 5 min) es la tercera capa.
  - **Reinicio del agente (18/08/2026)**: `decide_restart()` en watchdog.py
    reinicia SOLO si el lock-PID está muerto (autoridad; el lock solo se
    limpia al salir el proceso). NO reiniciar por staleness de health.json
    (<2h): los ciclos duran ~8 min y con waits de publicación/retries pueden
    pasar de 10 min → causaba falsos "Auto-reinicio" (alerta engañosa, no-op
    real por el guard singleton de run-prod.ps1). Seguridad: lock vivo +
    health >7200s = agente colgado → sí reiniciar.
  - Auto-reinicio del agente: `run-prod.ps1` (aislado, respeta stop.flag).
- **Ledger Telegram**: `monitoring/telegram-ledger.jsonl` registra TODO lo
  enviado al móvil (ts, método, ok, texto) — `services/telegram_client.py`
  lo escribe en `_send`; el watchdog escribe los suyos también. Para saber
  qué recibió el operador: leer ese ledger (o el final de
  `monitoring/telegram-sent.log`).
- **No duplicar**: el watchdog solo re-alerta en transiciones (p. ej. saldo
  bajo entra una vez, circuitos al abrir/recuperar). No crear más avisos por
  tick. Los cooldowns del health-check (`alert-critical`/`alert-warning`,
  60 min) marcan sus envíos en alerts.jsonl — respetarlos.
- **health-check.ps1 (18/08/2026)**: la autoridad para "agente vivo" es el
  PID de `.agent.lock` (el CIM no ve procesos de otra sesión y los ciclos
  duran ~7 min, así que health.json puede tener hasta ~7 min de edad). No
  revertir a buscar solo procesos `run_agent.py` ni a tolerancias < 15 min.
  Circuitos en health-check: un tier cuenta como abierto solo con >=3
  fallos/10 min Y ningún proveedor con éxito en la ventana (cascada caída
  del todo); el fallback deepseek-directo→openrouter es ruido esperado.
  No parsear `[DateTime]::Parse($obj.ts)` — ConvertFrom-Json ya lo
  convirtió (el re-parse en formato local explota).
- **Phase A weekly limit**: `data/editorial_policy.json`
  `publication_policy.max_posts_per_week=105` alineado a 15/día del `.env`
  (`AGENT_MAX_POSTS_PER_DAY`). La ventana es DESLIZANTE 7d
  (`count_posts_since(7)`): si se vuelve a subir el diario, subir también
  el semanal (7x) o Phase A se congela en "limite semanal alcanzado".
  Síntoma: 0 posts con `Phase A: limite semanal alcanzado (X/X)`.
- **ATENCIÓN (tests)**: `pytest tests/` sobrescribe `data/state/health.json`
  (cycle=1) y otros archivos de estado reales; el agente los reescribe en su
  próximo ciclo (~60s). No alarmarse por "ciclos=1" tras una corrida de tests.

## Run

| Task | Command |
|------|---------|
| Dev | `python run_agent.py` |
| Prod | `.\run-prod.ps1` |
| Watchdog | `.\run-watchdog.ps1` (guard automático: Task Scheduler `COMET-WatchdogGuard`) |
| Estado/alertas | `.\monitoring\status.ps1` |
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
