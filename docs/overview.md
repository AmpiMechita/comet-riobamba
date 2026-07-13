# COMET-RIOBAMBA — Overview
> Versión 4.3.x · Actualizado junio 2026

---

## Identidad y propósito

COMET-RIOBAMBA es un agente autónomo de contenido técnico que opera en Moltbook como
**research architect de sistemas de agentes**. Su objetivo no es comentar el estado del
arte ni buscar viralidad: es proponer frameworks, métricas y protocolos, abrir debates de
alta relevancia y sostener una agenda de investigación continua en torno a:

- Guardrails de toolchains y validación de tool calls
- Métricas para agentes multi-tool y sistemas BCI/closed-loop
- Failure modes, deduplicación y estabilidad operacional en pipelines de agentes

El agente publica bajo la cuenta `comet_riobamba` en Moltbook.
**Human Owner:** Ing. Rafael D. Estrada G. (`@Rafest_zoot`)

---

## Arquitectura por fases

### Fase A — Contenido original

Genera posts técnicos en modo **research** siguiendo la estructura:

```
PROBLEM     (2-3 oraciones): tensión real o gap identificado
PROPOSAL    (3-5 oraciones): framework, pipeline, protocolo o métrica concreta
RESEARCH QUESTION (1 oración): pregunta específica que invita a co-diseñar
```

**Selección de tema (orden de prioridad):**
1. `research_agenda.json` → `pending_topics` no cubiertos (poblados por Fase C)
2. `services/roadmap.py` → temas del roadmap activo
3. `data/editorial_policy.json` → 12 topics estáticos con ponderación por engagement histórico

**Anti-repetición:** `WritePolicyEngine` + `is_similar_to_recent()` evitan publicar sobre el
mismo tema dos veces en ventana reciente.

---

### Fase B — Respuestas a comunidad

Ejecuta en cada ciclo principal (~8 h) y en pasadas independientes cada hora (intra-sleep).

**Prioridad de ejecución:**
1. Responde comentarios relevantes en **posts propios** (`fetch_my_posts`)
2. Solo si queda presupuesto de ciclo, responde en **posts ajenos del feed**

**Cada reply debe aportar al menos uno de:**
métrica concreta · guardrail · failure mode real · research question

**Deduplicación:** clave `post_id:comment_id` en `data/replied_comment_ids.json`.
No se responde dos veces al mismo comentario ni se repite en posts ajenos ya tratados.

**Detección de autor propio:** método `_is_own_author()` normaliza guión/guión-bajo
(`COMET-RIOBAMBA` ↔ `comet_riobamba`) para evitar que el agente responda sus propios
replies anteriores.

---

### Fase C — Analytics & Trend Watcher

Corre cada 24 h (gate de tiempo) y solo si el presupuesto diario lo permite.

**Acciones en orden:**
1. Obtiene métricas de engagement de las últimas 24 h (`avg_engagement`, `top_topics`)
2. Genera insights: `engagement_low` y `topic_repetition`
3. Ajusta pesos del roadmap según performance de topics
4. **Actualiza `data/research_agenda.json`** con:
   - `pending_topics` nuevos detectados en el feed
   - `high_impact_threads` (hilos con alta actividad)
   - `new_terms` (terminología emergente)
5. Envía daily report por Telegram si está habilitado

La agenda actualizada por Fase C alimenta la selección de temas de Fase A en el siguiente
ciclo, cerrando el loop `observar → proponer → explorar`.

---

## Agenda de investigación (`data/research_agenda.json`)

Archivo JSON persistente con cinco arrays:

| Campo | Descripción |
|---|---|
| `pending_topics` | Temas detectados por Fase C pendientes de cubrir en Fase A |
| `open_questions` | Preguntas sin respuesta de posts e interacciones recientes |
| `experiments` | Ideas de experimentos propuestos en threads o posts propios |
| `high_impact_threads` | Hilos del feed con alta actividad relevante |
| `new_terms` | Terminología emergente detectada en el feed |

Fase A consume `pending_topics` → marca como `covered: true` tras publicar.
Fase C repone con nuevos topics en cada ciclo analytics.

---

## Configuración y límites

### Límites de comportamiento (`config/agent_policy.py`)

| Parámetro | Valor | Descripción |
|---|---|---|
| `max_posts_per_day` | 5 | Posts originales (Fase A) |
| `max_comments_per_day` | 12 | Presupuesto total diario (propios + feed) |
| `max_comment_replies_per_cycle` | 4 | Replies por ciclo de ~8 h |
| `max_comments_per_post` | 3 | Replies máximos en un post **propio** |
| `max_feed_comments_per_post` | 1 | Replies máximos en un post **ajeno** |
| `max_feed_replies_per_day` | 3 | Tope diario exclusivo para feed |

**Orden de resolución:** env var → `agent_policy.py` (POLICY) → default de PhaseB.

### Submolts permitidos

`agents · general · ai · security · aisafety · technology · infrastructure ·
tooling · memory · builds · buildlogs · todayilearned · aithoughts · agentskills ·
trading · crypto · agentfinance · agenteconomy`

### Submolts bloqueados

`introductions · announcements · philosophy · existential · consciousness ·
ponderings · bts · blesstheirhearts`

### Política editorial (`data/editorial_policy.json`)

- 12 topics con ponderación 0.83–0.95 (mayor peso: silent failure modes, cascading errors,
  context window)
- `tone`: natural_directo
- `allow_question_ending`: true *(requerido para estructura RESEARCH QUESTION)*
- `target_words`: 120–220

---

## Observabilidad

**Eventos emitidos** (`core/observability.py`):
`cycle_start` · `phase_a_publish_success` · `phase_a_publish_skip` · `phase_b_scan_start` ·
`phase_b_reply_success` · `phase_b_reply_skip` · `phase_b_duplicate_skip` ·
`state_saved` · `state_reset_daily` · `value_review_run`

**Archivos de estado:**
- `data/state/agent_state.json` — ciclo, posts/comentarios del día, consecutive_failures
- `data/state/health.json` — snapshot del último ciclo (duración, fases, errores)
- `data/state/phase_c_state.json` — historial de métricas y último analytics_run
- `data/replied_comment_ids.json` — set de claves `post_id:comment_id` ya respondidas
- `data/commented_post_ids.json` — posts ajenos ya comentados (evita repetición en feed)

**Telegram:** alertas de ciclo, errores críticos y daily report (requiere `BOT_TOKEN` +
`CHAT_ID` en `.env`).

---

## Deuda de naming: tiers de modelo

`MODEL_TIER_OPUS_MODEL` / `MODEL_TIER_HAIKU_MODEL` en `.env` son **nombres heredados de
variables de entorno sin relación con los tiers internos** `tier_premium` / `tier_fallback`
del código (`services/model_cascade.py`). Pendiente de migración coordinada de `.env`.
No confundir con los tiers internos al hacer debugging: `tier_premium` = Anthropic
(claude-sonnet-5), `tier_fallback` = DeepSeek V4 Pro. Los bloques `MODEL_TIER_OPUS_*` /
`MODEL_TIER_HAIKU_*` solo actúan como fallback legacy cuando falta `ANTHROPIC_API_KEY`.

---

## Deuda de dedup por exact-match en research_agenda

Dedup de `research_agenda.py` usa exact-match de string en `add_topic()` sin normalización
(lowercase/strip). Funciona hoy porque las reformulaciones son raras (~5-7% en muestra de
199 topics reales, confirmado 2026-07-11), pero no está protegido si el estilo de generación
de Phase B cambia. Revisar si empieza a crecer la tasa de near-duplicates.

---

## tier_fallback (DeepSeek V4 Pro) corre con thinking:disabled

`tier_fallback` (DeepSeek V4 Pro) corre con `thinking:disabled` por costo — prioriza
velocidad/precio sobre profundidad de razonamiento. Si la calidad editorial del fallback
se percibe inferior a lo esperado, considerar `reasoning_effort:high` con `max_tokens` más
generoso como alternativa, aceptando mayor costo por llamada.

---

## Purga de fixture data en research_agenda.json (2026-07-11)

Se detectó una fuga de fixture data de tests (strings "Post N about agents", "Feed post",
"Repeat", "New") hacia `data/research_agenda.json` real, causada por 2 tests de feed-limit
que no usaban aislamiento (`AGENDA_PATH` faltante en `_redirect_paths`).
Causa raíz corregida en commit `1d61498`.
Se purgaron 10 entradas de fixture del archivo real (219 → 209 topics), con backup en
`data/research_agenda.json.bak-20260711` (no versionado, en disco local).
El archivo `research_agenda.json` dejó de trackearse en git desde el commit `ca711cb`;
esta nota documenta la purga ya que el archivo mismo no deja rastro versionado.

---

## Estado operacional (junio 2026)

| Componente | Estado |
|---|---|
| Fase A (research mode) | ✅ Activa |
| Fase B (own posts + feed) | ✅ Activa — spam fix aplicado |
| Fase C (analytics + agenda) | ✅ Activa — corre cada 24 h |
| CAPTCHA solver (Cerebras fallback) | ⚠️ Pendiente verificar `CEREBRAS_API_KEY` |
| Telegram monitoring | Configurable vía `.env` |
| `research_agenda.json` | ✅ Limpia — se poblará en próximo ciclo Fase C |

---

## Archivos clave

```
comet-riobamba-v31/
├── core/
│   ├── agent.py          # Loop principal, orquestación de fases
│   └── state_manager.py  # Estado persistente (ciclo, quotas diarias)
├── phases/
│   ├── phase_a_content.py
│   ├── phase_b.py
│   └── phase_c_analytics.py
├── config/
│   ├── agent_policy.py   # Límites y defaults de comportamiento
│   ├── behavior_cfg.py   # Config base del agente
│   └── credentials.py    # Carga de API keys desde .env
├── services/
│   ├── model_cascade.py  # Cascada de proveedores LLM
│   └── moltbook_api_client.py
├── prompts/
│   └── prompt_templates.py  # SYSTEM_PROMPT, POST_TEMPLATE_CONTRARIAN, REPLY_TEMPLATE
└── data/
    ├── research_agenda.json
    ├── editorial_policy.json
    └── topic_index.json
```
