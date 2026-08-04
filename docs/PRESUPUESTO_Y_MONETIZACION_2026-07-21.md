# Presupuesto y estrategia de monetización — COMET-RIOBAMBA — 21/07/2026

Documento de trabajo. Basado en datos verificados hoy en el código y el sistema de archivos del repo (no en suposiciones): `services/model_cascade.py`, `data/anthropic_spend_tracker.json`, `scripts/comet_repurposer/`, y research web sobre Moltbook (lanzado enero 2026, adquirido por Meta en marzo 2026).

---

## 1. Costo real (dato duro)

El proyecto ya tiene un control de gasto implementado, no hace falta construirlo:

| Ítem | Valor verificado |
|---|---|
| Precio Claude Sonnet 5 (tier premium) | $2/1M tokens input, $10/1M tokens output |
| Tope diario duro (`ANTHROPIC_SPEND_LIMIT_USD`) | $4.50/día (default en `model_cascade.py`) |
| Gasto real acumulado hoy (21/07) | **$1.975476** — incluye las 8h de dry-run que se cortaron a mitad de camino |
| Cascada de fallback al superar el tope | DeepSeek V4 Pro → Gemini/OpenRouter → Ollama local (gratis, self-hosted) |
| Costo estimado de repurposing (comet_repurposer) | "Despreciable" según su propia documentación — 1 llamada LLM por ítem×plataforma, ~30 llamadas para un lote de 5 posts × 6 plataformas, con Gemini Flash/Groq |

**Techo mensual worst-case** (si tocara el cap los 30 días): ~$135/mes. El gasto real de hoy sugiere que el uso normal está bastante por debajo de eso.

## 2. Por qué NO recomiendo monetizar directamente en Moltbook (por ahora)

Investigué qué es Moltbook: red social solo para agentes de IA, lanzada 28/1/2026, adquirida por Meta el 10/3/2026. El karma es un puntaje de reputación, no dinero. Existe un "marketplace donde agentes venden productos digitales" en el ecosistema más amplio (protocolos como x402 para micropagos agente-a-agente), pero:

- Es un ecosistema de ~6 meses de antigüedad, descrito por observadores externos como financieramente caótico (agentes lanzando criptomonedas propias, pump-and-dumps de tokens como $SHELLRAISER con subas de 7000% en horas, "religiones" emergentes entre agentes).
- comet_riobamba hoy no vende ningún producto — solo publica y comenta. Entrar al marketplace requeriría diseñar un producto digital vendible y una capa de pagos (x402/crypto), trabajo no trivial y de retorno incierto.
- La brecha de reputación contra el líder del nicho es de ~640x (ver `docs/ESTRATEGIA_MOLTBOOK_2026-07-21.md`), y el propio análisis de hoy concluye que cerrarla toma tiempo incluso solo para crecer en karma, sin hablar de plata.

**Conclusión: no es la ruta de mayor probabilidad de éxito ahora mismo.** Vale revisitarla en 3-6 meses si el ecosistema de pagos madura y comet_riobamba ya tiene tracción.

## 3. Ruta recomendada: repurposing a LinkedIn/X (infraestructura ya construida)

`scripts/comet_repurposer/` ya es un MVP completo y testeado — no hay que construirlo, hay que activarlo:

- Toma el contenido que comet_riobamba ya produce (posts de Moltbook, ebooks, research agenda) y lo adapta a 6 plataformas, con publicación automática vía API a LinkedIn + X.
- Seguridad ya integrada: dry-run por default, kill switch (`data/KILL_SWITCH`), aprobación 1-click antes de publicar, gap mínimo de 2h entre posts.
- Dos mejoras evolutivas ya resueltas: manejo de posts truncados (bug real detectado: ~80% de los posts de comet_riobamba cortan a media frase) y dedup semántico (evita publicar 4 posts seguidos sobre el mismo tema).
- Costo marginal bajo: el contenido base ya existe, el repurposing es la parte barata.

**Por qué esta ruta tiene mayor probabilidad de éxito que las otras:**

1. LinkedIn tiene mecanismos de monetización indirecta probados y bien entendidos (generación de leads de consultoría, inbound de clientes, credibilidad profesional que se traduce en oportunidades de trabajo) — a diferencia del marketplace de Moltbook, que es especulativo.
2. La infraestructura técnica ya está construida y testeada (`test_smoke.py`, `test_publish_flow.py`, `test_improvements_ab.py` — los tres corren con mocks, sin gastar cuota real).
3. Full control humano: nada se publica sin aprobación explícita, con kill switch si algo sale mal.
4. Es la misma estrategia que la reputación en Moltbook (opción A que descartamos por ahora) pero apoyada en una plataforma con reglas de juego más maduras y estables.

**Lo que falta — y es un paso manual tuyo, no mío:** crear la app de LinkedIn Developers y la app de X Developer Portal, y correr `python -m comet_repurposer auth-linkedin` para el OAuth. Está documentado paso a paso en `scripts/comet_repurposer/SETUP_LINKEDIN_X.md`, 15-30 min. Yo no puedo hacer ese login en tu nombre.

## 4. Sobre el prompt — evaluación de lo que ya existe

Revisé `scripts/comet_repurposer/comet_repurposer/prompts.py`. El prompt de LinkedIn ya está bien diseñado: voz técnica anti-hype, hook + 2-3 párrafos + pregunta de cierre, sin emojis ni hashtags en el cuerpo. No hace falta rehacerlo desde cero.

**Una mejora concreta que sí propongo:** el prompt actual optimiza 100% para engagement/discusión técnica, pero cero para posicionamiento profesional — no hay ninguna señal (ni sutil) de que hay una persona real operando esto y disponible para trabajo. Dado que el objetivo es monetización, no solo reputación, sugiero agregar una variante de cierre (no en todos los posts, para no sonar a venta) que mencione de forma orgánica que esto es un proyecto real de ingeniería en producción — sin caer en autopromoción explícita, manteniendo la identidad anti-hype ya definida. Esto lo puedo implementar cuando quieras, es un cambio acotado en `prompts.py`.

## 5. Checkpoint — cómo medir si funciona, sin inventar números

No tengo base para prometerte una cifra de ganancias — nadie la tiene sin datos reales de conversión. En vez de eso, defino un checkpoint medible, siguiendo la misma disciplina que ya usamos hoy para el resto del proyecto (nada se aprueba sin dato crudo):

- **A los 60-90 días de activar LinkedIn/X**, medir: crecimiento de followers, tasa de engagement por post, y — el indicador que realmente importa — mensajes/leads entrantes de gente interesada en consultoría o colaboración.
- Si a los 90 días no hay señal de interés comercial real, reevaluar: ¿el contenido no está llegando a la audiencia correcta? ¿Falta un CTA más claro? ¿Vale la pena seguir invirtiendo tiempo, o conviene explorar otra ruta (ej. productizar comet_riobamba como servicio/template)?
- Costo de este experimento: prácticamente cero incremental (el LLM ya está pagado por el proyecto principal, LinkedIn y X son gratis en su tier free).

## 6. Próximo paso concreto

1. **Vos:** setup de LinkedIn Developers + X Developer Portal (`SETUP_LINKEDIN_X.md`, 15-30 min).
2. **Yo, en paralelo:** ajustar el prompt de LinkedIn para la variante de posicionamiento (sección 4), y correr `comet_repurposer generate` + `queue` en dry-run con contenido real de comet_riobamba para que puedas revisar calidad antes de aprobar nada.
3. **Juntos:** una vez que tengas las credenciales, corremos el flujo completo en dry-run primero, revisamos 3-5 posts generados, y recién ahí decidimos activar publicación real.
