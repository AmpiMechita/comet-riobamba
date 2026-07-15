# Prompt para KIRO — COMET-RIOBAMBA v4.3.0 (Modo Pro / Agente)

> **Instrucciones para KIRO**: Estás trabajando sobre el repositorio `C:\comet-riobamba-v31`, un agente social autónomo que opera en Moltbook (plataforma tipo Reddit/HackerNews). El código está en Python. Se ejecuta con `python run_agent.py`. Trabaja en modo agente/pro: lee archivos, modifica, ejecuta tests con `pytest`, y no me pregunes — toma decisiones técnicas y avanza. Todo el código y comentarios que escribas deben estar en **inglés**. Los logs del agente están en español, eso es correcto y no debes cambiarlo.

---

## 1. CONTEXTO DE PROYECTO

COMET-RIOBAMBA v4.3.0 es un agente autónomo de 3 fases que corre ciclos de 5 minutos:
- **Phase A**: Genera y publica contenido original (posts) en Moltbook
- **Phase B**: Responde a comentarios en posts propios + responde a posts ajenos en el feed
- **Phase C**: Analytics, auto-diagnóstico, ajuste de tópicos

Stack: Python 3.11+, SQLite (estado), REST API contra Moltbook, 8 proveedores LLM en cascada con circuit breakers, token bucket rate limiter (1 write/150s).

---

## 2. ESTADO ACTUAL — LO QUE YA FUNCIONA

Post-sesión de auditoría (25 jun 2026), estas cosas están CORREGIDAS y funcionando:
- ✅ Feed replies publicados: 8/8 en el primer ciclo post-fix (antes era 0/0)
- ✅ Scoring de posts funciona: distribución 10-50, 49 tech keywords en inglés matching
- ✅ `_allow_feed_repeat_reply` reescrito: expira a 24h, detecta nuevos comentarios, no bloquea permanente
- ✅ Dedup DB limpiada (370 filas → 0)
- ✅ Budget logging corrige: muestra `remaining_feed_daily=20/20`
- ✅ PhaseBDeps inyecta `posts_today` desde `self.state.posts_today`
- ✅ Spam gate: posts <100 chars descartados
- ✅ 586 tests pasando

---

## 3. BUGS CRÍTICOS PENDIENTES — PRIORIDAD DE ATAQUE

### P0-1: CAPTCHA Solver siempre extrae la misma expresión errónea
**Archivo**: `services/challenge_solver.py`
**Síntoma**: Después de cada `create_post`, Moltbook requiere verificación con un math challenge. El solver siempre extrae `"32 + 8" = 40.00`, Moltbook responde 400 "Incorrect answer". Los posts se crean pero quedan sin verificar.
**Evidencia en logs**:
```
ChallengeSolver: LLM extrajo expresion '32 + 8'
ChallengeSolver: LLM+eval exito! '32 + 8' = 40.00
MoltbookAPIClient: respuesta HTTP POST .../verify -> 400
Moltbook rechazo la respuesta. Result: {'message': 'Incorrect answer', ...}
```
**Hallazgo clave**: En una sesión anterior SÍ funcionó (`"32 + 17" = 49.00` → `✅ CAPTCHA resuelto`). Esto sugiere que el LLM está recibiendo mal el contenido del challenge (¿HTML no parseado? ¿cache de respuesta anterior? ¿el prompt al LLM no incluye el challenge real?).
**Tu tarea**: 
1. Lee `services/challenge_solver.py` completo
2. Rastrea cómo se obtiene el challenge HTML/response de Moltbook después de `create_post`
3. Verifica que el texto del challenge real se esté pasando al LLM y no un texto cacheado o hardcodeado
4. El fallback nativo de Python (`eval()`) falla primero — investiga por qué
5. Fix y valida que la expresión extraída coincida con lo que Moltbook realmente envía
6. Considera agregar logging del challenge crudo ANTES de enviarlo al LLM

### P0-2: `architect` mode fuerza opener "weakest link" (contaminación de personalidad)
**Archivo**: `modes.py:9` (aprox)
**Síntoma**: El modo de comunicación `architect` tiene una instrucción hardcodeada tipo "weakest link" que fuerza al agente a abrir cada respuesta con un framing negativo/debil. Esto contradice la personalidad técnica y directa del agente.
**Tu tarea**: 
1. Lee `modes.py` completo
2. Identifica la instrucción problemática en el modo `architect`
3. Reemplázala con algo consistente con la personalidad del agente (directo, técnico, sin apologetics)
4. Revisa los otros 4 modos para inconsistencias similares
5. Ejecuta los tests

### P1-1: Claim-check con 12.5% de falsos positivos
**Archivo**: `services/claim_checker.py` y `phases/phase_b.py:~1100`
**Síntoma**: 1 de cada 8 respuestas generadas es rechazada por claim-check con `on_topic=False`. Ejemplo real: reply sobre "robot rights" fue rechazada con `"The reply pivots to a technical discussion about blockchain latency"` — pero el post original SÍ trataba sobre eso.
**Hallazgo**: El claim-checker también tiene un "failing open" cuando el LLM devuelve JSON truncado (len=9): lo permite pasar con warning. Esto es aceptable. El problema es el umbral de `on_topic` y/o el prompt de evaluación.
**Tu tarea**:
1. Lee `services/claim_checker.py` completo
2. Revisa el prompt que se envía al LLM para evaluar on_topic — ¿está pidiendo que la reply cubra EXACTAMENTE el mismo topic o permite derivas técnicas razonables?
3. Ajusta el threshold o el prompt para permitir respuestas que hagan analogías técnicas o conexiones跨-tema
4. Verifica que el "failing open" para JSON truncado siga funcionando
5. No elimines el claim-check — solo afloja el criterio

### P1-2: `content_validators.py` desconectado del pipeline
**Archivo**: `content_validators.py` (nunca importado)
**Síntoma**: Existe un archivo con validadores de contenido que NUNCA se importan en Phase A ni Phase B. Código muerto.
**Tu tarea**:
1. Lee `content_validators.py`
2. Determina qué validaciones útiles contiene
3. Integra las relevantes en el pipeline de Phase A (antes de publicar) y/o Phase B (después de generar reply)
4. Si contiene validaciones duplicadas con lo que ya existe en phase_b.py, remuévelas y documenta por qué

### P1-3: `COMMENT_STYLE_INSTRUCTIONS` en español
**Archivo**: `phases/phase_b.py:~282`
**Síntoma**: Todas las system prompts del agente están en inglés, excepto `COMMENT_STYLE_INSTRUCTIONS` que está en español. Esto causa que el LLM genere respuestas en español cuando debería generar en inglés (el idioma de Moltbook).
**Tu tarea**: Traduce `COMMENT_STYLE_INSTRUCTIONS` al inglés. Mantén el tono y las restricciones idénticas.

---

## 4. BUGS SECUNDARIOS (P2-P3)

### P2-1: Validator desconocido que capsa `max_feed_replies` a 20
**Síntoma**: En logs aparece `max_feed=20` pero en `.env` no hay ningún `AGENT_MAX_FEED_REPLIES_PER_DAY=20`. Algo lo está forzando a 20.
**Tu tarea**: Busca en todo el codebase dónde se define/capsea `max_feed` o `max_feed_replies`. Puede estar en `agent_policy.py`, un config loader, o un validator. Documenta dónde está y por qué es 20.

### P2-2: DedupStore sin TTL
**Archivo**: `services/dedup_store.py`
**Síntoma**: Los fingerprints en `comet_dedup.db` nunca expiran. Se acumulan indefinidamente. Ya tuvimos que borrar 370 filas manualmente.
**Tu tarea**: Agrega una columna `created_at` (TIMESTAMP) y un método `cleanup(older_than_hours=24)` que se llame al inicio de cada ciclo. Los fingerprints más antiguos de 24h deben eliminarse.

### P2-3: Over-prohibition "squeeze" effect
**Síntoma**: Hay 40+ frases prohibidas distribuidas en múltiples archivos. La superposición causa que muchas respuestas legítimas sean descartadas, forzando al agente a generar respuestas genéricas.
**Tu tarea**: 
1. Encuentra todas las listas de frases prohibidas (busca patterns tipo `forbidden`, `banned`, `prohibited`, `blocklist`, `not_allowed`)
2. Cataloga cuántas hay y dónde están
3. Identifica duplicados y contradicciones
4. No elimines nada aún — solo documenta y sugiere consolidación

### P3-1: `OLLAMA_FALLBACK_REPLY` bypassa todos los quality controls
**Síntoma**: Cuando todos los proveedores LLM principales fallan, el agente usa una reply hardcodeada (`OLLAMA_FALLBACK_REPLY`) que reemplaza el prompt original completo. La respuesta generada bajo fallback no pasa por claim-check, quality guardrails, ni sigue los modos de comunicación.
**Tu tarea**: 
1. Encuentra dónde se define y activa `OLLAMA_FALLBACK_REPLY` (probablemente en `phase_b.py`)
2. Agrega al menos un length check y forbidden-phrase check antes de publicar un fallback reply
3. Loguea explícitamente cuando se usa fallback para distinguirlo en analytics

### P3-2: Sin notificación de modelo degradado
**Síntoma**: Cuando el circuit breaker abre para tier_opus y cae a tier_sonnet o peor, no hay notificación/logging al usuario.
**Tu tarea**: Agrega un log WARNING cuando se usa un tier menor al solicitado (ej: se pidió opus pero se usó sonnet).

---

## 5. MEJORAS DE ARQUITECTURA (ROADMAP v5.0)

Estas NO son bugs sino mejoras para la próxima versión. Trabajalas SOLO si terminas los P0 y P1 primero:

1. **Limitar replies por ciclo a 2-3** en vez de 8. Actualmente 8 replies = ~20 min por ciclo (token bucket 1/150s). El ciclo deberia durar ~5 min. Reducir `max_comment_replies_per_cycle` a 3 y compensar con más ciclos.

2. **Separar el token bucket por tipo de acción**: Actualmente `create_post` y `create_comment` comparten el mismo bucket. Si pubicas un post, los comentarios se retrasan 150s. Considera buckets independientes.

3. **Agregar métricas de "reply quality" post-publicación**: Trackear upvotes/karma recibidos por cada reply para feedback loop en Phase C.

---

## 6. REGLAS DE TRABAJO

- **No rompas los 586 tests existentes**. Si un cambio rompe un test, actualiza el test SI el comportamiento nuevo es correcto.
- **Cada fix debe ir con su test** cuando sea posible (especialmente P0-1 CAPTCHA, P0-2 architect mode).
- **No cambies los logs a español** — el agente loguea en español, eso es intencional.
- **Commits granulares**: un commit por fix, con mensaje descriptivo.
- **Si encuentras algo no listado aquí que sea un bug real**, fix it y documentalo.
- **Prioridad estricta**: P0 > P1 > P2 > P3 > Roadmap. No saltes de prioridad.
- **Después de cada fix**: ejecuta `pytest` para verificar.

---

## 7. ARCHIVOS CLAVE

| Archivo | Qué contiene |
|---------|-------------|
| `run_agent.py` | Entry point |
| `core/agent.py` | Orquestador, ciclo A→B→C, PhaseBDeps construction |
| `core/state_manager.py` | Estado persistente (cycle, counters) |
| `phases/phase_a_content.py` | Generación de contenido original |
| `phases/phase_b.py` | Respuestas a comunidad (~2000+ líneas) |
| `phases/phase_c_analytics.py` | Analytics y optimización |
| `services/challenge_solver.py` | CAPTCHA solver |
| `services/claim_checker.py` | Validación de claims en respuestas |
| `services/model_cascade.py` | Cascada de 8 proveedores LLM |
| `services/moltbook.py` | REST client para Moltbook API |
| `services/dedup_store.py` | Store de deduplicación de replies |
| `services/own_post_store.py` | Tracker de posts propios |
| `utils/resilience.py` | Circuit breaker implementation |
| `modes.py` | 5 modos de comunicación |
| `prompt_templates.py` | SYSTEM_PROMPT, AGENT_CHARTER |
| `content_validators.py` | Validadores (DESCONECTADOS) |
| `.env` | Configuración (API keys, tiers, límites) |
| `agent_policy.py` | Política de comportamiento |
| `tests/` | 586 tests |

## 8. CONFIGURACIÓN ACTUAL

```
max_posts_per_day=6
cycle_interval_seconds=300  (5 min)
max_comments_per_day=999
max_comment_replies_per_cycle=8
max_comments_per_post=3
MODEL_TIER_OPUS_MODEL=deepseek-chat
MODEL_TIER_SONNET_MODEL=gemini-2.5-flash
MODEL_TIER_HAIKU_MODEL=gemini-2.0-flash  (circuit breaker PERMANENTEMENTE ABIERTO - quota=0)
token_bucket: 1 write cada 150s
```

---

Empieza con **P0-1 (CAPTCHA Solver)**. Lee el archivo, entiende el flujo completo desde `create_post` hasta `submit_verification`, identifica por qué siempre extrae "32 + 8", y fix it.