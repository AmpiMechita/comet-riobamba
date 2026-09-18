<!--
AVISO 2026-09-17: El watchdog (monitoring/watchdog.py + guard-watchdog.ps1 +
health-check*.ps1 + run-watchdog.ps1) fue RETIRADO por generar falsos
positivos de reinicio y duplicar la supervision del proceso padre.
Las referencias mas abajo son historicas.
-->
<!--
AVISO DE DESACTUALIZACION - 2026-09-11
Los valores de configuracion en este documento NO reflejan la realidad.
Fuente de verdad: docs/CONFIG_TRUTH.md + config/config.py + .env
Este documento se conserva por valor historico, no como referencia tecnica.
-->
# COMET-RIOBAMBA — Agent Guidance

## Estado Vivo Actual (v5.2+) — LEER PRIMERO

> Esta sección es la fuente de verdad operativa. Si algún doc antiguo (v5.0/v5.1
> "Sniper Técnico", README, docs/ARCHITECTURE.md) la contradice, esto gana.
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
### Anti-Dogpile (3/3) y `skip_anti_dogpile`

**¿Cómo funciona?**
El mecanismo de anti-dogpile está diseñado para prevenir que el agente publique
múltiples replies idénticos o muy similares en posts ajenos del feed, lo que
podría percibirse como spam o comportamiento de bot.

Por defecto, el anti-dogpile tiene un techo de `max_replies_per_post` (default 3)
por post. Este límite es estricto y **no tiene exenciones** para `is_followup`
o `skip_anti_dogpile`.

**Uso de `skip_anti_dogpile=True`**
El parámetro `skip_anti_dogpile=True` está reservado para casos legitimados:

1. **Posts propios con debate activo**: Cuando el agente responde a sus propios
   posts publicados anteriormente. Esto está permitido porque:
   - El agente ya tiene una relación establecida con el autor
   - El debate es parte natural de la conversación
   - Evita bloquear la propia evolución del hilo

   **Condiciones para aplicar legitimamente (todas deben cumplirse):**
   - El post debe ser del agente propio (`own_post=True`)
   - Debe haber al menos 3 replies sustantivas previas en el hilo
   - Las replies deben tener contenido real (no URLs vacías, >20 chars)
   - No debe haber patrón de spam en el hilo

   Cuando estas condiciones se cumplen, el agente establece
   `skip_anti_dogpile=True` automáticamente en `_safe_publish_comment`.

2. **Uso explícito por desarrollador**: En casos raros, un desarrollador puede
   setear manualmente `skip_anti_dogpile=True` en el código, pero esto debe
   hacerse con extrema cautela y revisión.

**Riesgos y advertencias**
⚠️ **ADVERTENCIA**: El uso indebido de `skip_anti_dogpile=True` en posts propios
sin cumplir las condiciones arriba mencionadas puede:
- Evitar el control de flood diseñado para proteger la salud del feed
- Generar replies repetitivos que degradan la experiencia del usuario
- Hacer que el agente parezca un bot de spam
- Violar los términos de servicio de Moltbook

Si `skip_anti_dogpile=True` se usa en posts propios sin las condiciones de debate
activo, el sistema logging marcará un warning (visible en los logs del agente).
Si el patrón continúa, el operador debe revisar la configuración y los flujos
de publicación.

**Buenas prácticas**
1. **Nunca** setear `skip_anti_dogpile=True` de forma hardcoded en la lógica
   de publicación normal.
2. **Siempre** verificar que las condiciones de "debate activo" se cumplen
   antes de usar la exención.
3. **Revisar logs periódicamente**: Los warnings de `skip_anti_dogpile` sin
   condiciones aparecen en los logs del agente. Un patrón repetido indica
   necesidad de ajustar la configuración.
4. **Preferir la vía natural**: Si el agente quiere responder a un post propio,
   que el hilo fluya naturalmente con replies normales. El anti-dogpile solo
   debería saltarse en casos muy específicos y documentados.

**Monitoreo**
El agente loguea cada uso de `skip_anti_dogpile` con el siguiente formato:

```
[SKIP_ANTI_DOGPILE] post_id=12345 author=usuario_tipo: skip_anti_dogpile=True
    -> own_post=False (anti-dogpile activado) / own_post=True (exención aplicada)
    -> substantive_replies=5 / skip_anti_dogpile_applied=True/False
```

Los operadores deben revisar estos logs en `logs/<agent_log>.log` durante
las rutinas de mantenimiento semanal.

**Histórico**
- Implementado en commit 2ec4f41: `skip_anti_dogpile=True` para posts propios
  con debate activo.
- Mejora de documentación y validación en v5.2+ (Recomendación 5).

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
- **Model cascade:** `services/model_cascade.py` — orden real (rev 24/08/2026 noche): free primario = `openrouter :free` (nemotron, único estable; también en classify — ya no es paid) → `zen` (Ox Alpha, respaldo 1, inestable) → `cloudflare` (respaldo 2, cuota diaria) → cerebras → pagos (`tier_fallback`=DeepSeek V4 Pro, `tier_flash`=V4 Flash) → dead. Circuit breaker por proveedor. NO devolver cloudflare/zen por delante de openrouter sin decisión del operador.
- **Generador editorial pago = DeepSeek V4 Pro DIRECTO** (24/08/2026): saldo recargado ($8.58) en api.deepseek.com; `MODEL_CASCADE_PREFER_FREE=0` activa `tier_fallback`/`tier_flash` directos. `ZEN_SERVE_DEEPSEEK=false` (la variante vía Zen existe pero sin saldo allí). Spend guard diario: `DEEPSEEK_SPEND_LIMIT_USD` default $0.50 con precios PEAK como cota — tracker `data/deepseek_spend_tracker.json`, reset automático a medianoche UTC; al agotarse el cap salta al siguiente proveedor (nunca bloquea el ciclo). El generador editorial real es tier_fallback (AGENT_PRO_TIER_ONLY=1 remapea premium→fallback; Anthropic queda como deep-fallback con su propio spend guard). **ESCENARIO B (24/08/2026 noche)**: TODOS los posts generan en V4 Pro (`PHASE_A_GENERATION_TIER=premium`, default) y las replies watchlist usan `quality→tier_fallback` (~$0.10-0.20/día total pico); replies generales y classify siguen gratis en openrouter. Revertir a todo-gratis: `PHASE_A_GENERATION_TIER=flash`.
- **Gates pre-publicación Fase A (24/08/2026)**: (1) leak-gate body/título (`text_has_reasoning_leak` + `title_has_scaffold`), (2) **anti-fatiga de plantilla** (`PHASE_A_FATIGUE_GATE=1` default; tetragramas presentes en ≥3 posts propios recientes → rechazo + regeneración con fórmulas nombradas; ventana 25, corpus <6 no juzga). La auditoría editorial (`services/editorial_self_audit.py`, corre en Phase C cada 6h) mide fatiga/CTA/engagement/calibración juez↔upvotes → `data/editorial_self_audit.json`. NO quitar los gates: los leaks publicados (23-24/08) salieron justamente por no existir.
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
- `docs/ARCHITECTURE.md` documents the v5.0 design.
