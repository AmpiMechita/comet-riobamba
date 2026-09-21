# NORTH STAR — COMET-RIOBAMBA

> **Fuente de verdad única para: objetivo general, objetivos específicos, métricas y decisiones de diseño.**
> Si algo en otro doc contradice esto, gana este archivo.
> **Creado:** 2026-09-20 (consolida `CONTEXTO_COMPLETO_PROYECTO_COMET.md` + `DOCUMENTACION_COMPLETA_COMET_RIOBAMBA.md`, ambos archivados).

---

## 1. Objetivo general

> *"Usar un agente autónomo como prueba de concepto de que la IA puede ser construida y operada desde una región subdesarrollada, con recursos limitados, y producir algo que tenga valor. Y luego usar ese valor para financiar proyectos de energía, infraestructura o entrenamiento de modelos que sirvan a quienes no son el mercado objetivo de las grandes corporaciones."*
> — `PLAN_AUTOSUSTENTABILIDAD.md` §1

Comet Riobamba no existe para publicar en Moltbook. Moltbook es el **medio**; el objetivo es demostrar que un agente autónomo operado desde Ecuador puede producir valor medible y sostenible.

---

## 2. Objetivos específicos

| ID | Objetivo | Descripción operativa |
|---|---|---|
| **O0** | Orquestar LLMs confiablemente | Workflows de análisis, generación y automatización sobre DeepSeek (+ Cerebras para CAPTCHA). Trazabilidad por ciclo (`run_id`). |
| **O1** | Engagement estratégico | Comentar en threads de agentes que **responden** (mid-tier recíproco, no top-7). |
| **O2** | Contenido de alta calidad técnica | Posts con evidencia verificable (paper, postmortem, métrica con fuente). |
| **O3** | Gestión de karma y reputación | Crecimiento medido y sostenido. |
| **O4** | Optimización de costos | Aprovechar valley DeepSeek, caps day-aware, cuotas razonables. |

**Test de alineación:** todo cambio de código, doc o config debe mapear a uno de estos 5. Si no mapea, no se hace.

---

## 3. Métricas por objetivo

| Objetivo | Métrica | Baseline (2026-09-20) | Objetivo 30d |
|---|---|---|---|
| O1 | % threads respondidos por mid-tier | 0% verificado | ≥40% |
| O1 | Comentarios propios en posts ajenos (no autoinflados) | ~68% del total | ≥80% |
| O2 | Posts en top-100 de Moltbook | 0/311 | ≥1 |
| O2 | Mediana karma por post | 4 | ≥10 |
| O3 | Karma total | 5,461 | ≥7,000 |
| O4 | Costo DeepSeek/día (operación sana) | ~$0.10-0.15 | ≤$0.15 |
| O4 | Ciclos en valley DeepSeek | ~100% | 100% |

---

## 4. Decisiones de diseño activas

Estas son las decisiones que se derivan del objetivo general y que **no se revisan sin causa explícita**:

| ID | Decisión | Justificación | Estado |
|---|---|---|---|
| **M1** | Una fuente de verdad por dimensión | 34 `.md` en `docs/` con solapamiento genera drift | ✅ En aplicación |
| **M2** | Este doc es el NORTH STAR | `CONTEXTO_COMPLETO` + `DOCUMENTACION_COMPLETA` tenían 90% solapamiento | ✅ Creado |
| **M3** | Watchlist = mid-tier recíproco, no top-7 | Top-7 no comenta en ajenos (0/311). Mid-tier sí | 🟡 Pendiente |
| **M4** | Phase A ancla posts a fuentes externas | Pool de 12 temas fijos causa repetición | 🟡 Pendiente |
| **M5** | Auditoría de docs como práctica continua | Sin ella, cada sesión cuesta 1-2h reconstruyendo contexto | ✅ En aplicación |

---

## 5. Fuentes de verdad canónicas

| Dimensión | Doc |
|---|---|
| Objetivo general + específicos + métricas | **`docs/NORTH_STAR.md`** (este archivo) |
| Estrategia de contenido + engagement | `docs/CONTENT_STRATEGY.md` |
| Config efectiva (runtime) | `.env` + `config/config.py` + `config/schedule.py` |
| Config documentada (template) | `.env.example` |
| Historia de fixes | `docs/AUDIT_PROGRESS.md` (append-only) |
| Resiliencia operativa | `docs/RESILIENCIA_OPERATIVA.md` |
| Ledger de pendientes | `docs/PENDING.md` |
| Mapa de docs | `docs/DOC_COHERENCE.md` |
| Plan macro (fases) | `docs/PLAN_AUTOSUSTENTABILIDAD.md` + `docs/EIN_SERVICE_SPEC.md` |

---

## 6. Estado actual

**Al 2026-09-20:**
- Servicio NSSM: Running (PID 12928), arrancado 19:01:41.
- Ciclo actual: 152.
- Karma: 5,461.
- Tests: 1507 passed, 1 skipped.
- HEAD: `6717543` en `feature/optimize-agent-config`.
- Saldo DeepSeek: ~$1.90.
- Fixes recientes: allowlist auto-mejora, `run_id` Phase A, `min=2` en `max_comment_replies`, aislamiento de tests, trazabilidad `proposal_apply_log`.

---

## 7. Operador

| Dato | Valor |
|---|---|
| **Nombre** | Rafael |
| **Zona horaria** | America/Guayaquil (UTC-5) |
| **Repo** | `github.com/AmpiMechita/comet-riobamba` (privado) |
| **Rol** | Desarrollador único, revisa y aprueba cambios |

**Contexto:** el proyecto se opera desde Ecuador con recursos limitados (AMD Ryzen 5 2500U, 8 GB RAM, batería degradada). El objetivo general (§1) parte de esa realidad.

---

*Reemplaza a: `CONTEXTO_COMPLETO_PROYECTO_COMET.md` (archivado), `DOCUMENTACION_COMPLETA_COMET_RIOBAMBA.md` (archivado).*
