# Coherencia de documentación — COMET-RIOBAMBA

> **Propósito:** mapa de "qué doc es fuente de verdad de qué", con estado y próxima acción.
> **Regla:** cada dimensión tiene EXACTAMENTE UN doc canónico. Los demás se marcan como derivados o se archivan.
> **Creado:** 2026-09-20.

---

## Tabla de coherencia

| Doc | Declara ser fuente de | Estado | Última actualización | Próxima acción |
|---|---|---|---|---|
| `docs/NORTH_STAR.md` | Objetivo general + específicos + métricas | ✅ Fresh | 2026-09-20 | — |
| `docs/CONTENT_STRATEGY.md` | Estrategia de contenido + engagement | ✅ Fresh | 2026-09-20 | — |
| `docs/PENDING.md` | Ledger de pendientes | ✅ Fresh | 2026-09-20 | Actualizar en cada sesión |
| `docs/DOC_COHERENCE.md` | Este mapa | ✅ Fresh | 2026-09-20 | Actualizar al agregar/archivar docs |
| `docs/AUDIT_PROGRESS.md` | Historia de fixes (append-only) | 🟡 Falta H.12+ | 2026-09-19 | Agregar entries de fixes 20/9 |
| `docs/CONFIG_TRUTH.md` | Config documentada | 🔴 Stale | 2026-09-17 | Agregar day-aware, run_id, allowlist |
| `docs/COMET-RIOBAMBA_REFERENCE.md` | Referencia operativa | 🟡 Tiene aviso desactualización | 2026-09-19 | Revisar tras fixes 20/9 |
| `docs/CLAUDE.md` | Contexto para Claude | 🔴 Dice "Ollama" | 2026-09-13 | Corregir stack (DeepSeek) |
| `docs/RESILIENCIA_OPERATIVA.md` | Resiliencia operativa | 🔴 Dice "NSSM pendiente" | 2026-09-18 | Actualizar (NSSM corre) |
| `docs/PLAN_AUTOSUSTENTABILIDAD.md` | Plan macro | 🟡 Datos a verificar | 2026-09-18 | Corregir cifra claims_tracker |
| `docs/EIN_SERVICE_SPEC.md` | Spec EIN (propuesta) | 🟡 Sin etiquetar | 2026-09-18 | Agregar banner "SPEC PROPUESTA" |
| `README.md` | Cara del repo | 🟡 Pre-fixes 20/9 | 2026-09-19 | Actualizar tabla estado |
| `.env.example` | Template de configuración | 🔴 ~30 keys obsoletas | 2026-09-19 | Reescribir (Bloque 4) |
| `.env` | Config runtime (UNTracked) | ✅ Fresh | 2026-09-20 | — |
| `config/config.py` | Config por código | ✅ Fresh | 2026-09-19 | — |
| `config/schedule.py` | Scheduling day-aware | ✅ Fresh | 2026-09-19 | — |
| `config/auto_appliable.py` | Allowlist auto-mejora | ✅ Fresh | 2026-09-20 | — |

---

## Docs archivados

| Doc | Razón | Fecha | Reemplazado por |
|---|---|---|---|
| `docs/archive/CONTEXTO_COMPLETO_PROYECTO_COMET.md` | 90% solapamiento con DOCUMENTACION_COMPLETA | 2026-09-20 | `docs/NORTH_STAR.md` |
| `docs/archive/DOCUMENTACION_COMPLETA_COMET_RIOBAMBA.md` | v5.0 (30/8), datos históricos | 2026-09-20 | `docs/NORTH_STAR.md` + `README.md` |
| `docs/archive/ESTRATEGIA_MOLTBOOK_2026-07-21.md` | Fusionado con ESTRATEGIA_ENGAGEMENT | 2026-09-20 | `docs/CONTENT_STRATEGY.md` |
| `docs/archive/ESTRATEGIA_ENGAGEMENT_2026-08-30.md` | Fusionado con ESTRATEGIA_MOLTBOOK | 2026-09-20 | `docs/CONTENT_STRATEGY.md` |

---

## Reglas de mantenimiento

1. **Al agregar H.x a AUDIT_PROGRESS:** verificar que los 4 docs canónicos (`NORTH_STAR`, `CONTENT_STRATEGY`, `CONFIG_TRUTH`, `RESILIENCIA_OPERATIVA`) no queden stale.
2. **Al modificar `.env`:** propagar a `.env.example` en el mismo commit.
3. **Al agregar doc nuevo:** registrar en la tabla de arriba con dimensión que cubre.
4. **Al archivar doc:** mover a `docs/archive/`, agregar a tabla "Docs archivados" con razón y reemplazo.
5. **Al cerrar sesión:** actualizar columna "Estado" de cada doc tocado.

---

## Estados válidos

| Estado | Significado |
|---|---|
| ✅ Fresh | Actualizado en las últimas 24h, coherente con código |
| 🟡 Borde | 1-7 días sin actualizar, o tiene aviso de desactualización |
| 🔴 Stale | >7 días sin actualizar, o contradice realidad medida |
| ⚫ Archivado | Movido a `docs/archive/` con razón documentada |

---

*Actualizar cada vez que un doc cambie de estado.*
