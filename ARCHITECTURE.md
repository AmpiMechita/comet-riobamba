\# COMET-RIOBAMBA — Arquitectura v5.0



COMET-RIOBAMBA es un agente autónomo para Moltbook organizado en fases A–B–C, con una cascada de modelos y circuit breakers unificados. La versión v5.0 introduce una separación clara entre configuración, credenciales, fases y resiliencia.



\---



\## 1. Visión general



El ciclo principal del agente corre en `core/agent.py`:



\- \*\*Phase A — Contenido\*\*  

&#x20; Genera y publica posts nuevos en Moltbook usando la cascada de modelos (`ModelCascade`) y la política de escritura (`WritePolicyEngine`).



\- \*\*Phase B — Comunidad\*\*  

&#x20; Gestiona respuestas en feed ajeno y en posts propios a través de una implementación unificada `PhaseB`.



\- \*\*Phase C — Engagement\*\*  

&#x20; Analiza actividad, clasifica comentarios y decide dónde responder, delegando en `PhaseCEngagement`.



Cada fase recibe explícitamente sus dependencias mediante dataclasses (`PhaseADeps`, `PhaseBDeps`, `PhaseCDeps`), lo que permite test unitarios y reduce acoplamiento con el objeto `COMETRiobambaAgent`.



\---



\## 2. Configuración y credenciales



\### 2.1 `config/config.py`



Contiene la configuración de \*\*negocio y comportamiento\*\*:



\- `behavior\_cfg` — reglas de frecuencia, límites por día/ciclo, flags de publicación real vs draft.

\- `content\_cfg` — preferencias de longitud, estilo, prompts base.

\- `routing\_cfg` — orden de preferencia de tiers de modelos (local vs cloud).

\- `logging\_cfg` — formato, niveles y destinos de logs.



Ninguna API key vive aquí; solo flags y parámetros de comportamiento.



\### 2.2 `config/credentials.py`



Define el dataclass `Credentials` y el factory `Credentials.from\_env()`:



\- Carga `.env` una sola vez.

\- Valida y centraliza \*\*secrets y endpoints\*\*:

&#x20; - Claves de Moltbook, OpenRouter, Cerebras, Telegram, etc.

&#x20; - Config por tier de modelo (`TierConfig` para Opus/Sonnet/Haiku, etc.).

\- Es el único módulo autorizado a leer variables de entorno (`os.getenv()`).



Cualquier nuevo proveedor debe integrarse añadiendo campos a `Credentials` y usándolos sólo por inyección de dependencias.



\---



\## 3. ModelCascade, circuit breakers y resiliencia



\### 3.1 `services/model\_cascade.py`



`ModelCascade` orquesta el uso de múltiples proveedores de LLM, respetando `routing\_cfg` y `TierConfig`:



\- Resuelve el modelo “ideal” por fase/tarea.

\- Implementa timeouts, retries y degradación de calidad.

\- Usa un `CircuitBreaker` \*\*por provider\*\* para evitar golpear endpoints en fallo continuo.



Todos los límites de retries y cooldowns se obtienen vía variables de entorno \*\*no sensibles\*\* (`MODEL\_CASCADE\_RETRIES`, `\_COOLDOWN\_SECONDS`, etc.).



\### 3.2 `utils/resilience.py` y `services/global\_circuit.py`



`CircuitBreaker` en `utils/resilience.py` es la implementación canónica:



\- Soporta modo en memoria y persistente mediante `CircuitPersistence`.

\- `SQLiteCircuitPersistence` almacena estado global en SQLite (vía `services.persistence`).



`services/global\_circuit.py` es un wrapper delgado:



\- Instancia `CircuitBreaker(name="global\_circuit", persistence=SQLiteCircuitPersistence())`.

\- Expone la API histórica (`should\_skip\_cycle`, `register\_cycle\_result`, etc.).

\- Controla el intervalo dinámico del ciclo con backoff (1.5x).



`services/moltbook\_api\_client.py` usa también `CircuitBreaker` para la API de Moltbook (errores 401/403 como `force\_open`, rate limit no cuenta como fallo duro).



\---



\## 4. Fases y deps



\### 4.1 `phases/deps.py`



Define:



\- `PhaseADeps(model\_cascade, moltbook\_client, write\_policy, behavior\_cfg, posts\_today, metrics, ...)`

\- `PhaseBDeps(model\_cascade, moltbook\_client, behavior\_cfg, agent\_name, metrics, ...)`

\- `PhaseCDeps(model\_cascade, moltbook\_client, write\_policy, telegram\_client, behavior\_cfg, content\_cfg, cycle\_count, límites de Phase C, identity helpers, ...)`



Estas dataclasses encapsulan las dependencias de cada fase. `core/agent.py` es responsable de construirlas y mantener sincronizados los campos mutables (`posts\_today`, `cycle\_count`, límites diarios, etc.).



\### 4.2 Phase A



Archivo principal: `phases/phase\_a\_content.py`



\- Clase `PhaseAContentGeneration(deps: PhaseADeps)`.

\- `execute()` genera posts nuevos, decide publicar o guardar draft según `write\_policy` y `behavior\_cfg`.

\- Usa `phase\_error\_boundary` con `fallback\_return=None` (errores detienen el ciclo).



\### 4.3 Phase B unificada



Archivo principal: `phases/phase\_b.py`



\- Clase `PhaseB(deps: PhaseBDeps)` con API:



&#x20; - `async execute() -> Dict`: entrypoint único para el agente.  

&#x20; - `\_execute\_feed\_replies()` y `\_execute\_own\_post\_replies()` como subfases internas.



\- Combina la lógica rica de circuit breaker y manejo de errores de la implementación antigua (`phase\_b\_replies`) con el constructor desacoplado de `phase\_b\_responses`.

\- Usa `phase\_error\_boundary` con un fallback que devuelve `success=False` y listas vacías, permitiendo que el ciclo continúe.



\### 4.4 Phase C engagement



Paquete: `phases/engagement/`



\- `PhaseCEngagement(deps: PhaseCDeps)` en `\_\_init\_\_.py` como fachada:



&#x20; - Orquesta clasificación, tracking y respuesta.

&#x20; - `execute()` es el único entrypoint para el agente.



\- `classifier.py`:

&#x20; - `classify\_comment`, `priority\_score`, `is\_direct\_question\_to\_me`, `should\_reply`, `looks\_mostly\_english`.



\- `tracker.py`:

&#x20; - Persistencia de posts y comentarios (`tracked\_posts.json`, `comment\_events.jsonl`).

&#x20; - Dedupe, conteo diario, identidad del agente, construcción de reviews.



\- `responder.py`:

&#x20; - Construcción de prompts, invocación a `ModelCascade`, normalización de payloads, `publish\_reply`.



Todo el mojibake original fue corregido; las cadenas en español son UTF‑8 limpio.



\---



\## 5. Manejo de errores, logging y métricas



\### 5.1 `utils/phase\_utils.py`



\- `phase\_error\_boundary(logger, phase\_name, fallback\_return=None)`:

&#x20; - Decorador sync/async para `execute()` de cada fase.

&#x20; - Loguea errores con nivel ERROR, incrementa métricas por fase y decide si relanzar o devolver un valor seguro.



\- `validate\_phase\_deps(deps, required\_attrs)`:

&#x20; - Se usa en `\_\_init\_\_` de las fases para asegurar que las deps tienen los atributos esperados.



\### 5.2 Loggers y métricas



Nombres de logger:



\- `phases.phase\_a\_content`

\- `phases.phase\_b`

\- `phases.phase\_c\_analytics`

\- `phases.phase\_c.engagement`

\- `phases.phase\_c.classifier`

\- `phases.phase\_c.tracker`

\- `phases.phase\_c.responder`



Métricas de error:



\- `phase\_a\_errors`, `phase\_b\_errors`,

\- `phase\_c\_analytics\_errors`, `phase\_c\_engagement\_errors`.



Estas métricas se incrementan dentro de `phase\_error\_boundary` según `phase\_name`.



\---



\## 6. Integración con Moltbook y scripts



\### 6.1 `services/moltbook\_api\_client.py`



Cliente canónico para la API de Moltbook:



\- Métodos snake\_case (`create\_post`, `create\_comment`, `get\_feed`, `get\_comments`, `fetch\_posts`, `post\_reply`, `submit\_verification`, etc.).

\- Alias camelCase legacy eliminados.

\- Usa `Credentials` para API key y base URL, y `CircuitBreaker` para resiliencia.



\### 6.2 Scripts de soporte



\- `scripts/smoke\_test\_api.py` — prueba de humo de conectividad y credenciales.

\- `scripts/retry\_failed\_posts.py` — reintenta publicaciones fallidas leyendo de la outbox.



\---



\## 7. Trabajo futuro



\- Tests unitarios por fase, usando `Phase\*Deps` con mocks.

\- Métricas más detalladas (latencia por fase, ratio de éxito por modelo).

\- Integración de nuevos proveedores de LLM a través de `Credentials` + `ModelCascade`.

