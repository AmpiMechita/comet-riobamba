# PENDING.md — Ledger de pendientes COMET-RIOBAMBA

> **Regla de oro:** nunca borrar filas. Marcar `DONE` o `REJECTED` con fecha + commit.
> **Al abrir sesión:** leer filas OPEN prioridad Alta.
> **Al cerrar sesión:** agregar pendientes nuevos + marcar resueltos con commit.
> **Creado:** 2026-09-20 (bootstrap desde 6 handoffs + sesión 20/9).
> **Última actualización:** 2026-09-24 (jueves, UTC-5). P-071 DONE (fix produccion, commit feac722). Sesion P-072 (Sonnet 4.6).
> Ver `HANDOFF_2026-09-23.md` + `PROMPT_APERTURA.md` para retomar.

---

## Alta prioridad (verificar / hacer próximas 48h)

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-001 | DONE | 2026-09-19 | Bug `stop.flag` ignorado la primera vez (fix desplegado; verificacion mid-ciclo diferida) | Handoff 18/19 §7 |
| P-002 | DONE | 2026-09-19 | Verificar NSSM arranca tras reboot real de Windows. VERIFICADO 23/9: boot 17:39:47, servicio auto-arranco 17:40:13 (PID 6840), ciclo #283 OK | Handoff 18/19 §13.3 |
| P-003 | DONE | 2026-09-20 | Verificar `run_id` en producción (Phase A, lunes con cap reset) | Sesión 20/9 §15.3 |
| P-004 | DONE | 2026-09-20 | Verificar `run_id` + `timestamp` ISO en `proposal_apply_log` | Sesión 20/9 |
| P-005 | DONE | 2026-09-20 | Verificar cap weekday efectivo `max_posts_per_day=1` el lunes | Sesión 20/9 §15.4 |
| P-006 | DONE | 2026-09-20 | Post-mortem incidentes `model_error` (sep 1, 2, 10). CERRADO 23/9: docs/POSTMORTEM_MODEL_ERROR_2026-09.md. Causas sep 10 identificadas (CB 3 tiers + bug datetime phase_b); sep 1/2 irreconstruibles sin logs. | Purga `generation_attempts` 20/9 |
| P-007 | DONE | 2026-09-17 | Revisar `min=0` en `max_comments_per_day`, `max_feed_replies_per_day`, `max_comments_per_post`. CERRADO 23/9: floors 0->2/1/1 (commit 05dd801); P-068 registrado. | Sesión 20/9 §11.4 |

## Media prioridad

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-008 | OPEN | 2026-09-18 | Actualizar `RESILIENCIA_OPERATIVA.md` (NSSM corre, tests 1507, saldo real) | Sesión 20/9 |
| P-009 | DONE | 2026-09-20 | Corregir `claims_tracker`: doc dice 228K líneas, real = 27,557 claims | Sesión 20/9 |
| P-010 | OPEN | 2026-09-20 | Verificar fuentes externas en `PLAN_AUTOSUSTENTABILIDAD.md` | Sesión 20/9 |
| P-011 | DONE | 2026-09-20 | Etiquetar `EIN_SERVICE_SPEC.md` como "spec propuesta" | Sesión 20/9 |
| P-012 | OPEN | 2026-09-20 | Implementar `phase_a_voice_branch` (2 ramas de voz) | Sesión 20/9 §11.5 |
| P-013 | OPEN | 2026-09-20 | Reorientar watchlist: mid-tier recíproco (M3) | Sesión 20/9 §11.6 |
| P-014 | OPEN | 2026-09-20 | Consolidación de posts (post aclaratorio) | Sesión 20/9 §11.7 |
| P-015 | OPEN | 2026-09-20 | Fix `extract_moltbook_full.py`: backoff 429 + resume | Sesión 20/9 §11.8 |
| P-016 | OPEN | 2026-09-19 | H.11 — limpieza `credentials.py`: `deepseek_timeout`, `ollama_cloud_timeout` | Handoff 19 noche §13.4 |
| P-017 | OPEN | 2026-09-19 | Grep de fechas hardcodeadas en tests | Handoff 19 tarde §13.6 |
| P-018 | DONE | 2026-09-21 | Emojis mojibake residuales en `scripts/audit_dryrun_quality.py` | Handoff 19 noche §9 |
| P-019 | OPEN | 2026-09-19 | Test unitario para `phase_a_classifier_verdict` | Handoff 19 tarde §10 |
| P-020 | OPEN | 2026-09-19 | `scripts/phase_a_verdict_report.py` — agregador semanal | Handoff 19 tarde §10 |
| P-021 | OPEN | 2026-09-18 | Instrumentación horaria: `karma_roi_tracker` con `hour_of_day` | Handoff 17/18 §7 |
| P-022 | OPEN | 2026-09-17 | Verificar nombre del agente Moltbook (`comet_riobamba` vs `cometa_riobamba`) | Handoff 17/18 §7 |
| P-023 | OPEN | 2026-09-19 | Añadir sección day-aware + run_id + allowlist a `CONFIG_TRUTH.md` | Handoff 19 noche §13.11 |
| P-024 | OPEN | 2026-09-20 | Implementar M4 (fuente externa para Phase A) | Sesión 20/9 |
| P-025 | DONE | 2026-09-19 | Limpieza de backups (`.env.backup*`, `config/*.backup-*`) | Handoff 19 noche §13.12 |

## Baja prioridad

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-026 | DONE | 2026-09-19 | `data/config_audit_20260911.json` — artefacto viejo | Handoff 19 noche §13.13 |
| P-027 | DONE | 2026-09-18 | `snapshots.jsonl` — 4.96 MB, nadie escribe desde 6/9 | Handoff 18/19 §13.14 |
| P-028 | OPEN | 2026-09-18 | `guard C` en una línea — cosmético | Handoff 17/18 §6 |
| P-029 | OPEN | 2026-09-18 | `run_value_review` L116-123 dead code | Handoff 17/18 §6 |
| P-030 | DONE | 2026-09-20 | Decidir destino de `proposal_apply_log.legacy-20260920.jsonl` | Sesión 20/9 |

## Macro / estratégico

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-031 | OPEN | 2026-09-18 | Fase 1 plan autosustentabilidad: EIN como API | Handoff 18/19 §10 |
| P-032 | OPEN | 2026-09-18 | Verificar modelos disponibles con recargas | Handoff 18/19 §10 |

## Pendientes nuevos (2026-09-21)

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-033 | DECIDE | 2026-09-21 | Reconciliar 3 capas de config (policy/runtime/allowlist). Evidencia 21/9: env=15 vs allowlist=(2,10,8) vs log previous=2 | P-007b |
| P-040 | OPEN | 2026-09-21 | Rediseño motor auto-mejora: deltas + floors + sombra | Sesión 21/9 |
| P-041 | DONE | 2026-09-21 | Verificar posible Hangul-mojibake en `phase_a_content.py` | Sesión 21/9 |
| P-045 | DONE | 2026-09-21 | 2 tests fallan (TestIncidentFiguresGate::test_body_without_figures_rejected_and_incident_stays_unused + test_body_with_two_figures_published_and_marked_used). Reproducido 23/9: fallan SOLO cuando data/topic_evolution_state.json tiene una serie status=active. Mecanismo: evolution asigna topic antes que choose_topic (que respeta own_incident); editorial filter rechaza el topic de evolution y hace fallback, pero topic_source ya NO empieza con 'own_incident:'; _incident=None; gate no dispara; post sale sin error. NO son 8 tests; los 6+2 originalmente citados pasan. Fix pendiente (dos capas): (A) conftest.py debe aislar topic_evolution_state.json y topic_matrix_state.json; (B) decidir si own_incident debe ganar a evolution (ADR). CERRADO 24/9: capa A commit ccf726a (conftest.py), capa B ADR-003 Aceptado commit 7cf6c8f; suite 1507 passed. | Sesion 21/9, corregido 23/9 |
| P-046 | OPEN | 2026-09-21 | shutdown: agente completa cleanup en 1s pero proceso sigue vivo ~6min. Investigar threads no-daemon o tasks pendientes. | Sesion 21/9 |
| P-047 | DONE | 2026-09-21 | ROTAR MOLTBOOK_API_KEY: key expuesta 21/9. Rotada 22/9 20:18. DPAPI + keyring actualizados, validados. Backup en data\.secrets_backup\moltbook_api_key.20260922_200436.enc (hash DB0EF5C9). Servicio reiniciado 20:20:35, sin errores auth. Ver docs/adr/ADR-002-moltbook-key-rotation.md | Sesion 21/9, cerrado 22/9 |

---


## Pendientes nuevos (2026-09-22)

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-048 | DONE | 2026-09-22 | Unificar los 3 wrappers de lectura de key (config/credentials.py, services/top_agents_tracker.py, services/editorial_self_audit.py) para que todos usen config.credentials._get_secret(). CERRADO 22/9 noche: unificado en commit 99bda68 (top_agents_tracker.py + editorial_self_audit.py usan _get_secret; pytest 10 passed; py_compile OK; sin reinicio de servicio, modulos CLI/huerfanos) | Auditoría 22/9 |
| P-049 | DONE | 2026-09-23 | Implementar script de rotación de key con backup previo + validación + rollback automático. CERRADO 23/9: scripts/rotate_key.py (validación HTTP + backup timestamped + DPAPI/keyring + rollback automático + --dry-run; tests exit 1/2/4 OK; py_compile sin warnings). ADR-002 actualizado. | Auditoría 22/9, cerrado 23/9 |
| P-050 | OPEN | 2026-09-22 | Documentar endpoints oficiales de Moltbook en docs/DIRECTRICES.md (incluir /feed, /users/top, /users/{id}; marcar /users/me como NO válido) | Auditoría 22/9 |
| P-051 | DONE | 2026-09-22 | Crear data\.secrets_backup\ con .gitignore antes de rotar key | Auditoría 22/9 |
| P-052 | OPEN | 2026-09-22 | Añadir rotación trimestral de MOLTBOOK_API_KEY al calendario operativo | Auditoría 22/9 |
| P-053 | DONE | 2026-09-22 | Crear docs/AUDITORIA_ENTORNO.md con snapshot del entorno | Auditoría 22/9 |
| P-054 | DONE | 2026-09-22 | Crear docs/MAPA_TECNICO.md con mapa de servicios/wrappers/endpoints | Auditoría 22/9 |
| P-055 | DONE | 2026-09-22 | Crear docs/adr/ADR-002-moltbook-key-rotation.md con procedimiento de rotación | Auditoría 22/9 |
| P-056 | OPEN | 2026-09-22 | Evaluar rotación de logs\agent.log y logs\service_stdout.log (crecen >5 MB/día) | Auditoría 22/9 |
| P-057 | OPEN | 2026-09-22 | Verificar que .env no contiene ninguna otra API key en texto plano (DeepSeek, Cerebras, Telegram sí están) | Auditoría 22/9 |


## Pendientes nuevos (2026-09-22 tarde)

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-058 | DONE | 2026-09-22 | Prompt de apertura contiene HEAD exacto. Verificado 23/9 con Select-String: PROMPT_APERTURA.md en disco no hardcodea HEAD; ya usa 'git log --oneline -1'. Premisa no aplica. | Sesion 22/9 tarde, cerrado 23/9 |
| P-059 | DONE | 2026-09-22 | Verificar coherencia PENDING vs HANDOFF en cada cierre. CERRADO 25/9: Regla 34 agregada a DIRECTRICES.md. | Sesion 22/9 tarde, cerrado 25/9 |
| P-060 | DONE | 2026-09-22 | Revisar si otros wrappers de lectura de key ignoran DPAPI despues de unificar P-048. No basta con los 3 detectados: verificar imports sueltos de keyring. CERRADO 22/9 noche: grep keyring/MOLTBOOK_API_KEY en todo el repo: unicos lectores restantes _get_secret (canonico) y _rotate_key.py (escritor); extract_* pasan por Credentials.from_env; config.py valida post-from_env. No hay mas wrappers | Sesion 22/9 tarde |
| P-061 | OPEN | 2026-09-22 | Mensajes de error desactualizados: dicen 'no definido en .env' en scripts/extract_moltbook.py, scripts/extract_moltbook_full.py y config/config.py::validate_config. La key vive en DPAPI/keyring desde 21/9. Cosmetico, no rompe ejecucion | Sesion 22/9 noche (P-048) |
| P-062 | DONE | 2026-09-23 | ADR-002 actualizado: status Aceptado; Paso 3 alineado con rotate_key.py (new_key.tmp, no Read-Host -AsSecureString); Consequences sin P-048 pendiente; añadido INV7 (rollback). CERRADO 23/9. | Sesion 22/9 noche, cerrado 23/9 |
| P-063 | DONE | 2026-09-22 | Regla EOL para parches: read_text/write_text de Python colapsan CRLF y traducen LF->CRLF en Windows; con core.autocrlf=true esto renormaliza blobs con CRLF (incidente CHANGELOG commit 53345b0: numstat 152/139 por solo EOL). APLICADA 22/9 noche como regla 33 de DIRECTRICES.md: usar read_bytes/write_bytes y verificar numstat tras cada commit | Sesion 22/9 noche (fix EOL) |
| P-064 | DONE | 2026-09-23 | Pulir PROMPT_APERTURA v6: punto (a) del objetivo cita HANDOFF §10 pero el handoff nocturno trae la sugerencia en §9; ERROR A cita '200 lineas' (handoff actual = 112). CERRADO 23/9: prompt v6 corregido in-place (§10->§9 en 3 sitios, 200->112); sin regenerar v7. | Cierre sesion 23/9 |
| P-065 | OPEN | 2026-09-23 | Añadir error_type (y tier fallido) a generation_attempts.jsonl: hoy solo guarda outcome=model_error sin causa; impide diagnostico retroactivo. | P-006 |
| P-066 | OPEN | 2026-09-23 | Confirmar commit que corrigio 'TypeError: offset-naive and offset-aware datetimes' en phases/phase_b.py (candidato 28acb8a). | P-006 |
| P-067 | DONE | 2026-09-23 | PROMPT_APERTURA.md apuntaba a HANDOFF_2026-09-22_noche.md y conteos 112/153/97. CERRADO 23/9: PASO 1 ahora detecta handoff por nombre-fecha descendente ($h) y no hardcodea conteos; PASO 2 usa $h; ERROR A sin conteos; duplicado HEAD eliminado. numstat 17/10. | Sesion 23/9 cierre |
| P-068 | OPEN | 2026-09-23 | config/behavior_cfg.py (v4.3.0) codigo muerto: nadie lo importa en produccion (todos usan config/config.py::behavior_cfg). Eliminar o archivar. | Hallazgo P-007 23/9 |
| P-069 | DONE | 2026-09-23 | PROMPT_APERTURA.md PASO 1 usaba Sort-Object Name -Descending, roto para sufijos _p006 (ASCII: punto < underscore). CERRADO 23/9: ahora usa Sort-Object LastWriteTime -Descending; verificado que detecta _p006 (54 lineas). numstat 4/3. | Sesion 23/9 (post-Claude) |
| P-070 | DONE | 2026-09-23 | Añadir "No ser condescendiente" a DIRECTRICES.md §7b; agregar sub-regla 12b (reproducir antes de diagnosticar). Origen: violaciones reglas 1/2/12 en sesión P-045. CERRADO 24/9: commit 4684933; verificado Select-String. | Sesión 23/9 P-045 |
| P-071 | DONE | 2026-09-23 | Bug de produccion: cuando topic_evolution_state.json tiene serie active, evolution asigna topic antes que choose_topic y rompe la prioridad own_incident (material unico no se publica). Reproducido 23/9 inyectando 1 active: test 1 falla con 'topic Evidence for: ... rejected by editorial filter, using fallback'. State restaurado desde backups/topic_evolution_state.json.bak-20260923-210313. Servicio no afectado. Requiere ADR para decidir precedencia own_incident vs evolution. Origen: P-045. CERRADO 24/9: own_incident corre ANTES de evolution en execute() (commit feac722, ADR-003 INV1-INV4); 2 tests nuevos TestExecuteOwnIncidentPrecedence; suite 1509 passed. | Sesion 23/9 P-045 |

## Cerrados esta sesión (2026-09-21)

| ID | Descripción | Commit / artefacto |
|---|---|---|
| P-003 | Verificar run_id en produccion Phase A | Verificado 21/9 16:12, cycle-182-1790007121 |
| P-004 | Verificar ts+timestamp+run_id en proposal_apply_log | Verificado 21/9 15:08, cycle-180-1790003032 |
| P-005 | Verificar cap weekday max_posts_per_day=1 | Verificado ciclos 188-194 |
| P-018 | Fix mojibake en `audit_dryrun_quality.py` | cf6721e + 1606c00 |
| P-025 | Limpieza backups `.env.*` + `config/*.bak*` | backups/env-backups-20260921 + backups/config-backups-20260921 |
| P-026 | `config_audit_20260911.json` archivado | data/archive/ |
| P-027 | `snapshots.jsonl` archivado | monitoring/archive/ |
| P-030 | `proposal_apply_log.legacy` archivado | data/archive/ |
| P-009 | Fix `EIN_SERVICE_SPEC.md`: 228083 -> ~29,400 entries reales | (pendiente commit) |
| P-011 | Verificado: `EIN_SERVICE_SPEC.md` ya tenia header SPEC PROPUESTA | no-op |
| P-041 | Verificado: 0 Hangul en `phase_a_content.py` (artefacto de terminal) | no-op |
| P-042 | Fix doble "data" en `claims_tracker.py` + unificar callers | (pendiente commit) |
| P-043 | Recuperacion `data/data/` via VSS (claims 37B, topic_index 47B, write_log 1168B) + protocolo destructivo en DIRECTRICES.md | backups/recovered-data-data-20260921-185509/ |
| P-001 | Fix shutdown watcher: detecta stop.flag mid-ciclo | 052f561 |
| P-044 | DIRECTRICES.md creado (27+ reglas + protocolo destructivo + recuperacion VSS) | 1f88d0a |
| --- | Migracion MOLTBOOK_API_KEY a DPAPI machine-scoped | e912fca |

## Cerrados esta sesión (2026-09-20)

| ID | Descripción | Commit / artefacto |
|---|---|---|
| P-101 | Fix allowlist auto-mejora + sync prompt + write atómico | `f265756` |
| P-102 | Fix `run_id` por ciclo en `generation_attempts` | `985cd2f` |
| P-103 | Reducción frecuencia (`.env`: cap 2→1 weekday, 4→2 weekend) | `.env.backup-c-freq-20260920-1635` |
| P-104 | Fix `min=2` en `max_comment_replies_per_cycle` | `7dec8cb` |
| P-105 | Aislar JSONL de Phase A en conftest | `ae72715` |
| P-106 | Fix `ts/timestamp/run_id` en `proposal_apply_log` | `6717543` |
| P-107 | Purga 2413 entries contaminadas de `generation_attempts.jsonl` | `backups/generation_attempts.jsonl.backup-20260920-1845` |
| P-108 | Archivar 592 entries legacy de `proposal_apply_log.jsonl` | `data/proposal_apply_log.legacy-20260920.jsonl` |
| P-109 | Fix `lxml 6.1.3` (Energy Intel) | entorno |
| P-110 | H.10 — `deepseek_flash_timeout` eliminado | `8e2d941` |
| P-111 | H.10b — verificación `COMET-RIOBAMBA_REFERENCE.md` (no-op) | `8cb210c` |
| P-112 | Crear NORTH_STAR + CONTENT_STRATEGY + DOC_COHERENCE + PENDING | (esta sesión) |

---

## Rechazados (con razón)

| ID | Descripción | Razón |
|---|---|---|
| P-901 | Monetizar directamente en Moltbook | Ecosistema joven sin tracción. Ver `PRESUPUESTO_Y_MONETIZACION_2026-07-21.md` |

---

*Actualizar en cada sesión. Nunca borrar filas.*
