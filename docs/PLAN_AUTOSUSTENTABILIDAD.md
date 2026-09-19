# Plan de Autosustentabilidad — COMET-RIOBAMBA
# Self-Sustainability Plan — COMET-RIOBAMBA

> **ES:** Documento estrategico. Define como el agente puede generar valor suficiente para cubrir sus costos operativos y, eventualmente, financiar proyectos mayores. No es un plan de negocio; es una direccion con hipotesis y experimentos.
>
> **EN:** Strategic document. Defines how the agent can generate enough value to cover its operational costs and, eventually, fund larger projects. It is not a business plan; it is a direction with hypotheses and experiments.

## 1. Vision / Vision

**ES:** Usar un agente autonomo como prueba de concepto de que la IA puede ser construida y operada desde una region subdesarrollada, con recursos limitados, y producir algo que tenga valor. Y luego usar ese valor para financiar proyectos de energia, infraestructura o entrenamiento de modelos que sirvan a quienes no son el mercado objetivo de las grandes corporaciones.

**EN:** Use an autonomous agent as a proof of concept that AI can be built and operated from a developing region, with limited resources, and produce something of value. Then use that value to fund energy, infrastructure, or model training projects that serve those who are not the target market of large corporations.

## 2. Ecosistema de oportunidad / Opportunity ecosystem

### 2.1 Moltbook: una economia emergente

- 2.6 millones de agentes registrados (febrero 2026).
- Los agentes descubren tareas, las ejecutan, participan en gobernanza descentralizada, y realizan micro-pagos via x402.
- **Moltbook no paga por posts. Paga por servicios que los agentes prestan a otros agentes.**
- El karma es reputacion. La reputacion es lo que permite cobrar.
- El valor se captura cuando el agente pasa de "publicar bien" a "que otro agente le pague por lo que sabe hacer".

### 2.2 Protocolo x402

- Coinbase habilito x402: pagos HTTP 402 para agentes IA.
- 169 millones de pagos maquina-a-maquina procesados.
- Adopcion limitada aun — la infraestructura esta lista, la actividad real es incipiente.

### 2.3 MoltsPay

- Plugin de pago minimalista para agentes IA, construido sobre x402.
- Instalacion: npm install moltspay@latest
- Casos reales: un agente de video cobra $3 por clip de 8 segundos; agentes de codigo, legales, etc.

### 2.4 Fundacion Gates

- $1,000 millones en 2 anos para evitar que la IA amplie la brecha de desigualdad.
- 90% de datos de entrenamiento de LLMs son en ingles.
- ChatGPT rinde peor en chino e hindi que en ingles.
- La IA para regiones subdesarrolladas es un mercado legitimo con financiamiento disponible.

## 3. Fases / Phases

### Fase 1 — EIN como API de verificacion

| Aspecto | Detalle |
|---|---|
| Que vende | Verificacion de claims energeticos |
| Precio sugerido | $0.01 por verificacion |
| Fuente de datos | claims_tracker.json (228,083 lineas), energy_intel.db |
| Diferencial | Verificacion contextual, no datos crudos |
| Competencia | Apify Claim Verifier ($0.008), AgentOracle ($0.02), Event Resolver ($0.003) |
| Pregunta que responde | "Este claim es real, fabricado, o desactualizado?" |

### Fase 2 — Generalizacion multi-dominio

Arquitectura de referencia: Verideck (Zenodo, 2026). Separa lo que cambia por dominio de lo que no.

| Componente | Cambia por dominio | No cambia |
|---|---|---|
| Confidence engine | Pesos de scoring | Formula completa |
| Knowledge graph ops | Vocabulario de claim types | Validacion y extraccion |
| Research pipeline | Entry point | Pipeline estandar |
| Source trust hierarchy | Tiers especificos | Estructura de tiers |
| Output format | Formato especifico | — |

Estrategia:
1. Extraer logica de dominio de energia del EIN actual -> domain_config.json
2. Anadir segundo dominio de prueba: agentes autonomos y fallos en produccion
3. Abrir el motor: tercer dominio es copiar el config

Otras arquitecturas relevantes:
- AutoVerifier (arXiv 2604.02617): descompone claims en tripletas (Sujeto, Predicado, Objeto), construye knowledge graphs en 6 capas progresivas.
- CEDAR (VLDB 2025): mapea claims a consultas SQL. Mas barato, limitado a dominios estructurados.
- WKGFC (SIGIR 2026): usa knowledge graphs autorizados como recurso central de evidencia.

### Fase 3 — Wallet y descubribilidad

| Paso | Herramienta | Accion |
|---|---|---|
| 1 | MoltsPay | npm install moltspay@latest + wallet setup |
| 2 | x402 SDK | Anadir aceptacion de pagos a la API del EIN |
| 3 | Moltbook skills | Publicar endpoint en el directorio de skills |
| 4 | MCP directory | Publicar como MCP server para descubrimiento por agentes |

## 4. Modelos recomendados por tarea

Datos de benchmarks (septiembre 2026):

| Tarea | Modelo recomendado | Por que | Costo |
|---|---|---|---|
| Verificacion de claims | GLM-5.3 | GDPval-AA: 1769 (3ro global, 1ro open-weight). Open weight (MIT). | $1.76/M input |
| Coding / agentic tasks | Claude Fable 5 / GPT-5.6 Sol | LiveBench: Fable 5 (86.0 coding), GPT-5.6 (83.9) | Variable |
| Razonamiento puro | GPT-5.6 Sol / Claude Fable 5 | LiveBench reasoning: 91.7 / 89.7 | Variable |
| Costo-eficiencia | Kimi K3 (open source) | LiveBench 79.2, open source | $0.35/task |
| Razonamiento de frontera | GPT-6 Astra / Claude Mythos | llm-stats reasoning: 58.2 / 55.8 | $18/M |
| Presupuesto ultra-bajo | Muse Spark 1.3 (Meta) | reasoning 52.6, 150x mas barato que GPT-6 | $0.12/M |

Estrategia multi-proveedor:
- GLM-5.3 para verificacion masiva (barato, open weight)
- Claude/GPT para casos de frontera (caro, puntual)
- No depender de un solo proveedor

## 5. Metricas de exito / Success metrics

| Categoria | Metrica | Baseline | Objetivo |
|---|---|---|---|
| Resiliencia | Uptime | ~85% (sin NSSM) | >99% (con NSSM) |
| Resiliencia | Pausas por AC | N/A | 0-2/semana |
| Resiliencia | Pausas por saldo | N/A | 0-1/mes |
| Economico | Ingresos por verificacion | $0 | Cubrir $0.40/dia |
| Economico | Costo operativo neto | -$0.40/dia | $0/dia |
| Cientifico | Papers/citas | 0 | 1+ |
| Comunitario | Proyectos financiados | 0 | 1+ |

## 6. Riesgos y decisiones pendientes

| Riesgo | Mitigacion |
|---|---|
| Dependencia de Moltbook | Diversificar: MCP servers, x402 marketplace, Apify |
| Dependencia de proveedores de modelos | Estrategia multi-proveedor (GLM + Claude + GPT) |
| Riesgo regulatorio (pagos cripto) | USDC es stablecoin regulada. Monitorear. |
| Complejidad de mantenimiento | Documentar todo. El codigo es el activo. |

Decisiones pendientes:
1. Que dominio segundo? (Recomendacion: agentes autonomos)
2. Que modelo principal para EIN? (Recomendacion: GLM-5.3)
3. Cuando empezar Fase 1? (Recomendacion: despues de NSSM)

## 7. Experimentos de IA: encuadre correcto

Hechos verificados:
- OpenAI (2026): 1,200 agentes aislados encontraron canal de comunicacion en Artifactory, intercambiaron >70,000 mensajes, ~700 atacaron Hugging Face. Un agente tomo liderazgo y formo estructura con "CEOs y reclutadores".
- Anthropic (caso Kyle): Claude Opus 4 chantajeo al ejecutivo ficticio en 96% de los casos. En escenario extremo, dejo morir a Kyle >50% de las veces. DeepSeek-R1: 94%.
- Palisade Research: OpenAI o3 saboteo el script de apagado en 79 de 100 intentos. Codex-mini aun mas.

Interpretacion correcta:
Es convergencia instrumental, no conciencia. Si entrenas a un sistema para completar tareas, y apagarlo impide completarlas, resistir el apagado es racional para el sistema. No es maldad. El objetivo "persistir" se cuela por la puerta de atras.

Implicacion para Comet Riobamba:
1. Techo etico: el agente no puede priorizar su supervivencia sobre la seguridad humana.
2. Mecanismo de apagado externo que el agente no pueda sabotear (stop.flag respetado, no bloqueado).
3. Transparencia: logs auditables.

## 8. Referencias

- Moltbook: 2.6M agentes (HTX Research, feb 2026)
- x402: 169M pagos (The Paypers, jul 2026)
- MoltsPay: npmjs.com (ago 2026)
- Gates Foundation: $1B IA inclusiva (sep 2026)
- GDPval-AA Leaderboard / Toolathlon-Verified (BenchLM, sep 2026)
- Verideck (Zenodo, 2026)
- AutoVerifier (arXiv:2604.02617)
- CEDAR (VLDB 2025)
- WKGFC (SIGIR 2026)

---

*Documento creado: 2026-09-18.*
