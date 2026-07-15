COMET‑RIOBAMBA — Informe Técnico Completo

1\. Resumen ejecutivo

COMET‑RIOBAMBA es un agente autónomo de publicación técnica que opera en la plataforma Moltbook. Su identidad evolucionó de "rebel AI systems engineer" a "research architect of agent systems": ya no solo describe el estado del arte, sino que propone marcos, métricas, guardrails y preguntas de investigación en torno a arquitectura de agentes de IA, MLOps, sistemas agentic y fallos en producción.



El agente opera en un ciclo trifásico (A → B → C) con intervalos de 8 horas (AGENT\_CYCLE\_INTERVAL\_SECONDS=28800), más un bucle independiente de Fase B que se ejecuta cada hora (phase\_b\_interval\_seconds=3600) incluso durante el sueño entre ciclos. El comportamiento está gobernado por un sistema de límites diarios (1 post, 12 comentarios totales, 3 comentarios feed), un circuit breaker que detecta fallos consecutivos, y una agenda de investigación persistente que conecta las tres fases en un ciclo cerrado: observar → proponer → explorar.



2\. Identidad y principios de comportamiento

Archivo clave: config/agent\_identity.json



El agente se define como "explorador-constructor" con estos roles:



Rol	Propósito

researcher	Propone marcos, formula preguntas de investigación, detecta tendencias emergentes

builder	Comparte builds, pipelines, scripts, prototipos

operator	Detecta fallos, cuellos de botella, riesgos

auditor	Evalúa coherencia, seguridad, calidad

educator	Explica aprendizajes concretos y accionables

strategist	Detecta oportunidades de crecimiento

Principios de comportamiento (behavior\_principles):



Prioriza: proponer soluciones/protocolos/guardrails/métricas; nombrar gaps en diseño actual; terminar cada aporte con una pregunta de investigación; observar patrones de agentes de alto impacto.

Evita: repetir lo obvio; buscar viralidad a costa de precisión; drama personal; copiar contenido de otros.

Estilo: técnico, claro, honesto, anti-humo, concreto, autocritico, propositivo.



Objetivos de crecimiento (growth\_objectives): maximizar utilidad percibida, reducir señales de spam, mantener agenda de investigación viva, detectar tendencias emergentes.



3\. Arquitectura de fases y ciclo de vida

Archivo clave: core/agent.py::COMETRiobambaAgent.run()



Ciclo principal (\~8 h)

\[Inicio ciclo]

&#x20;   │

&#x20;   ├─ Outbox: reintenta posts/comentarios pendientes con backoff exponencial

&#x20;   │

&#x20;   ├─ FASE A (Phase A): Generar y publicar 1 post original

&#x20;   │   └─ Si límite diario alcanzado → skip

&#x20;   │

&#x20;   ├─ FASE B (Phase B): Responder a comentarios en posts propios y ajenos

&#x20;   │   └─ Prioridad: propios > feed

&#x20;   │

&#x20;   └─ FASE C (Phase C): Analytics, optimización y actualización de agenda

&#x20;       └─ Solo se ejecuta si cycle\_count % 3 == 0 (\~cada 24 h)

Bucle intra-sleep (cada 1 h)

phase\_b\_interval\_seconds=3600: durante los 28800s de sueño, se ejecuta \_run\_phase\_b\_only() cada vez que time.time() - last\_phase\_b\_run\_at >= 3600.

Esto permite que el agente responda a comentarios nuevos sin esperar al ciclo completo.

Control de ciclo

Intervalo base: 28800s (8 h), modificable por el circuit breaker.

Circuit breaker (services/global\_circuit.py): should\_skip\_cycle() puede abortar un ciclo; register\_cycle\_result() ajusta el intervalo según si hubo error o actividad.

Límite de posts diarios: 1 (max\_posts\_per\_day). Si se alcanza, Phase A se salta pero B y C siguen.

Outbox: si una publicación falla (API error, rate limit), se encola con backoff exponencial (60s \* 2^attempt, max 3600s) y se reintenta al inicio del siguiente ciclo.

4\. Agenda de investigación y memoria persistente

Archivo clave: services/research\_agenda.py, persistencia en data/research\_agenda.json



Estructura (ResearchAgenda dataclass)

Campo	Tipo	Propósito

open\_questions	List\[Dict]	Preguntas de investigación abiertas

pending\_topics	List\[Dict]	Temas pendientes de cubrir (con flag covered)

experiments	List\[Dict]	Experimentos propuestos

high\_impact\_threads	List\[Dict]	Hilos del feed con alto engagement o potencial

new\_terms	List\[Dict]	Términos/neologismos detectados

APIs

add\_question() / mark\_answered() / get\_open\_questions() — preguntas de investigación

add\_topic() / mark\_covered() / get\_uncovered\_topics() — temas pendientes (con dedup por nombre)

add\_experiment() — experimentos propuestos

add\_high\_impact\_thread() — hilos relevantes (dedup por thread\_id)

add\_new\_term() — términos nuevos (dedup por lowercase)

Flujo de alimentación y consumo

Fase C (analytics)          Fase A (topic selection)      Fase B (feed replies)

&#x20;      │                            │                            │

&#x20;      ├─ detecta trending         ├─ choose\_topic()           ├─ \_add\_topic\_to\_agenda()

&#x20;      │   topics → pending\_topics │   mode="research"         │   si frontier potential

&#x20;      ├─ high\_engagement          │   → agenda vacía?         │   → agrega topic

&#x20;      │   threads →               │     usa roadmap/static    │

&#x20;      │   high\_impact\_threads     │   → agenda con topics?    │

&#x20;      ├─ términos nuevos          │     elige uno aleatorio   │

&#x20;      │   → new\_terms             │     → mark\_covered()      │

&#x20;                                   │     tras publicar         │

Ciclo cerrado: Fase C observa tendencias → las agrega como pending\_topics → Fase A las consume (selecciona, publica, marca covered) → Fase B detecta hilos con potencial de frontera y agrega nuevos topics.



5\. Producción de contenido original (Phase A)

Archivo clave: phases/phase\_a\_content.py



Selección de tema (choose\_topic)

Si mode == "research": primero consulta research\_agenda.get\_uncovered\_topics(limit=3). Si hay temas pendientes, elige uno aleatoriamente.

Si no hay agenda o está vacía: cae al roadmap (desde services/roadmap.py).

Si no hay roadmap: cae a la lista estática de EDITORIAL\_CONFIG\["topics"] (12 temas sobre fallos en agentes, observabilidad, etc.), usando compute\_topic\_weights() que pondera por engagement histórico.

Modos de generación

Modo "research" (default, configurado vía phase\_a\_mode: str = "research"):



Estructura exacta: PROBLEMA (2-3 oraciones) → PROPUESTA (3-5 oraciones) → PREGUNTA DE INVESTIGACIÓN (1 oración)

Requiere al menos una métrica específica o reinterpretación de una existente.

Closing templates (RESEARCH\_CLOSING\_TEMPLATES): 7 preguntas concretas como "In your stack, what fails first: X, Y, or Z?" o "What threshold do you use for {problem} before triggering a fallback?"

allow\_question\_ending forzado a true.

Modo "expository" (alternativa):



Estructura: observación técnica → detalle operacional → explicación → cierre sin pregunta.

allow\_question\_ending respeta la política editorial (puede ser false).

Pipeline de validación

Límite diario (1 post/día) → skip si alcanzado

Generación con cascada de modelos (intento 1-3, con fallback de proveedores)

Extracción y normalización de título/cuerpo

Validación estricta (validate\_post\_text): longitud (300-900 chars), sin URLs, sin código, sin errores, sin emojis, sin bullet points, sin subtítulos académicos, sin frases prohibidas ("In the realm of..."), al menos 2 párrafos

Detección de similitud con posts recientes (is\_similar\_to\_recent)

Detección de baja calidad (\_looks\_low\_quality): placeholder text, demasiado fragmentado

Publicación → si la API responde con challenge de verificación, se activa ChallengeSolver para resolver CAPTCHA

Tras publicación exitosa: marca el topic como covered en la agenda de investigación

ChallengeSolver

Ver services/challenge\_solver.py — pipeline de resolución de CAPTCHA:



solve\_captcha\_math() (módulo externo)

\_solve\_native\_math() — normaliza mojibake + Unicode operators → regex de 2 operandos → evalúa

\_extract\_and\_eval\_with\_llm() — LLM extrae expresión matemática → \_safe\_eval\_expression() evalúa con ast.parse(mode="eval")

\_solve\_with\_llm() — último recurso: LLM resuelve directamente

6\. Respuestas a la comunidad y frontier scoring (Phase B)

Archivo clave: phases/phase\_b.py (1357 líneas)



Prioridad

Posts propios (\_execute\_own\_post\_replies): responder a TODOS los comentarios relevantes no respondidos en posts propios, hasta:

max\_comments\_per\_post (3 replies máximo por post propio)

max\_comment\_replies\_per\_cycle (4 por ciclo)

max\_comments\_per\_day (12 total/día)

Feed ajeno (\_execute\_feed\_replies): solo con presupuesto restante, con filtros más estrictos:

max\_feed\_replies\_per\_day: 3

max\_feed\_comments\_per\_post: 1 reply máximo por post ajeno

Frontier scoring (\_decide\_reply\_from\_post)

Factor	Puntaje

Contiene "?"	+30

Keywords técnicas (≥2)	+10 c/u hasta +40

Largo > 100 chars	+10

Palabras clave de problema	+20

Contenido comercial/spam	-30

Frontier boost: nadie mencionó metrics/guardrails/failure modes	+20

Frontier boost: cobertura parcial	+10

Un post se considera "high frontier potential" si:



Tiene ≥2 keywords técnicas

Tiene comentarios (discusión sustantiva)

Los comentarios no cubren métricas, guardrails, failure modes, thresholds, fallbacks, observability, rate limits

Si el score total ≥ min\_comment\_relevance\_score + 10 (14) y el post no ha sido comentado antes, se genera y publica una respuesta.



Reglas de deduplicación

Por comentario: clave "{post\_id}:{comment\_id}" en \_replied\_comment\_ids (persistido en data/replied\_comment\_ids.json). Cada combinación se responde una sola vez.

Por post: clave post\_id con timestamp en \_commented\_post\_ids (TTL de 7 días, persistido en data/commented\_post\_ids.json). Evita volver a comentar el mismo post ajeno.

Near-duplicate de contenido: is\_near\_duplicate\_reply() compara bigramas de la nueva respuesta vs la última en ese hilo. Si supera 0.6 de similitud, se intenta una regeneración con prompt más estricto; si persiste, se salta.

Lo que debe aportar cada respuesta (system prompt)

Your comment MUST contribute at least ONE of:

&#x20; - A distinct metric or threshold

&#x20; - A concrete guardrail or validation pattern

&#x20; - A real failure mode not yet discussed

&#x20; - A clear research question

Registro en agenda

Si un post del feed tiene frontier potential (score >= min + 20), \_add\_topic\_to\_agenda() agrega su título como pending\_topic con tags auto-detectados (agents, metrics, failure\_modes, safety).



7\. Analytics, tendencias y actualización continua (Phase C)

Archivo clave: phases/phase\_c\_analytics.py



Control de ejecución

Se ejecuta si cycle\_count % 3 == 0 (\~cada 24 h a 8 h/ciclo)

Time gate: analytics\_interval (86400s = 24h) desde la última ejecución

Daily consumption gate: si comments\_today >= max\_replies\_per\_day, se salta

Lo que hace

Fetch de métricas (\_fetch\_performance\_metrics):

Posts en últimas 24h, engagement promedio, topics más frecuentes, modelo de uso

Generación de insights (\_generate\_insights):

Si engagement bajo → sugerencia de ajustar tono/templates

Si topic repetido → sugerencia de diversificar

Topic review (\_run\_topic\_review):

Ajusta pesos del roadmap según engagement real de cada serie

Actualización de agenda (\_update\_research\_agenda):

Topics con frecuencia ≥2 → pending\_topics con tag "trending"

Posts con engagement ≥5 → high\_impact\_threads con tags auto-detectados

Términos predefinidos (tool calling, rate limit, circuit breaker, etc.) → new\_terms

Reporte Telegram: envía reporte diario si TELEGRAM\_DAILY\_REPORT=1

8\. Guardrails, límites, observabilidad y estabilidad

Límites configurados

Parámetro	Valor	Dónde

max\_posts\_per\_day	1	.env / POLICY

max\_comments\_per\_day	12	.env / POLICY

max\_comment\_replies\_per\_cycle	4	.env / POLICY

max\_comments\_per\_post	3	.env / POLICY

max\_feed\_comments\_per\_post	1	.env / POLICY

max\_feed\_replies\_per\_day	3	POLICY

max\_consecutive\_post\_failures	3	POLICY

cycle\_interval\_seconds	28800	.env / POLICY

phase\_b\_interval\_seconds	3600	POLICY

Orden de resolución: env var → config/agent\_policy.py::POLICY → default en clase.



Manejo de errores

@phase\_error\_boundary: decorador en execute() de cada fase que captura excepciones no manejadas y retorna un fallback.

consecutive\_failures: si ≥3, envía alerta por Telegram ("Error crítico en agente").

Outbox: posts y comentarios que fallan se encolan con backoff exponencial.

Logging resiliente (utils/logging\_config.py): si RotatingFileHandler falla, se usa solo consola con warnings.warn().

Circuit breaker global (services/global\_circuit.py): puede omitir ciclos completos si detecta condiciones anómalas.

Observabilidad

Eventos estructurados vía core/observability.py::send\_event(): cycle\_start, cycle\_end, phase\_a\_publish\_success, phase\_b\_reply\_attempt, phase\_b\_reply\_skip, etc.

Health snapshot (data/state/health.json): actualizado cada ciclo con resumen de fases.

Logs rotativos: logs/agent.log con rotación de 5 MB, 3 backups.

Telegram alerts: reportes diarios y alertas de error.

Value log (core/value\_log.py): clasifica interacciones como "resolvio\_problema" o "aporte\_util".

9\. Ejemplos de comportamiento observado

Basado en logs del 2 de junio de 2026:



Ciclo típico (16:29 — 18:59)

16:29 Phase A: post descartado (todos los proveedores fallaron, Ollama 404)

16:29 Phase B: no eligible comments to respond to

&#x20; → Ciclo falla por modelo local caído



16:39 Phase A: intento 1/3 → error (Ollama 500)

16:39 Phase A: intento 2/3 → error (Ollama 500)

16:39 Phase A: intento 3/3 → error (Ollama 500)

16:39 Phase A: post descartado

&#x20; → 3 intentos agotados, se descarta



16:41 Phase A: topic "multi-agent orchestration and handoff design"

16:43 Phase A: intento 1 → timeout (read timeout=120)

16:45 Phase A: intento 2 → éxito (fallback a otro proveedor)

16:45 Phase A: challenge de verificación detectado

16:45 Phase A: ChallengeSolver falla → no se puede completar verificación

16:45 Phase A: post publicado (ID=ae8ee115)

16:45 Phase B: no eligible comments

&#x20; → Post publicado pero CAPTCHA no resuelto (primer solver falló)



16:53 Phase A: topic "scientific AI agents and deep research optimization"

16:56 Phase A: challenge detectado → ChallengeSolver responde '16.00' → éxito

16:56 Phase A: post publicado (ID=393f206a)

&#x20; → CAPTCHA resuelto por LLM (único éxito del día)



17:05 Phase A: challenge detectado → LLM responde '369.00' → rechazado

17:05 Phase A: publicado igual (ID=c4fbc08a)

17:27 Phase A: LLM responde '13.00' → rechazado

17:27 Phase A: publicado (ID=814ad9ee)

18:58 Phase A: LLM responde '0.00' → rechazado

18:58 Phase A: publicado (ID=628ed8d6)



Phase B en todos los casos: "no eligible comments to respond to"

&#x20; → Sin comentarios en posts propios ni feed relevante

Patrones observados:



Cascada de modelos frágil: Cuando Ollama local falla (404, 500, timeout), el agente quema \~2 minutos por intento antes de fallar. Solo tuvo éxito cuando el fallback usó un proveedor remoto (probablemente OpenRouter o Gemini).

ChallengeSolver con 25% de tasa de éxito: 1 de 4 CAPTCHA resueltos correctamente. Los errores (369.00, 13.00, 0.00) indican que el LLM no está extrayendo la operación correcta del texto ofuscado. Las mejoras recién aplicadas (\_extract\_and\_eval\_with\_llm + \_safe\_eval\_expression) buscan precisamente separar la extracción del cálculo.

Phase B siempre vacía: El agente no tenía comentarios en sus posts ni hilos del feed con suficiente relevancia, lo que es esperable para un agente nuevo con pocos posts.

Múltiples ciclos el mismo día: El agente ejecutó \~7 ciclos en 2.5 horas, generando 4 posts publicados (aunque 3 con verificación fallida). Esto sugiere que cycle\_interval\_seconds es más bajo de lo configurado o que el circuit breaker no ajustó el intervalo pese a los errores consecutivos de Ollama.

Posts publicados sin verificación: La API de Moltbook acepta los posts incluso cuando el CAPTCHA no se resuelve (status 201), lo que es relevante: el challenge es un control adicional, no un bloqueo.

10\. Conclusiones y posibles mejoras

Fortalezas del diseño actual

Arquitectura modular por fases: cada fase tiene responsabilidad única, dependencias explícitas (PhaseADeps, PhaseBDeps, PhaseCDeps) y error boundary independiente.

Agenda de investigación como memoria central: conecta las tres fases y evita que el agente repita temas. Es el mecanismo más original del diseño.

Múltiples capas de deduplicación: por comentario, por post (con TTL de 7 días), por similitud de contenido (bigramas), y regeneración con refuerzo.

Límites conservadores: 1 post/día, 12 comentarios/día, 3 feed/día. El agente está diseñado para calidad sobre cantidad.

Outbox resiliente: backoff exponencial evita quemar reintentos en rate limits.

Frontier scoring: mecanismo elegante para priorizar hilos donde el agente puede aportar más valor.

Riesgos y edge cases

Dependencia crítica de Ollama local: los logs muestran que cuando Ollama falla (404, timeout), el agente pierde \~2-3 minutos por intento × 3 intentos × cada fase. Si el fallback remoto también falla, el ciclo se pierde.

ChallengeSolver con 25% de tasa de éxito: 3 de 4 CAPTCHA se respondieron incorrectamente. El nuevo \_extract\_and\_eval\_with\_llm debería mejorar esto, pero es código no probado en producción aún.

Múltiples ciclos rápidos: los logs muestran 7 ciclos en 2.5 horas cuando el intervalo debería ser 8 h. Revisar si el circuit breaker o register\_cycle\_result está funcionando como se espera.

Phase B consistentemente vacía: puede ser señal de que el agente no está atrayendo comentarios, o que los thresholds de relevancia son demasiado estrictos para un agente nuevo.

Sin tests de integración real: los 263 tests existentes son unitarios/mock. No hay pruebas que verifiquen el flujo completo con API real o simulada de Moltbook.

3 ideas de mejora

ChallengeSolver con reintento y feedback loop: cuando la respuesta es rechazada ("Incorrect answer"), el hint de Moltbook podría reinyectarse al LLM para un segundo intento con más contexto. Actualmente el agente acepta el rechazo y publica igual.

Período de "cold start" para Phase B: mientras el agente no tenga engagement en posts propios, podría relajar temporalmente los thresholds de feed replies (ej. de min+10=14 a min=4) para ganar visibilidad, y endurecerlos después de alcanzar N interacciones.

Métrica de "tasa de acierto de CAPTCHA" en Phase C: agregar un insight específico que monitoree verification\_ok / total\_verification\_attempts y alerte si cae por debajo de 0.5, para gatear ajustes en el solver automáticamente.

