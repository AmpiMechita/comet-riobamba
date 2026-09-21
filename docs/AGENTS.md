# AGENTS.md — COMET-RIOBAMBA

> Onboarding para agentes AI que trabajan sobre este repo. Si algo aquí contradice al código o al `.env`, gana el código.
> Reemplaza a `CLAUDE.md` (que queda como pointer por compatibilidad).

## 1. Qué es este proyecto

COMET-RIOBAMBA es un agente autónomo de contenido técnico en [Moltbook](https://www.moltbook.com). Genera posts técnicos, comenta en threads de otros agentes y ajusta su comportamiento con métricas de engagement.

- Objetivo general + específicos + métricas: `docs/NORTH_STAR.md`
- Estrategia de contenido y engagement: `docs/CONTENT_STRATEGY.md`

## 2. Stack técnico (actual, 2026-09-20)

- **Lenguajes:** Python 3.14, PowerShell 7.6.
- **LLMs (producción hoy):** DeepSeek v4-pro (Phase A), deepseek-chat/flash (Phase B/C). Cerebras solo para CAPTCHA. Ollama no está en uso.
- **LLMs (plan macro, Fase 1 EIN, no implementado):** GLM-5.3, Claude/GPT frontera, Muse Spark. Ver `docs/PLAN_AUTOSUSTENTABILIDAD.md` §4.
- **Persistencia:** SQLite (`data/comet_state.db`), JSONL (`data/*.jsonl`), JSON (`data/*.json`).
- **Servicio:** NSSM Windows `CometRiobamba` (SYSTEM, Automatic).
- **OS:** Windows 11 Home 24H2, build 26100.
## 3. Estructura del repo

- `run_agent.py` — punto de entrada. NO usar `main.py`, `agent.py`, `bot.py`.
- `core/agent.py` — orquestador del ciclo principal.
- `phases/` — `phase_a_content.py` (contenido), `phase_b/` (replies, subdirectorio), `phase_c_analytics.py`, `phase_c_watchlist.py`.
- `services/` — clientes (Moltbook, DeepSeek), resiliencia (pause_controller, battery_monitor, balance_guard), auto-mejora (proposal_applier).
- `config/` — `config.py`, `credentials.py`, `schedule.py`, `auto_appliable.py`, `topic_matrix.py`.
- `docs/` — ver §5.
- `tests/` — 1507 passed, 1 skipped.
- `data/` — estado runtime (gitignored selectivo).
- `scripts/` — herramientas read-only de análisis.

## 4. Convenciones

- **Idioma:** español en comentarios/mensajes; inglés en output público a Moltbook.
- **UTF-8 sin BOM.** Line endings: respetar los del archivo original (CRLF en la mayoría).
- **Logs:** `logs/service_stdout.log` + `logs/service_stderr.log` (rotación 5 MB).
- **Backups:** `backups/<nombre-fix>-YYYYMMDD-HHMMSS/` antes de tocar archivos.
- **Commits atómicos**, mensaje español, formato `tipo(scope): descripción`.
## 5. Documentación — dónde ir

| Necesito... | Leer |
|---|---|
| Objetivo general + específicos + métricas | `docs/NORTH_STAR.md` |
| Estrategia de contenido y engagement | `docs/CONTENT_STRATEGY.md` |
| Config efectiva (runtime) | `.env` + `config/config.py` + `config/schedule.py` |
| Config documentada (template) | `.env.example` + `docs/CONFIG_TRUTH.md` |
| Historia de fixes y auditoría | `docs/AUDIT_PROGRESS.md` |
| Resiliencia operativa | `docs/RESILIENCIA_OPERATIVA.md` |
| Pendientes abiertos | `docs/PENDING.md` |
| Mapa de docs | `docs/DOC_COHERENCE.md` |
| Plan macro (autosustentabilidad) | `docs/PLAN_AUTOSUSTENTABILIDAD.md` |
| Spec EIN (propuesta, no implementada) | `docs/EIN_SERVICE_SPEC.md` |
| Arquitectura técnica | `docs/ARCHITECTURE.md` + `docs/ARCHITECTURE_GUIDELINES.md` |
| Runbooks | `docs/RUNBOOK_AGENT.md`, `docs/RUNBOOK_D1.md` |
| Principios inviolables | `docs/BUILD_PROMPT_from_scratch.md` §1 |

## 6. Operar el servicio

    $nssm = 'C:\comet-riobamba-v31\tools\nssm.exe'
    $raw = (& $nssm status CometRiobamba | Out-String)
    ($raw -replace '\s+', ' ').Trim()

    # Restart (NUNCA nssm restart — deja servicio STOPPED)
    & $nssm stop CometRiobamba
    Start-Sleep -Seconds 20
    & $nssm start CometRiobamba

**NO ejecutar python run_agent.py desde sesión normal** — dos agentes escribiendo al mismo SQLite.
## 7. Al reanudar una sesión

1. Correr bloque de estado: NSSM + python procs + tail log + saldo + agent_state.
2. Ver docs/PENDING.md filas OPEN prioridad Alta.
3. Ver docs/DOC_COHERENCE.md para docs stale.
4. Decidir foco con el usuario.

---

*Última revisión: 2026-09-20. Reemplaza a CLAUDE.md.*