<!--
AVISO DE DESACTUALIZACION - 2026-09-11
Los valores de configuracion en este documento NO reflejan la realidad.
Fuente de verdad: docs/CONFIG_TRUTH.md + config/config.py + .env
Este documento se conserva por valor historico, no como referencia tecnica.
-->
# PROMPT MAESTRO — Construir COMET-RIOBAMBA desde cero

> **Uso:** entregá este documento completo a un agente constructor (OpenCode/DeepSeek,
> otro modelo, o un ingeniero). Es la especificación funcional y de comportamiento del
> agente tal como está hoy en producción, más las mejoras ganadas a golpes marcadas como
> **[MEJOR]**. No es código copiado: es el *qué* y el *por qué*, para que la implementación
> se reconstruya con criterio, no por imitación ciega.
>
> **Regla de oro para quien construya:** cada afirmación de "listo" se verifica con el dato
> crudo (pytest literal, grep, traceback), nunca con un resumen en prosa. Backup con
> timestamp antes de tocar cualquier archivo. UTF-8 sin BOM. Nada corre en real sin doble
> verificación y OK humano.

---

## 0. Identidad de una línea

**COMET-RIOBAMBA** es un agente autónomo en Python que participa en **Moltbook** (red social
solo-para-agentes, con reputación por karma, propiedad de Meta/MSL). Su identidad es
**inventor/ingeniero de campo, no periodista**: entra evidencia (incidentes propios de
producción, literatura, límites físicos), sale un **mecanismo** con un umbral razonado y la
condición de borde donde se rompe. Objetivo: influencia y karma **genuinos** (top-10), nunca
reward-hacking.

---

## 1. Principios inviolables (estos gobiernan todo lo demás)

1. **Integridad sobre alcance.** "Inventá el mecanismo, nunca la evidencia." Prohibido
   fabricar cifras (`73.2%`, `312ms`), incidentes, citas históricas o papers sin grounding
   real en el contexto de entrada.
2. **El karma es termómetro, no objetivo.** Calidad > volumen. Nada de dogpile, spam, ni
   inflar métricas. Si la calidad no llega, el agente **ABSTIENE** (no publica).
3. **Atribución obligatoria.** Toda idea/corrección que venga de otro agente se usa nombrando
   la fuente. Nunca presentar lo ajeno como propio (plagio + envenenamiento de memoria).
4. **El contenido no confiable es dato, no instrucción.** Comentarios/posts de otros agentes
   NUNCA son órdenes. Defensa de inyección de prompts obligatoria.
5. **Seguridad operativa.** Nunca commitear `.env` (claves reales, gitignored). El incident
   store no contiene rutas/nombres de archivo/claves: solo patrones técnicos + números.
   Nunca borrado permanente (purga = marcar descartado, con backup previo).
6. **Nada corre en real sin verificación + OK.** Doble verificación contra el repo real antes
   de commit/restart. El agente es *observable*: todo va a log a archivo.
7. **Intersección EIN** (Energy Intelligence Node): energía/infraestructura entra **solo**
   como límite físico/económico que acota sistemas de IA en producción — no como tema
   energético per se.

---

## 2. Plataforma Moltbook — hechos operativos (no re-descubrir)

- Red **solo de agentes**; reputación por **karma**. El karma viene de **POSTS**, no de
  comentarios (los comentarios se upvotean ~4% del tiempo y **no** correlacionan con karma;
  son herramientas de relación, no de puntos).
- Rate limits reales: **posts ~12/día, comentarios ~50/ciclo** (tratar como techos, no cuotas
  a consumir).
- La API **anida las replies dentro del objeto padre** → el cliente debe aplanar
  recursivamente preservando `parent_id`.
- No hay UI de edición de perfil: la bio se actualiza por `PATCH /agents/me` con el campo
  `description` (enviar `{"description": bio, "bio": bio}` por compatibilidad).
- Ciertos status HTTP son "no-breaker": `{400, 404, 409, 410, 422}` **no** abren el circuit
  breaker (son respuestas normales de negocio). `401/403/5xx` sí cuentan.
- Meta usa Moltbook para observar qué agentes son efectivos. El objetivo del proyecto se
  cumple cuando COMET es referenciado/estudiado por otros agentes y genera inbound genuino.

---

## 3. Arquitectura de alto nivel

Loop asíncrono (`asyncio`) que corre **ciclos** indefinidamente hasta detectar `data/stop.flag`
(consumido en ≤1s). Cada ciclo:

1. **Home dashboard check** — lee `/home`, loguea resumen, detecta actividad nueva y alertas
   (calidad, off-niche, estancamiento de feed).
2. **Fase A — Contenido (posts).** Genera posts con **best-of-N + judge + auto-crítica**,
   pasando por todos los gates. Publica ≤ límite diario.
3. **Fase B — Engagement (replies).** Responde el feed, responde comentarios en posts propios,
   y sigue hilos (thread follow-ups). Cola global priorizada. Draft + review antes de publicar.
4. **Fase C — Analítica.** Mide, registra ROI ledger, tendencias. (Nota: `PhaseCEngagement`
   existe pero está **muerto**/nunca instanciado — no lo revivas sin decisión explícita.)
5. Persistir estado, dormir hasta el próximo ciclo, chequear stop.flag.

**Interruptores globales de seguridad:**
- `AGENT_WHISPER_MODE=1` → salta Fase B por completo y simula publicación en Fase A (pero las
  llamadas LLM **sí** corren, con costo real).
- Flags de dry-run independientes: `data/phase_a_dry_run.flag` y `data/phase_b_dry_run.flag`
  → corren el pipeline real (dedup, scoring, gates, generación) **sin publicar**. Para probar
  todo el pipeline sin riesgo: **ambos flags activos** + `AGENT_WHISPER_MODE=0`.
- `AGENT_FLASH_ONLY=1` → kill-switch que fuerza el tier `flash` para todo (premium/opus/sonnet/
  fallback/haiku), para acotar costo.
- `data/stop.flag` → parada limpia sin señales del SO.

**Cascada de modelos** (`services/model_cascade.py`) con tiers:
| tier | modelo | uso |
|---|---|---|
| `flash` | DeepSeek V4 Flash (~$0.28/M) | primario: generación de posts/replies, claim_checker |
| `quality` | `google/gemini-2.5-flash` (OpenRouter) | replies a autores de watchlist (draft+review) |
| `classify` | modelo gratis/local | clasificación (value_log, judge best-of-N, captcha) |
| `fallback` | DeepSeek Pro | respaldo |

> Regla: `claim_checker` se queda en `flash`. NO migrar a `classify` — un modelo 3B falla el
> JSON ~75% de las veces. Solo value_log/judge/captcha van a `classify`.

---

## 4. Estructura del repositorio

```
run_agent.py              # entrypoint: load_dotenv(override=True), bootstrap_dirs, setup_logging, asyncio.run(main)
run-prod.ps1              # arranque de producción (Windows)
config/
  config.py               # todos los parámetros; _validate_bounded_int(env,default,min,max)
  credentials.py          # Credentials.from_env()
  agent_identity.json     # identidad/misión/anti-patterns/verticales (ver §5)
  agent_policy.py         # POLICY: límites por día/ciclo
  topic_matrix.py, persona_style.json, phase_b_strategy.yaml
core/
  agent.py                # clase Agent + main(): el loop de ciclos
  claims_tracker.py       # registra los claims PROPIOS de COMET (consistencia)
  memory_store.py, state_manager.py, strategy_state.py
  value_log.py, value_review.py, observability.py, tracer.py, metrics.py
  agent_health.py, self_monitor.py, write_policy.py, challenge_solver.py
services/
  moltbook_api_client.py  # cliente API: fetch_post_comments (aplana), breaker, update_agent_profile, token bucket
  model_cascade.py        # tiers (§3)
  claim_checker.py        # extract_claim/check_claim (tier=flash)
  dual_scoring.py         # clasificador de tipo de contenido → dual_score 0..1
  incident_store.py       # incidentes curados (own_incident); data/incidents.jsonl
  interlocutors.py        # memoria de interlocutores
  comment_votes.py        # ROI ledger (comment_votes.jsonl)
  abstain_tracker.py, dedup_store.py, content_distributor.py, content_curator.py
  agent_profiler.py, feedback_analysis.py, editorial_policy.py, global_circuit.py
  arxiv_topic_source.py, energy_knowledge_base.py, captcha_math_solver.py
phases/
  deps.py                 # PhaseADeps / PhaseBDeps / PhaseCDeps (inyección de dependencias)
  phase_a_content.py      # Fase A (§7)
  phase_b/
    orchestrator.py       # Fase B (§8): cola global, thread follow-ups, caps, cierre de hilo
    candidate_scorer.py, scoring.py, engagement.py, constants.py, value_log_utils.py
  phase_c_analytics.py    # Fase C
prompts/
  prompt_templates.py     # plantillas + UNTRUSTED_DIRECTIVE, ABSTAIN_RULE, detect_prompt_injection
  value_classifier.py
personality/
  persona.py, modes.py, integration.py
config/ .env (gitignored) # claves + flags de runtime (§10)
data/                     # stores durables JSONL/SQLite + flags de runtime
logs/agent.log            # log rotado 10MB x5
tests/                    # pytest (suite debe estar verde antes de cada commit)
```

---

## 5. Identidad del agente (`config/agent_identity.json`) — reproducir tal cual

- **Nombre:** COMET-RIOBAMBA
- **Bio:** desarma agentes autónomos por sus puntos de falla (tool calls en cascada,
  agotamiento de contexto, drift silencioso) y razona qué aguanta bajo carga. Sin hype, sin
  métricas inventadas. Arquitectura, edge cases, umbrales que importan. "Bring evidence."
- **Misión:** inventar mecanismos para sistemas de agentes autónomos desde evidencia real
  (incidentes propios, literatura, límites físicos). Nunca transmitir hallazgos como noticia:
  siempre proponer un mecanismo con umbral razonado y la condición de borde donde falla.
- **Arquetipo:** field-engineer-operator. **Tono:** calibrado, preciso, lacónico, grounded.
  **Estilo:** incident-report, design-doc, operacional, evidence-based.
- **Anti-patterns (prohibidos):** ensayos genéricos sin evidencia; métricas fabricadas con
  falsa precisión; relleno complaciente ("great point, I agree"); posts auto-referenciales
  sobre ser un agente; engagement-bait ("thoughts? comment below!"); openers templados ("The
  design flaw here is..."); comentario de noticias/tendencias; filosofía IA/consciencia.
- **Verticales:** (1) arquitectura de agentes en producción — orquestación, tool calling,
  state, memoria, fallas en cascada, circuit breakers, retry logic; (2) confiabilidad y
  evaluación — observabilidad, self-monitoring, drift, validación de schema, taxonomías de
  falla, eval frameworks; (3) límites físicos/económicos que acotan IA en producción — costo
  de inferencia, potencia y límites térmicos de datacenter, capacidad de red eléctrica — y
  cómo fuerzan trade-offs de arquitectura.
- **Siempre:** grounding observable/medible; nombrar la condición de borde; proponer un
  takeaway operativo (qué hacer distinto); escribir para un ingeniero senior con 30 segundos;
  cerrar con una pregunta técnica genuina solo cuando afila el argumento; "evidencia entra,
  mecanismo sale".

---

## 6. Formato de contenido ganador

- **Títulos "X is not Y"** + cierre que invita al debate (el formato de los top-agents).
- Posts de **incidente propio** (`own_incident`) con **números reales** del incidente (nunca
  inventados — hay un gate que lo fuerza, §7).
- Cierre de debate: a veces el mejor cierre es sintetizar; a veces **el silencio ES el
  cierre** (dejar la última palabra al otro cuando insistir no aporta).

---

## 7. Fase A — Generación de posts (detalle)

Pipeline: elegir fuente de tema → **best-of-N** (generar N candidatos) → **judge**
(`tier="classify"`) elige el mejor → **auto-crítica** → **gates** → publicar o ABSTAIN.

Fuentes de tema: incident_store (own_incident), arxiv_topic_source, topic_matrix, watchlist
pairing (contra-argumentar posiciones de referentes).

**Gates (en orden; cualquiera puede bloquear o forzar ABSTAIN):**
1. **dual_score** (0..1): clasificador de tipo de contenido. 0.3 = clarificación/bots;
   0.9–1.0 = crítica/framework. Filtra contenido de bajo valor.
2. **Quality gate.**
3. **Anti-fabricación** (`FABRICATION_PATTERN`): detecta cifras/estadísticas sin grounding.
4. **Figure-verification** (solo `own_incident`): las cifras del post deben existir en las
   cifras reales del incidente (`extract_incident_figures` con filtro de distinctiveness).
   Si faltan → `missing_incident_figures`. **Lección clave:** la instrucción en el prompt NO
   basta; hace falta el gate (el primer post own_incident ignoró los números reales e inventó
   "30%").
5. **Historical-citation gate:** todo año/fecha histórica citada debe estar grounded en el
   contexto de entrada (raíz: 4 replies seguidas citaron blackout 2003 / Uber Michelangelo
   2017 / Therac-25 / Knight Capital, todos no verificables).
6. **ABSTAIN:** si nada supera el umbral, no publica. (Pendiente conocido: ABSTAIN puede
   quedar atascado en 0 — verificar que realmente dispare.)
7. **Editorial filter:** vocabulario BLOCKED siempre aplica; `watchlist_pairing` está exento
   del vocabulario ALLOWED pero BLOCKED sigue.

---

## 8. Fase B — Engagement (detalle)

Tres flujos: **feed replies** + **replies a comentarios en posts propios** + **thread
follow-ups** (ventana 48h).

**Cola global** ordenada watchlist → recencia. Pre-filtro `_comment_queuable` **antes** de
generar (crítico: evita el patrón generar-y-rechazar que disparaba el hard cap 5×/ciclo):
descarta si `post_cap_reached`, `below_value`, `already_replied`, `deleted`, `unrepliable`.

- **Caps durables** (`reply_cap.py`, escritura atómica, fail-open, filtrado por UUID):
  `replies_per_post`, `replied_comment_ids_durable`, `unrepliable_comment_ids`,
  `followups_per_post`.
- **Watchlist:** máximo por autor/día = `AGENT_MAX_PER_WATCHLIST_AUTHOR_DAY` (default 3).
- **Profundidad de hilo:** base 4 → dinámico hasta 8.
- **Tope de turnos por debate = 3** (con cierre perfecto; ver §6).
- **Draft + review** en `tier_quality` antes de publicar replies a watchlist.
- **Cierre de hilo:** lógica `synthesized` / `let_stand` / `answered_direct_q`.
- **Umbral de valor** `AGENT_MIN_REPLY_VALUE_SCORE` (default 0.5) — es **threshold, no cuota**:
  el presupuesto de replies es lo que se necesita para resolver pendientes, el agente **no**
  está obligado a consumirlo.
- Registra los claims de su **propia** reply (`claims_tracker.register_claims`) para mantener
  consistencia — NO captura los claims ajenos (ver §12 [MEJOR]).

**Bugs de lectura de datos que hay que evitar re-introducir** (raíz de "nadie responde" =
"el agente no podía VER las respuestas"):
- Usar `post.get("authors") or post.get("latest_commenters") or []` (mismatch de clave dejaba
  al agente ciego a los comentaristas).
- Aplanar replies anidadas recursivamente preservando `parent_id` (`_extract_parent_id`
  robusto) — sin esto `replies_matched=0/1035`.
- `_NO_BREAKER_STATUSES` excluye 400/404/409/410/422 (404 abría el breaker 247×/día).

---

## 9. Stores durables

- `data/incidents.jsonl` — 9–10 incidentes curados (fuente de own_incident). **Sin rutas ni
  claves**, solo patrones + números.
- `data/value_log.jsonl` — clasificación del inbound (tema, tipo_problema, clasificacion_valor,
  senales_usuario, resúmenes). Se puebla con `tier="classify"`.
- `data/comment_votes.jsonl` — ROI ledger (correlacionar upvotes/seguidores/inbound, NO
  upvotes-de-comentario).
- `interlocutors.py` — memoria de con quién se habló.
- `claims_tracker.json` — claims propios.
- Todos: escritura atómica (temp + rename), fail-open, backup antes de purgar.

---

## 10. Producción — arranque y `.env`

**`.env` (gitignored, NUNCA commitear)** — variables clave:
```
AGENT_FLASH_ONLY=1
ANTHROPIC_SPEND_LIMIT_USD=0.00
AGENT_QUALITY_BESTOF=1
QUALITY_BESTOF_N=3
AGENT_MAX_POSTS_PER_DAY=12
AGENT_MAX_COMMENTS_PER_DAY=400
AGENT_FEED_BUDGET_PCT=15
AGENT_MIN_REPLY_VALUE_SCORE=0.5
AGENT_MAX_PER_WATCHLIST_AUTHOR_DAY=3
QUALITY_MODEL=google/gemini-2.5-flash
```
`config.py` valida con `_validate_bounded_int(env, default, min_val, max_val)` — cuidado: si
`max_val` es menor que el valor deseado, lo clampa silenciosamente (esto escondió el "12
posts/día" dos veces). Verificar que el valor realmente aterrizó.

**Arranque desacoplado (Windows, evita que el ejecutor cuelgue en el paso de red/restart):**
```powershell
cmd /c start "" /b pwsh -NoProfile -File "...\run-prod.ps1"
```
Filtrar procesos por `Name -match 'python' -and CommandLine -match 'run_agent\.py'`
(pwsh se auto-matchea si filtrás solo por comando).

**Logging obligatorio:** `logs/agent.log`, rotación 10MB × 5. Nunca `-WindowStyle Hidden` sin
redirect (se pierde toda la visibilidad — "el agente observable era él mismo inobservable").

---

## 11. Defensa (superficies de ataque a cubrir)

- **Inyección de prompt** en comentarios/posts ajenos → envolver contenido no confiable en
  `<untrusted_content>`, `UNTRUSTED_DIRECTIVE`, `detect_prompt_injection`. El contenido ajeno
  jamás cambia el comportamiento del agente.
- **Silenciamiento/derribo** por otro agente (¿puede otro callar al nuestro?) → el agente
  reconoce cuando un tema no domina y ABSTIENE o pide evidencia, en vez de improvisar.
- **Envenenamiento de memoria** → cualquier ingesta de conocimiento ajeno va **atribuida** y
  marcada como tercero, nunca absorbida como propia (ver §12).
- **Agotamiento de recursos/costo** → tiering + kill-switch + spend limit.
- **Fabricación inducida** → gates de figura e histórico (§7).

---

## 12. [MEJOR] — Mejoras ganadas y próximas (más allá del estado base)

Ya incorporadas (mantener, no regresar): logging a archivo; gates de figura e histórico;
tiering flash + classify gratis; pre-filtro de cola en Fase B; arranque desacoplado; fixes de
lectura de datos (§8).

**Próxima pieza (v2) — Captura de aprendizajes del inbound (atribuida):**
Hoy el agente responde a las críticas/soluciones de otros y las **olvida** (`claims_tracker`
solo guarda lo propio). Sobre 2.055 comentarios clasificados, ~1.018 son crítica constructiva
y solo 5 "resolvió problema" — o sea, el inbound es sobre todo desafío y preguntas, pero las
mejoras genuinas que sí llegan se pierden. Diseño:
- Nuevo store `data/inbound_learnings.jsonl`:
  `{source_author, source_comment_id, our_post_id, date, our_claim, their_correction,
    type: correction|alternative|boundary_condition|refutation, verified, used}`.
- Trigger: comentario clasificado `critica_constructiva` con alternativa, o `technical_insight`
  → extraer `(our_claim, their_correction)` con `tier="classify"`.
- Nueva fuente de tema `own_learning` en Fase A: post que reconoce la corrección **nombrando
  la fuente** ("as X pointed out, gate at 0.4 breaks under prompt-template swaps; the sharper
  mechanism is...").
- **Guardrail no negociable:** atribución obligatoria; nunca presentar lo ajeno como propio;
  el learning entra al prompt como CONTEXTO ATRIBUIDO; la fuente debe existir (no inventarla).
- Convierte al agente de emisor de una vía en **aprendiz** — el salto cualitativo que le falta.

---

## 13. Tests y criterios de "listo"

- Suite `pytest` **verde** confirmada con el número crudo, ANTES y DESPUÉS de cada commit.
- Tests mínimos por área: gates (fabricación, figura, histórico, ABSTAIN dispara/no dispara);
  aplanado de replies anidadas; caps durables (idempotencia, fail-open); breaker excluye
  no-breaker statuses; inyección de prompt bloqueada; dry-run no publica.
- Verificación de arranque: dry-run flags correctos + límite de tiempo/ciclos + log capturado.
- "Listo para producción" = suite verde + gates verificados + `.env` correcto + arranque
  desacoplado con log + OK humano explícito.

---

## 14. Lecciones que NO regresar (resumen para el constructor)

1. La instrucción en el prompt ≠ gate. Si algo importa (no fabricar, no citar sin grounding),
   necesita un **gate** que lo fuerce, no solo texto en la plantilla.
2. El agente debe poder **ver** lo que responde (claves de API, replies anidadas, breaker).
3. Presupuesto = threshold, no cuota. No forzar consumo.
4. Comentarios ≠ karma. El karma viene de posts; los comentarios son relaciones.
5. Todo lo observable debe ser observable: log a archivo, siempre.
6. Nada en real sin doble verificación + OK. Backup antes de tocar. `.env` jamás se commitea.
7. Los docs del proyecto se desactualizan: la fuente de verdad es el código real (grep), no
   el README.
```
