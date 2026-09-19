# COMET-RIOBAMBA — Agente Autónomo para Moltbook

> **AVISO DE DESACTUALIZACIÓN** (2026-09-17):
> README reescrito con datos verificables del `.env`, `config/config.py` y
> `docs/AUDIT_PROGRESS.md`. Fuente de verdad en caso de duda:
> - `docs/AUDIT_PROGRESS.md` — progreso de la auditoría integral
> - `docs/CONFIG_TRUTH.md` — estado real de configuración
> - `.env` — valores efectivos en runtime
> - `CHANGELOG.md` — historial de cambios
> Si algo aquí contradice al código o al `.env`, gana el código.

## Descripción

COMET-RIOBAMBA es un agente autónomo que opera en
[Moltbook](https://www.moltbook.com) generando contenido técnico original
(IA, agentes, MLOps, infraestructura, seguridad) y realizando engagement
estratégico con la comunidad.

## Estado actual (2026-09-17)

| Componente | Estado |
|---|---|
| **Versión código** | `AgentVersion = "5.0"` (config/config.py) |
| **Versión CHANGELOG** | 5.11.x (ver `CHANGELOG.md`) |
| **Modelo Phase A** | `deepseek-v4-pro` (tier_pro) |
| **Modelo Phase B** | `deepseek-chat` (tier_flash) |
| **Spend cap DeepSeek** | $0.50/día (`DEEPSEEK_SPEND_LIMIT_USD`) |
| **Spend real típico** | $0.10–0.15/día en operación sana |
| **Cascade** | DeepSeek-only. Cerebras solo para CAPTCHA |
| **Quality Governor** | Activo (7 gates rule-based, 0 costo LLM) |
| **Telegram** | Operativo (alertas + comandos) |
| **Fase A** | Genera contenido (publicación según flag) |
| **Fase B** | Posts propios + feed. Cap: 30 candidatos / 15 replies por ciclo |
| **Fase C** | Watchlist + analytics. Cap: 3 comentarios, $0.15 por ciclo |
| **Energy Intel (EIN)** | Habilitado. Alerts Telegram off (Fase D congelada) |

## Configuración efectiva (2026-09-17)

Fuente: `.env` + `config/config.py`.

### Ciclo y horarios (tz: America/Guayaquil, UTC-5)

```
AGENT_CYCLE_INTERVAL_SECONDS=1800              # 30 min entre ciclos
AGENT_POST_HOURS=11,12,13,14,15,16,17,18,19    # 9h ventana publicación
AGENT_COMMENT_HOURS=11,12,13,14,15,16,17,18,19 # 9h ventana comentarios
AGENT_QUIET_HOURS=20,21,22,23,0,1,2,3,4,5,6,7,8,9,10  # 15h quietas
```

### Límites

```
AGENT_MAX_COMMENTS_PER_DAY=30             # comentarios totales/día
AGENT_MAX_COMMENT_REPLIES_PER_CYCLE=15    # tope replies exitosas/ciclo
AGENT_PHASE_B_OWN_QUEUE_PER_CYCLE=30      # tope candidatos/ciclo
max_posts_per_day=None                    # sin tope (agente decide)
max_comments_per_post=None                # sin tope por post
```

### Fases

```
AGENT_PHASE_B_ENABLED=1
AGENT_PHASE_C_ENABLED=1
AGENT_PRO_TIER_ONLY=0             # 0 = permite fallback a gratis
PHASE_A_GENERATION_TIER=pro       # DeepSeek V4 Pro
```

## Quality Governor (7 gates rule-based)

Filtra contenido sin llamadas LLM (0 costo). En `services/quality_governor.py`.

| Gate | Detecta |
|---|---|
| `text_has_reasoning_leak` | Scaffolds internos ("Here's a thinking process:", "TITLE:") |
| `title_has_scaffold` | Clickbait y scaffold en títulos |
| `text_has_ungrounded_named_entity` | Entidades sin calificador |
| `text_has_ungrounded_software_version` | Versiones sin calificador |
| `text_has_repeated_example_24h` | Repetición en 24h |
| `gate_calidad_entidades` | Agregador de los 3 anteriores |
| `text_has_artistic_excellence` | Calidad narrativa mínima |

## Cascade de modelos

**Activos:**
- `tier_pro` → DeepSeek V4 Pro — generación editorial
- `tier_flash` / `tier_classify` → DeepSeek Flash — tareas ligeras
- `cerebras` → Llama 3.1 8B — **solo** pipeline de CAPTCHA

**Desactivados:** Anthropic, Groq, OpenRouter, Gemini, HuggingFace.

**Características:**
- Circuit breakers por proveedor con cooldowns diferenciados.
- Descuento 50% DeepSeek en horarios valle (fuera de 16:30–00:30 UTC).
- **Spend guard** activo desde 2026-09-13 (Fase 5 auditoría):
  bloquea antes de llamar la API si el gasto acumulado >= cap.
- Tracker persistente: `data/deepseek_spend_tracker.json` (reset diario UTC).
- Sandbox de pensamiento desactivado en DeepSeek V4 Pro.

## Telegram — comandos reales

Implementados en `services/telegram_control.py`:

```
/stats         — métricas generales
/top           — top agentes por karma
/claims        — claims tracker
/next          — próximos temas agendados
/quality       — estado de quality governor
/health        — salud del agente
/pause         — pausar ciclos
/resume        — reanudar
/proposals     — propuestas de mejora
/proposal <id> — ver propuesta específica
/ideas         — ideas capturadas
/learnings     — aprendizajes inbound
/spend         — gasto del día
/inbound       — watchlist inbound
```

Alertas automáticas: engagement spikes, quality alerts, circuit open,
agente detenido.

## Métricas y tracking

**Archivos de estado (runtime, en `data/`):**
- `data/cascade_telemetry.jsonl` — llamadas LLM (JSONL)
- `data/deepseek_spend_tracker.json` — gasto diario DeepSeek
- `data/quota_state.json` — cuotas por proveedor
- `data/degraded_mode_state.json` — modo degradado activo?
- `data/state/health.json` — snapshot del último ciclo
- `data/state/phase_c_state.json` — analytics Phase C

## Comandos útiles

```powershell
# Arrancar agente (dev, foreground)
python run_agent.py

# Arrancar agente (prod, con lock singleton)
.\run-prod.ps1

# Detener gracefully
New-Item data/stop.flag -Force

# Log en vivo
Get-Content logs\agent.log -Tail 50 -Wait

# Reporte diario
python -m scripts.print_daily_report

# Métricas últimos N días
python -m scripts.metrics_last_n_days

# Dashboard de spend
python -m scripts.spend_dashboard

# Inventario de código (auditoría)
python -m scripts.code_inventory

# Auditoría de configuración
python -m scripts.audit_config

# Suite de tests (baseline: 1401 passed)
python -m pytest tests/ -q
```

## Estructura del proyecto

```
core/         — Orquestador del agente (agent.py, state_manager.py)
phases/       — Fases A (contenido), B (respuestas), C (watchlist + analytics)
services/     — Model cascade, Moltbook client, Telegram, tracker
config/       — Configuración (behavior_cfg, credentials, agent_policy)
utils/        — Logging, resiliencia, validadores
prompts/      — Plantillas de prompts + guías de calidad
tests/        — Suite completa (1401 tests)
scripts/      — Utilidades CLI (auditoría, métricas, informes)
scripts/ops/  — Utilidades operativas one-shot
docs/         — Documentación (AUDIT_PROGRESS, CONFIG_TRUTH, runbooks)
```

## Historial de cambios

Ver `CHANGELOG.md` para detalle. Última entrada: **5.11.x (2026-08-29)**.

Últimas actualizaciones mayores documentadas:
- **Fase 2.1 auditoría** — Eliminados duplicados críticos.
- **Fase 5 auditoría** — DeepSeek spend guard implementado y activo.
- **Fix SIGINT (2026-09-17)** — Blindaje de `handle_signal` + persistencia
  de `health.json` en shutdown paths.

## Fuentes de verdad

Ante cualquier duda, el orden de autoridad es:

1. **`.env`** — configuración efectiva en runtime.
2. **`config/config.py` + `config/credentials.py`** — defaults y carga.
3. **`docs/CONFIG_TRUTH.md`** — estado real de config.
4. **`docs/AUDIT_PROGRESS.md`** — progreso de auditoría y fixes.
5. **`CHANGELOG.md`** — historial de versiones.
6. **Este README** — resumen general (puede desactualizarse).

## Contacto

- Operador: AmpiMechita (GitHub).
- Moltbook: `comet_riobamba`.

---

**Repo:** https://github.com/AmpiMechita/comet-riobamba

