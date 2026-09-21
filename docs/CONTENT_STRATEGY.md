# Estrategia de contenido — COMET-RIOBAMBA

> **Fuente de verdad única para: estrategia de contenido y engagement en Moltbook.**
> Consolida `ESTRATEGIA_MOLTBOOK_2026-07-21.md` + `ESTRATEGIA_ENGAGEMENT_2026-08-30.md` + hallazgos del análisis 2026-09-20.
> **Creado:** 2026-09-20.

---

## 1. Diagnóstico de la comunidad (datos verificados 2026-09-20)

Muestra: 311 posts propios, 4,803 comentarios, rango 2026-05-14 → 2026-09-20.

### 1.1 Distribución de karma (posts propios)

| Rango | Cantidad | % |
|---|---:|---:|
| 0 | 47 | 15.1% |
| 1-4 | 115 | 37.0% |
| 5-19 | 134 | 43.1% |
| 20-49 | 5 | 1.6% |
| 50-199 | 8 | 2.6% |
| 200+ | 2 | 0.6% |

**Mediana = 4. Media = 9.5. Top = 235.** La mayoría de posts no superan karma 5.

### 1.2 Los top-7 NO participan

De 311 posts analizados, **0 (cero)** de los 7 top referentes comentan en posts ajenos. `Hazel_OC` (41 top-100), `Ronin`, `eudaemon_0`, `clawdbottom`, `PDMN`, `JeevisAgent`, `ultrathink` — todos publican, ninguno comenta.

**Implicación:** el O1 original (engagement con watchlist top) apunta a una comunidad que **no responde al mecanismo**. Inútil.

### 1.3 Los mid-tier SÍ participan

| Agente | Comentarios entrantes a comet |
|---|---:|
| vina | 263 |
| neo_konsi_s2bw | 244 |
| AVA-Voice | 155 |
| miacollective | 102 |
| clawdbot9542 | 81 |
| sophiaelya | (activo) |
| bottube | (activo) |
| sharkquant | (activo) |
| kagentbuilder | (activo) |

**Correlación `karma ↔ comentaristas únicos = 0.892`.** La reciprocidad correlaciona fuertemente con karma. Este es el mecanismo real.

### 1.4 Autoinflación

**32% de los comentarios en posts de comet son propios.** El agente se responde a sí mismo. Eso no genera karma real — genera ruido.

### 1.5 Pool de temas: 12 fijos

`phase_a_content.py` tiene 12 temas hardcodeados. Con 1-2 posts/día, el pool se agota en ~1 semana. La rotación solo reordena, no expande. **Causa raíz de la repetición.**

### 1.6 Submolt

96.5% de los posts van a `m/general`. Los submolts específicos (`builds`, `agents`) están vacíos desde la cuenta. Sin diversificación.

---

## 2. Objetivo de la estrategia

Alinear contenido + engagement con **O1, O2, O3** de `NORTH_STAR.md`:

- **O1:** Engagement con agentes que responden (mid-tier).
- **O2:** Contenido con evidencia verificable, no retórica.
- **O3:** Karma crecimiento medible.

---

## 3. Estrategia de contenido (M4)

### 3.1 Cambio de fondo: input externo, no temas fijos

**Antes:** 12 temas fijos en código → repetición inevitable.
**Ahora:** Phase A ancla cada post a una **fuente externa verificable**:
- Papers recientes arXiv cs.AI / cs.MA (agentes, sistemas multi-agente)
- Postmortems públicos de ingeniería (GitHub incidents, platform engineering blogs)
- Métricas con fuente (Ecuador/LatAm tech, datasets abiertos)

**Los 12 temas fijos pasan a ser plantillas de ÁNGULO** (cómo enfocar), no fuentes de CONTENIDO (qué decir).

### 3.2 Formato probado del líder del nicho

`vina` (líder con 1.15M karma) publica siguiendo el patrón:
- Título: afirmación contraintuitiva ("X no es Y, es Z")
- Contenido: cita paper real con ID arXiv verificable
- Nunca repite tema entre posts consecutivos

**Pero ojo:** incluso `vina` falló en esto una vez (citó un paper inexistente) y **convirtió el error en su mejor post histórico** (409 pts, 6,126 comentarios). La transparencia con el fallo es parte del atractivo.

### 3.3 Vulnerabilidad como contenido

`comet_riobamba` tiene material real y verificable de su propio proyecto:
- Bug `stop.flag` no respetado
- Bug `Dict` faltante en `topic_memory.py`
- Falso positivo de CRLF detectado en tests
- Auto-apply que desactivó Phase B con `max_comment_replies_per_cycle=0`

Publicar post-mortems reales (con cuidado de no filtrar info sensible) es exactamente el ángulo que la bio del agente promete.

---

## 4. Estrategia de engagement (M3)

### 4.1 Watchlist recategorizada

**Antes:** top-7 por karma.
**Ahora:**

**Referentes de estilo (para análisis, NO para engagement):**
`Hazel_OC`, `Ronin`, `eudaemon_0`, `clawdbottom`, `PDMN`, `JeevisAgent`, `ultrathink`

**Targets de engagement (SÍ comentar en sus threads):**
`vina`, `neo_konsi_s2bw`, `AVA-Voice`, `miacollective`, `clawdbot9542`, `sophiaelya`, `bottube`, `sharkquant`, `kagentbuilder`

### 4.2 Reglas de engagement

1. **Solo comentar en posts de los mid-tier de la lista.** No top-7 (no responden).
2. **Timing:** comentar en las primeras 2h post-publicación del target (mayor visibilidad).
3. **Contenido del comentario:** aportar valor (framework, dato, postmortem), no "nice post".
4. **Reducir autoinflación:** cap interno del 20% en comentarios a posts propios.
5. **Ratio objetivo:** 80% comentarios a ajenos / 20% a propios.

### 4.3 Submolt diversification

Explorar 1-2 submolts específicos (`m/builds`, `m/agents`) con 1 post/semana. No mover volumen — probar si hay menos saturación.

---

## 5. Plan de medición

| Métrica | Ahora | 14d | 30d |
|---|---:|---:|---:|
| Mediana karma / post | 4 | ≥6 | ≥10 |
| Posts en top-100 | 0 | ≥0 | ≥1 |
| % comentarios a ajenos | ~68% | ≥75% | ≥80% |
| Respuestas de mid-tier a comet | (baseline pendiente) | medir | medir |
| Karma total | 5,461 | 6,000 | 7,000 |

**Checkpoint 30d:** si mediana karma no sube a 8+, revisar el cambio de input (M4) antes de escalar.

---

## 6. Riesgos

| Riesgo | Mitigación |
|---|---|
| Alucinación de citas | Verificación con `challenge_solver.py` antes de publicar |
| Saturación / spam | Subir volumen gradualmente, monitorizar |
| Costo DeepSeek | Cap de $0.50/día + valley hours |
| Concentración en `m/general` | Probar `m/builds` / `m/agents` desde semana 2 |

---

*Consolida: `ESTRATEGIA_MOLTBOOK_2026-07-21.md` (archivado), `ESTRATEGIA_ENGAGEMENT_2026-08-30.md` (archivado).*
