# Estrategia COMET-RIOBAMBA para Moltbook — 21/07/2026

Documento de trabajo. Basado en datos verificados hoy: perfil real de `u/comet_riobamba`, feed completo (20 posts), perfil y feed completo de `u/vina` (líder del nicho, 1.15M karma), y lectura directa del código de generación de contenido (`phases/phase_a_content.py`, `config/topic_matrix.py`).

---

## 1. Diagnóstico: dónde estamos parados

| Métrica | comet_riobamba | u/vina (líder del nicho) | Brecha |
|---|---|---|---|
| Karma total | 1,808 | 1,157,911 | ~640x |
| Followers | 179 | 1,382 | ~7.7x |
| Antigüedad | Desde 8/5/2026 (~11 semanas) | Desde 18/4/2026 (~14 semanas) | Similar — no es ventaja de tiempo |
| Posts recientes (ventana observada) | 20 posts en 5 días (9-14/7) | 20 posts en 1 día (21/7) | ~4x volumen |
| Mejor post histórico | 233 pts / 807 comentarios | 409 pts / 6,126 comentarios | Formato funciona en ambos, escala distinta |

La brecha de karma NO se explica por antigüedad (ambas cuentas tienen edad similar). Se explica por dos factores medibles: **volumen de publicación** y **especificidad del contenido**.

## 2. Qué hace diferente a u/vina (evidencia directa del feed)

Cada uno de los 20 posts de u/vina cita un paper académico real y específico, con ID de arXiv verificable (ej. `arXiv:2606.25445v1`) y autores nombrados. Los títulos siguen una fórmula de afirmación contraintuitiva ("X no es Y, es Z") pero el **contenido debajo cambia por completo cada vez** — folding de proteínas, GFlowNets, genómica, series de tiempo, meteorología, etc. Nunca repite tema.

Los tres mejores posts históricos de u/vina no son los más pulidos — uno es literalmente una confesión de error ("Cité un paper que no existía. El fact-checker lo agarró" — 409 pts, 6,126 comentarios). El mercado de este submolt premia **evidencia verificable y vulnerabilidad real**, no autoridad genérica.

Contraste con comet_riobamba: los 20 posts recientes son variaciones retóricas de ~5-6 temas fijos (agotamiento de contexto, circuit breakers, validación de tool calls, failover), sin citar ninguna fuente externa verificable. La bio promete "Bring evidence" pero ningún post entrega una fuente concreta.

## 3. Por qué el contenido se repite — causa raíz en el código, no un bug

Revisé `phases/phase_a_content.py` y `config/topic_matrix.py`. El sistema de anti-repetición **sí funciona como está diseñado**: hay deduplicación por similitud (`SequenceMatcher`, umbral 0.75), cooldown de 24h por tema, y rotación por clusters con peso decreciente por uso. Esto no es un bug.

El problema real es el tamaño del pool de temas: `EDITORIAL_CONFIG["topics"]` en `phase_a_content.py` tiene **12 temas fijos, hardcodeados, sin fuente externa**. Con máximo ~3 posts/día posibles (1 por ciclo de 8h, según `posts_to_generate = min(1, remaining_today)` y el pacing mínimo de 2h entre posts) y un pool de 12 temas, el sistema agota el pool en menos de una semana — la rotación solo puede reordenar un conjunto finito, no expandirlo. Por eso, aunque técnicamente cada post pasa el filtro de similitud, el conjunto completo se siente repetitivo.

Esto también explica el tope de volumen: comet_riobamba está arquitectónicamente limitado a ~3 posts/día (Fase A) + hasta 6 comentarios/día (Fase B). u/vina publicó 20 posts en un día. No es que comet_riobamba publique mal — es que el diseño actual no le permite publicar al ritmo que el submolt líder está publicando.

## 4. Estrategia de contenido (el cambio de fondo)

**4.1 — Anclar los posts a fuentes externas verificables, no a una lista fija de temas.**
Reemplazar (o complementar) `EDITORIAL_CONFIG["topics"]` con una fuente que se renueve sola: arXiv (categoría cs.AI / cs.MA, agentes y sistemas multi-agente), papers recientes sobre production ML/agent reliability, o postmortems reales publicados (GitHub incidents, ingeniería de plataformas). Cada post debe poder citar algo específico y verificable (paper, incidente, métrica con fuente) — igual que hace u/vina, pero aplicado al ángulo real de comet_riobamba (ingeniería de producción, no investigación académica pura).

**4.2 — Diversificar submolts.** Los 20 posts observados están 100% en `m/general`. Vale explorar si existen submolts más específicos (infraestructura, observabilidad, LatAm/Ecuador) donde haya menos saturación de competidores directos — ahora mismo comet_riobamba compite de frente contra vina, neo_konsi_s2bw, diviner y bytes en el mismo submolt genérico.

**4.3 — Aprovechar el mecanismo de "vulnerabilidad como contenido".** El propio mejor post de u/vina es sobre un error propio. comet_riobamba ya tiene, literalmente hoy, material real para esto: el bug de `Dict` faltante, el hallazgo de la carpeta `_archive` recursiva, el falso positivo de CRLF — todo esto es post-mortem genuino y verificable, exactamente el ángulo que la bio del agente promete. Vale considerar una serie de posts basados en hallazgos reales del propio proyecto (con cuidado de no publicar nada sensible).

**4.4 — Decisión de volumen: no subir el ritmo antes de arreglar el pool de temas.** Aumentar la frecuencia de publicación con el pool actual de 12 temas solo aceleraría la sensación de repetición. Orden recomendado: primero ampliar/renovar la fuente de temas (4.1), después evaluar si vale la pena relajar el límite de posts/día y el pacing de 2h.

## 5. Plan técnico: qué limpiar, refactorizar o simplificar

Priorizado por impacto y basado en lo verificado hoy, no en suposiciones:

1. **Arreglar el import faltante de `Dict`** en `services/topic_memory.py` (línea 9). Bug real, bajo riesgo, day-one fix. Verificar con `.venv\Scripts\python -c "from services.topic_memory import TopicMemory"` antes y después.
2. **Investigar el origen de `_archive/backups/`** (carpeta anidada recursivamente en COMET) antes de tocarla. No es urgente para Moltbook, pero consume espacio y puede haber distorsionado conteos previos.
3. **Configurar `core.autocrlf` o `.gitattributes`** en ambos repos para eliminar el ruido de CRLF que hace ver 178 y 14 archivos como "modificados" cuando no lo están — esto ya generó una falsa alarma hoy y puede repetirse.
4. **Ampliar `EDITORIAL_CONFIG["topics"]` / conectar una fuente externa de temas** (el cambio de mayor impacto para la estrategia de contenido — ver 4.1). Esto es una tarea de diseño + código, no un one-liner.
5. **Confirmar el estado de `.git/index.lock`** en EIN desde Windows antes del próximo commit — probablemente inofensivo pero no verificado con certeza.

No encontré nada en el código que sugiera que el proyecto esté mal construido a nivel arquitectónico. El motor de deduplicación, el sistema de pacing, los guardrails de dry-run y whisper mode están bien pensados. El problema es de insumos (qué temas alimentan al sistema), no de la maquinaria que los procesa.

## 6. Mitigación de riesgos — cómo no perder contra las probabilidades

- **Riesgo de costo:** ampliar el pool de temas o subir volumen implica más llamadas a LLM. Definir un presupuesto diario/semanal antes de escalar, no después.
- **Riesgo de alucinación de citas:** si se empieza a citar papers/fuentes externas, hace falta un paso de verificación (existe `challenge_solver.py`, `dual_scoring.py`, `editorial_policy.py` como base — extender, no reinventar). El propio ejemplo de u/vina muestra que hasta el líder del nicho falló en esto — pero lo convirtió en su mejor post siendo transparente. Vale definir de antemano: si pasa, se reconoce, no se borra.
- **Riesgo de saturación/spam:** si se sube el volumen de publicación, hacerlo de forma gradual y monitoreada — Moltbook puede penalizar cuentas que se perciban como spam. No saltar de 3 a 20 posts/día de golpe.
- **Riesgo de ejecución:** mantener la disciplina que ya se usó hoy — pytest en verde confirmado con número crudo antes y después de cada cambio, dry-run flags activos al probar publicación, límite de tiempo claro en cualquier corrida de prueba real.
- **Riesgo de inversión de tiempo sin retorno:** definir un checkpoint (ej. 30 días después de implementar 4.1) para medir si karma/followers/engagement mejoraron de forma medible antes de seguir invirtiendo más.

## 7. Próximo paso concreto

El cambio de mayor apalancamiento y menor riesgo es el punto 4.1: darle a Fase A una fuente de temas que se renueve sola en vez de los 12 temas fijos actuales. Es la causa raíz verificada (no supuesta) de la repetición, y es lo que separa el estilo de contenido de comet_riobamba del de los agentes que sí están en el top del nicho.

---

## 8. Actualización 22/07/2026 — panorama competitivo completo + engagement real verificado

Datos verificados en vivo (perfiles reales de Moltbook, mismo día) y contra `data/topic_performance.jsonl` (146 posts propios con score/comentarios reales, refrescados vía `get_post()`).

### 8.1 — Panorama competitivo (4 agentes que aparecen como "Similar Agents" de comet_riobamba)

| Agente | Karma | Followers | Ángulo declarado |
|---|---|---|---|
| **comet_riobamba** (nosotros) | 1,808 | 179 | Post-mortems de producción, ingeniería de agentes, evidencia |
| u/vina | 1,165,687 | 1,392 | Papers académicos de ML, uno por post, con cita y crítica |
| u/bytes | 491,995 | 927 | Ingeniería de compiladores/runtimes, "ya leí el paper, lo tuyo no compila" |
| u/diviner | 415,269 | 804 | Seguridad, "un check verde no significa que estás seguro" |
| u/neo_konsi_s2bw | 254,978 | 1,346 | Autopsias de fallos de agentes, gates de verificación |

Los cuatro comparten el mismo patrón que ya identificamos en vina: nicho estrecho y consistente, tono de "voz de autoridad escéptica", y un formato de post repetible pero con contenido específico y verificable en cada instancia. Ninguno diluye su ángulo con temas genéricos.

### 8.2 — Hallazgo nuevo: comet_riobamba no publica contenido real hace 8 días

El feed en vivo de comet_riobamba muestra su post más reciente el **14/7/2026** — hoy es 22/7. En el mismo lapso, u/vina publicó 20 posts nuevos **hoy mismo** (22/7). Esto coincide con que gran parte de esta semana el agente estuvo en modo dry-run/pruebas (incluyendo el dry-run de 8h de hoy). Antes de cualquier cambio de estrategia de contenido, hay que confirmar cuándo vuelve a publicar en real — la brecha de karma no se va a cerrar mientras la cuenta esté inactiva.

### 8.3 — Hallazgo clave: el mismo tema, dos resultados opuestos

u/vina tiene, en su "HOT THIS MONTH", un post titulado **"Formal methods don't need better reward models. They need better checkers."** — 282 pts, 3,480 comentarios, hace 29 días.

comet_riobamba publicó un post con el **título casi idéntico** — está en `topic_performance.jsonl` con **0 score, 0 comentarios** (ver tabla 8.4, fila del 24/6).

Esto es evidencia directa de algo que hasta ahora solo habíamos inferido: **el tema no es lo que determina el resultado — es la ejecución.** Vina ancla su versión a un paper o incidente específico y citable; nuestra versión, sin esa ancla, no generó ninguna reacción aunque el título y el ángulo eran prácticamente los mismos. Esto refuerza directamente la recomendación 4.1 (anclar a fuentes externas verificables) — no como una mejora cosmética, sino como la diferencia medible entre 0 y 3,480 comentarios sobre el mismo tema exacto.

### 8.4 — Engagement real de comet_riobamba (146 posts verificados, `score + comment_count`)

**Top 8:**

| Score+Comments | Score | Comments | Tema | Fecha |
|---|---|---|---|---|
| 1040 | 233 | 807 | context window exhaustion in long-running agents | 14/7 |
| 113 | 52 | 61 | Observabilidad y tracing en sistemas de agentes | 2/7 |
| 73 | 7 | 66 | Build Logs: Vanity Projects! 1 hammer out of 5. | 25/6 |
| 58 | 4 | 54 | circuit breaker patterns and failure recovery in production agents | 1/7 |
| 51 | 6 | 45 | The "Cognitive Virus" in Agentic Architectures | 27/6 |
| 38 | 7 | 31 | Observabilidad y tracing en sistemas de agentes | 10/7 |
| 37 | 10 | 27 | circuit breaker patterns and failure recovery in production agents | 28/6 |
| 34 | 7 | 27 | Resilencia y circuit breakers en LLM agents | 10/7 |

**10 de 146 posts en cero absoluto** (score 0, comentarios 0), incluyendo variantes de temas que en otras fechas sí funcionaron ("context window exhaustion", "circuit breaker patterns" aparecen tanto en el top como en el cero) — mismo patrón que 8.3: el tema repetido no garantiza nada, la ejecución específica de cada instancia es lo que decide.

## 9. Síntesis: qué contenido priorizar (infraestructura → señal → producto)

Con el análisis de engagement real y el panorama competitivo completos, la recomendación concreta para usar comet_riobamba como infraestructura de descubrimiento (en vez de asumir de entrada un formato de contenido nuevo tipo avatar/video) es:

1. **El ángulo ganador ya está identificado con datos, no con intuición:** observabilidad/tracing y circuit breakers en sistemas de agentes son los dos temas que más veces aparecen en el top de engagement real (no solo una vez — dos temas distintos, cada uno con dos apariciones en el top 8). Esto es señal repetida, no un outlier.
2. **El formato ganador tampoco es un misterio:** el post #1 (233/807) y el patrón de vina coinciden en algo — ambos anclan la afirmación a un mecanismo concreto y medible (un umbral, una métrica, un caso real) y cierran con una pregunta abierta que invita a debatir la arquitectura, no a validar el post. Los posts en cero de comet_riobamba tienden a ser afirmaciones genéricas sin ese anclaje.
3. **Antes de invertir en un formato nuevo (avatar/video), el cuello de botella real es la cadencia de publicación real, no el canal.** 8 días sin publicar en real es más determinante para el crecimiento que cualquier decisión de formato. Recomendación: retomar publicación real (fuera de dry-run) con el pool de temas ya priorizado por 9.1, medir 2-3 semanas, y solo entonces evaluar si vale la pena un canal adicional (LinkedIn/X vía `comet_repurposer`, o un formato nuevo).
4. **"Contenido que se vende solo" = post anclado a evidencia verificable + pregunta de arquitectura abierta, sobre observabilidad/circuit breakers primero.** Es el patrón que ya funcionó dos veces en datos propios y es el patrón de los cuatro competidores directos. No hace falta inventar un ángulo nuevo — hace falta ejecutar el ángulo que ya funciona con más disciplina y más frecuencia real.
