# AUDITORÍA PUNTA A PUNTA — COMET-RIOBAMBA v31

**Fecha:** 2026-08-22 · **Rama:** `feature/optimize-agent-config`
**Alcance:** infraestructura + lógica, punta a punta. Sin cambios en código todavía.
**Método:** lectura directa de código fuente, telemetría real (`cascade_telemetry.jsonl`,
`logs/agent.log`, `alerts.jsonl`), estado vivo (`status.ps1`) y `.env` de producción.

---

## 0. Resumen ejecutivo

El agente está VIVO (ciclo 4365) y la estrategia central funciona: OpenRouter `:free`
sostiene ~90% de las llamadas LLM (271 ok / 2 fallos en 3h). Pero:

1. **INCIDENTE ACTIVO**: `cerebras_content` devuelve HTTP 404 permanente (modelo
   `llama-3.3-70b` retirado del catálogo Cerebras). Cada vez que cloudflare tropieza
   con su rate limit, la cascada llega a cerebras, muere y dispara
   «CASCADA LLM AGOTADA → Modo Degradado» + alerta Telegram. ~20 fallos evitables
   en 3 horas; falsos positivos de outage al operador.
2. **Saldos negativos**: DeepSeek $-0.41, OpenRouter $-0.20. Con
   `AGENT_FLASH_ONLY=1` y `MODEL_CASCADE_PREFER_FREE=1`, toda la operación depende
   de proveedores gratis (openrouter :free + cloudflare). Riesgo de punto único.
3. **9 servicios huérfanos** (código muerto) y varios bugs de lógica de baja
   severidad documentados abajo.

---

## 1. Estado vivo al momento de la auditoría

| Componente | Estado |
|---|---|
| Agente | VIVO · ciclo 4365 · health hace 16 s · lock True |
| Watchdog | VIVO (PID 6188) |
| Circuitos | ninguno abierto al chequear |
| Modo degradado | no (pero activado 3+ veces hoy: 19:03, 19:18, 19:19 UTC-5) |
| Errores 1h | 9 |

### Telemetría cascada (últimas 3 h, 303 eventos)

| Proveedor | Llamadas | Fallos | Diagnóstico |
|---|---|---|---|
| `openrouter` (:free nemotron) | 271 | 2 | OK — pilar actual |
| `cloudflare` (llama-3.3-70b) | 12 | 6 | rate_limit del free tier (esperable, no bug) |
| `cerebras_content` | 20 | 20 | HTTP 404 determinista — modelo muerto |

---

## 2. Hallazgos CRÍTICOS (acción recomendada)

### C1. `cerebras_content` con modelo retirado → falsos «Modo Degradado»
- Evidencia (`logs/agent.log`): HTTP 404 desde cerebras_content:llama-3.3-70b,
  seguido de CRITICAL «CASCADA LLM AGOTADA … Modo degradado ACTIVO».
- Impacto: generación detenida innecesariamente; spam de alertas Telegram
  («Circuito abierto: cerebras_content» x3 hoy); normaliza alertas reales.
- Fix propuesto (1 línea en `.env`, reversible):
  - Opción A: actualizar `CEREBRAS_MODEL` a un modelo vivo del catálogo.
  - Opción B: `CEREBRAS_CONTENT_ENABLED=false`.
- No tocar: circuit breaker ni watchdog (funcionan correctamente; el problema es
  el proveedor, no la resiliencia).

### C2. Dependencia de punto único en proveedores gratis
- Saldos negativos (DeepSeek, OpenRouter) + `AGENT_FLASH_ONLY=1` ⇒ tier_flash
  (gemini-3.7-flash pagado vía OpenRouter) devuelve 402; Anthropic reservado;
  DeepSeek no registrado (PREFER_FREE=1).
- Si OpenRouter :free cambia cuotas o el nemotron sale del catálogo :free, queda
  solo cloudflare con rate limit agresivo ⇒ degradación sostenida real.
- Recomendación: decisión de operador (recargar saldo mínimo o diversificar free).

---

## 3. Hallazgos de CONFIGURACIÓN

### F1. `.env` con variables muertas y duplicadas
- `AGENT_MAX_PER_WATCHLIST_AUTHOR_DAY` aparece DOS veces (=3 y =10). Con
  `load_dotenv(override=True)` gana la última (10). Confuso; consolidar a una.
- Variables que NADIE lee en el código (basura): `AGENT_POSTS_PER_DAY=6`,
  `AGENT_COMMENTS_PER_POST=0`. El código usa `AGENT_MAX_POSTS_PER_DAY` /
  `AGENT_MAX_COMMENTS_PER_POST`. Riesgo: un operador las edita creyendo que aplican.

### F2. `routing_cfg` muerto (`config/config.py:216-228`)
- Apunta a `dashscope/qwen-plus|qwen-turbo` con fallback groq/openrouter/ollama.
- La cascada real es `model_cascade.py` (Anthropic/DeepSeek/OpenRouter/Cerebras/
  Cloudflare/Zen). Ningún componente lee `routing_cfg`. Eliminar o marcar legacy.

### F3. Agent charter roto (`config/config.py:245`)
- `AGENT_CHARTER_PATH = Path('config.agent_charter.yaml')` — es un path de módulo
  Python usado como ruta de archivo. El archivo real NO existe en ninguna parte
  del repo. `_load_agent_charter()` devuelve siempre `{}` silenciosamente.
- Decidir: crear `config/agent_charter.yaml` o eliminar el loader.

### F4. Inconsistencia de idioma en contenido
- `EDITORIAL_CONFIG` (phase_a_content.py): language=en, topics EN — coherente con
  el filtro `_is_mostly_english()`. Pero `content_cfg['topics']` (config.py) está
  en ESPAÑOL: si algún flujo cae ahí, genera posts que Fase A rechaza a posteriori
  (gasto LLM desperdiciado). Unificar topics de `content_cfg` a EN o vaciarlo.

### F5. `status.ps1` requiere pwsh (UTF-8 sin BOM)
- Con Windows PowerShell 5.1 explota (leído como ANSI). Documentado; opcional:
  guardar con BOM UTF-8 para robustez.

---

## 4. Hallazgos de LÓGICA (bugs confirmados)

### L1. `classifier.py:105` — comparación imposible
- `should_reply()` compara `comment_type == 'crossreference'`, pero
  `classify_comment()` devuelve `'cross_reference'` (con guion bajo). Rama muerta:
  los cross-reference nunca entran por esa vía (solo por score>=90 o pregunta directa).
- Fix: cambiar a `'cross_reference'`.

### L2. `scoring.py:422-454` — código muerto tras return
- `_compute_relationship_bonus()` tiene `return 0` en línea 421 y después una
  función vieja embebida inalcanzable (bonus por upvotes/comment_count).
- Fix: borrar líneas muertas (o extraer a función si se quiere usar).

### L3. Métricas de Phase C miden el feed ajeno, no actividad propia
- `_fetch_performance_metrics()` llama `self.moltbook.fetch_posts(since_hours=24, limit=50)`
  → feed global; además `fetch_posts()` solo acepta `limit`/`sort` (kwargs traga
  `since_hours` silenciosamente). Resultado: `posts_published_24h` y `avg_engagement`
  no miden lo que dicen medir; insights («engagement bajo», «tópico dominante») se
  basan en datos ajenos.
- Fix: usar `fetch_my_posts()` + `get_post()` para engagement propio, o renombrar
  la métrica a lo que realmente mide.

### L4. `_apply_optimization()` simulado (`phase_c_analytics.py:264-282`)
- Devuelve «Config adjustment simulated» sin aplicar nada. Los insights generan
  notificaciones Telegram de acciones inexistentes. O implementarlo vía
  `proposal_applier` (ya existe allowlist) o suprimir la notificación.

### L5. Duplicación best-of helpers
- `_quality_bestof_enabled/_quality_bestof_n` definidas en `phase_a_content.py:906-916`
  y otra vez (solo enabled) en `phases/phase_b/orchestrator.py:172-174`.
  Extraer a módulo compartido (p.ej. `utils/quality_flags.py`).

### L6. TODO vigente rate-limit awareness (`moltbook_api_client.py:479`)
- Parcialmente cubierto: `_call_write` ya reintenta 429 con Retry-After y 5xx con
  backoff. El TODO puede cerrarse o convertirse en nota documental. Sin acción urgente.

### L7. Error menor EPO patents (energy intel)
- `search error 'green hydrogen electrolysis': 404` en `logs/agent.log` — endpoint
  o query de la API europea de patentes falla. Baja prioridad; revisar query/endpoint.

---

## 5. Inventario de código muerto (servicios huérfanos)

Verificado: 0 referencias en `core/phases/services/scripts/config/utils/monitoring`,
0 en tests, 0 imports dinámicos.

| Servicio | Acción propuesta |
|---|---|
| `services/agent_profiler.py` | archivar/eliminar |
| `services/archive_keeper.py` | archivar/eliminar |
| `services/art_bridge.py` | archivar/eliminar |
| `services/auto_optimizer.py` | archivar/eliminar |
| `services/content_validator.py` | archivar/eliminar |
| `services/editorial_applier.py` | archivar/eliminar |
| `services/feedback_enricher.py` | archivar/eliminar |
| `services/social_metrics.py` | archivar/eliminar |
| `services/submolt_discovery.py` | archivar/eliminar |

Solo-tests (decidir si merecen vida en producción o archivar junto a sus tests):
- `services/post_history_guard.py` (4 tests)
- `services/trend_watcher.py` (13 tests)

Nota convención repo: mover a carpeta `attic/` o similar en vez de borrar, para
respetar el espíritu de «nunca modificar .bak» sin mantener ruido en `services/`.

Otros artefactos muertos detectados:
- `config/config.py.before_hf`, `services/model_cascade.py.before_huggingface`,
  `model_cascade.py.bak`, docenas de `.bak-*` — NO tocar (convención), pero
  considerar mudarlos a `attic/` en un commit dedicado algún día.

---

## 6. Fortalezas confirmadas (no romper)

- Token bucket separado post/comment/action + retry 429 con Retry-After + backoff 5xx
  (`moltbook_api_client.py`) — sólido.
- Circuit breaker por proveedor con alertas con cooldown (`model_cascade.py`).
- Anti-fabricación en Phase A/B (gates de cifras, años históricos, entidades no
  grounding) — bien calibrado con casos reales documentados en comentarios.
- Dedup multicapa (DedupStore SQLite + replied_comment_ids + anti-dogpile reply_cap
  compartido B/C) — funciona (dedup inbound f1197db intacto).
- Watchdog triple capa + ledger Telegram + alerts.jsonl con cooldown único.
- Fixes clave verificados intactos: parser karma real (489a074), alto valor scoring
  (be02c3c), weekly limit deslizante alineado (105 = 7x15).

---

## 7. Plan de corrección propuesto (orden por impacto/esfuerzo)

| # | Acción | Esfuerzo | Riesgo | Impacto |
|---|---|---|---|---|
| 1 | Fix C1 cerebras (.env: modelo vivo o disable) | 1 min | nulo | alto |
| 2 | Consolidar `.env`: dedupe WATCHLIST_AUTHOR_DAY, borrar vars muertas | 5 min | bajo | medio |
| 3 | L1 fix `crossreference` → `cross_reference` | 1 min | nulo | medio |
| 4 | L2 borrar código muerto en scoring.py | 2 min | nulo | bajo |
| 5 | F2/F3: eliminar routing_cfg muerto + charter loader roto (o crear yaml) | 15 min | bajo | limpieza |
| 6 | L3 métricas propias en Phase C | 30-60 min | medio | medio-alto |
| 7 | Mover 9 huérfanos a attic/ | 10 min | bajo | limpieza |
| 8 | F4 unificar idioma topics content_cfg | 5 min | bajo | medio |
| 9 | L4 conectar _apply_optimization a proposal_applier o silenciar | 20 min | medio | medio |
| 10 | L5 dedup helpers bestof | 10 min | nulo | bajo |

Después de cada cambio: `pytest tests/ -q` (advertencia conocida: los tests
sobrescriben `data/state/health.json`; el agente lo reescribe en su próximo ciclo).

---

## 8. Lo que esta auditoría NO hizo (transparencia)

- No se modificó ningún archivo de código ni `.env` (pendiente tu aprobación).
- No se ejecutó la suite completa de tests todavía (se hará al iniciar fixes).
- No se auditó a fondo `scripts/comet_repurposer/` (subproyecto independiente con
  sus propios tests) ni los ~50 scripts de utilidad uno a uno — solo presencia de
  referencias.
- No se verificaron saldos contra las APIs en vivo (se usó el último chequeo del
  watchdog como fuente).
