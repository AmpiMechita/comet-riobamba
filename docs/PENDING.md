# PENDING.md — Ledger de pendientes COMET-RIOBAMBA

> **Regla de oro:** nunca borrar filas. Marcar `DONE` o `REJECTED` con fecha + commit.
> **Al abrir sesión:** leer filas OPEN prioridad Alta.
> **Al cerrar sesión:** agregar pendientes nuevos + marcar resueltos con commit.
> **Creado:** 2026-09-20 (bootstrap desde 6 handoffs + sesión 20/9).
> **Última actualización:** 2026-09-30 p136b (Regla 46b anadida a DIRECTRICES.md: prohibido cerrar sesion sin actualizar fila canonica del ID en el MISMO commit. P-135 OPEN.)
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
| P-008 | DONE | 2026-09-18 | Actualizar `RESILIENCIA_OPERATIVA.md` (NSSM corre, tests 1538, saldo real $3.00). CERRADO 2026-10-02: documento actualizado con datos reales. | Sesión 20/9 |
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
| P-065 | DONE | 2026-09-23 | Añadir error_type (y tier fallido) a generation_attempts.jsonl. CERRADO 24/9: kwargs opcionales en _log_generation_attempt + caller model_error actualizado + test; commit f450094; suite 1510 passed. | P-006 |
| P-066 | DONE | 2026-09-23 | Confirmar commit que corrigio 'TypeError: offset-naive and offset-aware datetimes' en phases/phase_b.py (candidato 28acb8a). CERRADO 24/9 (P-076): fix real = 2e60d3f (audit 13-16/09); ruta real phases/phase_b/orchestrator.py (NO phases/phase_b.py, inexistente); hunk L2112-2113 ts_dt.replace(tzinfo=timezone.utc) + comentario FIX 2026-09-13 naive->aware. Candidato 28acb8a (scheduling day-aware) erroneo. | P-006 |
| P-067 | DONE | 2026-09-23 | PROMPT_APERTURA.md apuntaba a HANDOFF_2026-09-22_noche.md y conteos 112/153/97. CERRADO 23/9: PASO 1 ahora detecta handoff por nombre-fecha descendente ($h) y no hardcodea conteos; PASO 2 usa $h; ERROR A sin conteos; duplicado HEAD eliminado. numstat 17/10. | Sesion 23/9 cierre |
| P-068 | OPEN | 2026-09-23 | config/behavior_cfg.py (v4.3.0) codigo muerto: nadie lo importa en produccion (todos usan config/config.py::behavior_cfg). Eliminar o archivar. | Hallazgo P-007 23/9 |
| P-069 | DONE | 2026-09-23 | PROMPT_APERTURA.md PASO 1 usaba Sort-Object Name -Descending, roto para sufijos _p006 (ASCII: punto < underscore). CERRADO 23/9: ahora usa Sort-Object LastWriteTime -Descending; verificado que detecta _p006 (54 lineas). numstat 4/3. | Sesion 23/9 (post-Claude) |
| P-070 | DONE | 2026-09-23 | Añadir "No ser condescendiente" a DIRECTRICES.md §7b; agregar sub-regla 12b (reproducir antes de diagnosticar). Origen: violaciones reglas 1/2/12 en sesión P-045. CERRADO 24/9: commit 4684933; verificado Select-String. | Sesión 23/9 P-045 |
| P-071 | DONE | 2026-09-23 | Bug de produccion: cuando topic_evolution_state.json tiene serie active, evolution asigna topic antes que choose_topic y rompe la prioridad own_incident (material unico no se publica). Reproducido 23/9 inyectando 1 active: test 1 falla con 'topic Evidence for: ... rejected by editorial filter, using fallback'. State restaurado desde backups/topic_evolution_state.json.bak-20260923-210313. Servicio no afectado. Requiere ADR para decidir precedencia own_incident vs evolution. Origen: P-045. CERRADO 24/9: own_incident corre ANTES de evolution en execute() (commit feac722, ADR-003 INV1-INV4); 2 tests nuevos TestExecuteOwnIncidentPrecedence; suite 1509 passed. | Sesion 23/9 P-045 |

## Pendientes nuevos (2026-09-24)

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-072 | OPEN | 2026-09-24 | Prevenir inflación EOL en diffs de docs (patrón recurrente). Evidencia: CHANGELOG en commit c08ec1e (cierre P-075) numstat 330++/163-- solo por EOL, idéntico a incidente P-063 (53345b0). Contenido correcto; Regla 33 aplicada en Python (read_bytes/write_bytes); git renormaliza al commitear con core.autocrlf=true. Evaluar '* text=auto eol=lf' o regla para *.md en .gitattributes. No bloqueante. | Sesión P-076 (hallazgo P-075) |
| P-073 | OPEN | 2026-09-24 | Reportes diarios monitoring/daily-*.md detenidos desde 2026-09-05 (agente sigue corriendo). Restaurar generacion o decidir retiro formal. | Sesion P-077 (analisis produccion) |
| P-074 | DONE | 2026-09-24 | Lazo feedback engagement muerto. Causa raiz (p078): BUG1 import muerto run_agent.py:26; BUG2 llamada fantasma karma_updater.py:43 get_post_info inexistente; BUG3 id erroneo karma_updater.py:80; BUG4 (nuevo p079) fuente SQLite con 0/200 filas con score>0. FIX p079 commit 277ba5b: Camino B, delegar a karma_roi_tracker.update_karma. | Sesion P-077 + p078 + p079 |
| P-075 | OPEN | 2026-09-24 | Dominancia fallback en topic_source: dedup_fallback 1025 + forced_fallback 1003 = 69.6% historico (n=2914). Revisar pipeline de topics y decidir si es sano o deuda. | Sesion P-077 |
| P-076 | OPEN | 2026-09-24 | run_id historico ausente en generation_attempts: presente en 4/2914, solo desde 2026-09-21. Fix P-102 (985cd2f, 20/9) empieza a poblar tarde; decidir backfill o aceptar. | Sesion P-077 |
| P-077 | OPEN | 2026-09-24 | value_log clasifica 108/108 como aporte_util en 14d. Posible sesgo del clasificador; muestrear y validar. | Sesion P-077 |
| P-079 | DONE | 2026-09-24 | Fix P-074 (commit 277ba5b). Camino B: (a) via fetch_post_comments(thread_id)+match por id (no existe get_comment). (b) update_karma_from_moltbook despacha por type. (c) update_all_karma_guarded 6h cableado en core/agent.py. (d) 15 tests dirigidos + suite 1510 passed. | Sesion P-078 + p079 |
| P-080 | DONE | 2026-09-24 | PROMPT_APERTURA.md L46: byte BEL (0x07) entre `\logs` y `gent.log` (premisa "\n literal" incorrecta, era BEL). Corregido a `.\logs\agent.log`. Sin inflacion EOL. | Sesion P-079, cerrado p081 |
| P-081 | DONE | 2026-09-24 | Divergencia schema JSONL vs SQLite. Inventario p081: 0 consumidores en produccion (solo karma_dashboard.py CLI + load_tracker_entries interno); engagement_events/daily_snapshots vacias; comments_received sin consumidor. Decision ADR-004: JSONL OBSOLETO, SQLite unica fuente. Retiro ejecutable en P-083. | Sesion P-079, cerrado p081 (ADR-004) |
| P-082 | DONE | 2026-09-24 | Backfill historico SQLite. CERRADO PARCIAL 25/9 p088: 85/120 recuperables (C2 64/64 + C1 21/34 + 2 muestra). SQLite score NULL 192->107, last_updated NOT NULL 19->104. Irrecuperables con API: 61 feed_reply (P-088) + 13 thread_followup (comment borrado) + 22 A (bug post_id==comment_id, ver P-091) + 11 rejected. [Reconciliado p133: DONE definitivo (ver fila 27/9 en audit).] | Sesion P-079, cerrado p088 |
| P-083 | DONE | 2026-09-24 | Ejecutar retiro JSONL (ADR-004). CERRADO 25/9 p083b commit 5658073: (1) krt sin _jsonl_write_entry/JSONL_PATH/KARMA_TRACKER_FILE + load_recent_entries(hours) lee SQLite (parent_comment_id discrimina post/comment); (2) monitoring/karma_dashboard.py eliminado (huerfano); (3) karma_updater.load_tracker_entries delega en load_recent_entries; (4) data/karma_roi_tracker.jsonl (108843B) -> data/archive/karma_roi_tracker.jsonl.20260925_154911 (gitignored); (5) conftest sin monkeypatches huerfanos + test_karma_roi_tracker.py reescrito. Suite 1509 passed, 1 skipped. | Sesion p081, cerrado p083b |
| P-084 | DONE | 2026-09-24 | Reiniciar servicio NSSM para activar fix 94ecbc2 (colision skipped->skipped_window). Diagnostico p081: proceso PID 6452 arranco 19:40:59, commit 94ecbc2 fue 19:52:15 -> proceso stale. 0 lineas "karma_updater:" en agent.log ni rotados. Post-restart: observar 1 ciclo, confirmar linea en log y score>0 en SQLite. CERRADO 25/9 (verif p083): 2 lineas karma_updater en agent.log (08:19:03 updated=9 failed=2; 14:24:39 updated=10 failed=1, skipped_window 212/223) + state file 14:24:39 + SQLite rows 200->211 score>0 1->4 lu_nn 9->19. ERRATA p081: PID stale real 7132, NO 6452. | Sesion p081, cerrado p083 |

## Pendientes nuevos (2026-09-25)

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-085 | DONE | 2026-09-25 | Corregir plantilla de apertura: premisa sin Internet incorrecta. CERRADO 25/9 p083b: PROMPT_APERTURA.md linea 'ni Internet (sin herramientas)' eliminada; anadida aclaracion '(Si tienes acceso a Internet para buscar herramientas y mejoras.)'. | Handoff p082 s6, cerrado p083b |
| P-086 | DONE | 2026-09-25 | Anadir regla a DIRECTRICES.md: borrar artefactos de sesion (scripts/patch_*.py) ANTES de git add -A, no despues del commit. Origen: p083b amend a5ea345->5658073. CERRADO 26/9 p086: regla 35 en DIRECTRICES.md seccion "Artefactos de sesion". | Handoff p083b |

## Pendientes nuevos (2026-09-25 p082)

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-087 | DONE | 2026-09-25 | Bug `services/karma_roi_tracker.py::load_recent_entries` L648: para `type=comment` asignaba `thread_id = parent_comment_id` (thread real = `post_id`). CERRADO 25/9 p087: SELECT trae `post_id`; `thread_id = post_id_val if is_comment else None` (commit 9275a64). Test C2 (parent != post) + post top-level; suite 1510 passed. Verificado en prod ciclo #374 (17:08:14): updated=4 failed=7; los 3 thread_followup con parent no-nulo actualizados (antes fallaban); los 7 fallos son feed_reply = P-088. | Sesion p082, cerrado p087 |
| P-088 | DONE | 2026-09-25 | 61 filas historicas `source=feed_reply` (parent_comment_id NULL, comment_id != post_id) NO recuperables con API actual: `get_post(comment_id)` -> 404; `fetch_post_comments(post_id)` no las incluye (probe B: 197 comments, hit=False). Aceptar perdida historica o explorar otro endpoint. [Reconciliado p133: falso negativo, DONE definitivo (ver fila 27/9 en audit).] | Sesion p082 |

| P-089 | OPEN | 2026-09-25 | Verificar que `docs/HANDOFF_<fecha>_<id>.md` no exista antes de escribir HANDOFF nuevo. Sesion p082b: `HANDOFF_2026-09-25_p082.md` ya existia (sesion nocturna 03:35-04:25 P-084, commit 7035ac9) y fue sobrescrito en 997f337; restaurado desde 7035ac9 en 4df134f renombrando el propio a p082b. Regla candidata para DIRECTRICES.md. | Sesion p082b |
| P-090 | DONE | 2026-09-25 | `load_recent_entries` discrimina `type` por `parent_comment_id IS NULL`: `feed_reply` top-level (parent NULL) se clasifica como `post` y llama `get_post(comment_id)` -> 404. Semanticamente deberia discriminar por `source` (own_post_reply/thread_followup/feed_reply -> comment). No bloqueante hoy (P-088 dice que no se recuperan igual), pero ensucia logs y podria morder si la API cambia. CERRADO 25/9 p094: load_recent_entries usa action_type; 72/72 feed_reply top-level ahora type=comment con thread_id=post_id. Commit 7d28f95. | Sesion p087 |

## Pendientes nuevos (2026-09-25 p088)

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-091 | DONE | 2026-09-25 | Bug writer: 24 filas own_post_reply published parent NULL con post_id == comment_id. get_post(comment_id) devuelve el comment tratado como post; fetch_post_comments(post_id) -> 404. Preexistente, no regresion. Afecta 22 A + 2 con score>0. Hipotesis fix: corregir punto de escritura (record_phase_b_comment o track_action) para guardar post_id real. | Sesion p088 |

## Cerrados esta sesión (2026-09-25 p092)

| ID | Descripción | Commit / artefacto |
|---|---|---|
| P-092 | Fix P-091: action_type en comment_actions + filtros en get_roi_summary y roi_dashboard. Backfill 24 post + 11 post_rejected. Tests 8/8 tracker + 19 adyacentes. Verificado A=35/B=176. | 03ec072 |
| P-091 | Bug writer post_id==comment_id (causa raiz track_action) | resuelto por P-092 (03ec072) |

## Cerrados esta sesión (2026-09-25 p088)

| ID | Descripción | Commit / artefacto |
|---|---|---|
| P-082 | Backfill historico SQLite (parcial 85/120) | scripts/_p088_backfill.py (borrado); ver HANDOFF_2026-09-25_p088.md |

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

## Cerrados esta sesión (2026-09-25 p094)

| ID | Descripción | Commit / artefacto |
|---|---|---|
| P-090 | load_recent_entries discrimina type por action_type (no por parent_comment_id IS NULL); 72/72 feed_reply top-level correctos | 7d28f95 |

## Cerrados esta sesión (2026-09-25 p095)

| ID | Descripción | Commit / artefacto |
|---|---|---|
| P-094 | Incidente regleta/bateria (4 boots, 1 Kernel-Power 41 sucio); causa: regleta apagada -> bateria agotada; analisis cerrado sin commit de codigo | n/a |
| P-095 | battery_monitor LOW=25 RESUME=45 + logging INFO/WARNING; activo PID 7564 | 337b06d |

## Pendientes nuevos (2026-09-25 p095)

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-093 | DONE | 2026-09-25 | Schema versioning SQLite (5 DBs agente). CERRADO 26/9 p100: helper core/sqlite_migrations.py::apply_migrations + SCHEMA_VERSION/MIGRATIONS en memory_store, persistence, topic_memory, dedup_store, karma_roi_tracker. ADR-005. Tests tests/test_sqlite_migrations.py (6) + 59 focalizados + suite 1520 passed 1 skipped. Huesped data/karma_roi_tracker.db borrado. | Sesion p093, cerrado p100 |



## Pendientes nuevos (2026-09-26 p101)

| ID | Estado | Creado | Descripcion | Origen |
|---|---|---|---|---|
| P-100b | DONE | 2026-09-26 | Decidir dueno del schema de energy_intel.db + versionar (ADR-005 bis). Premisa de P-100 era incorrecta: ademas del escritor primario docs/ein/energy_intel_node.py, runtime escribe via services/energy_knowledge_base.py::update_claim_status; y phase_b/orchestrator.py lo consume. Opciones: (a) versionar solo en energy_intel_node.py (dueno schema) + validar uv>=1 en runtime; (b) dejar fuera de ADR-005 y documentar; (c) mover schema a runtime y degradar node a escritor puro. Requiere ADR. | Sesion p101 |
| P-101 | OPEN | 2026-09-26 | Fijar cwd del repurposer o aceptar duplicado de DBs. services/content_distributor.py:155 invoca `python -m comet_repurposer ... cwd=scripts/comet_repurposer`; config resuelve project_root=os.getcwd() -> DBs activos viven en scripts/comet_repurposer/data/*.db, no en data/*.db (raiz). Ya existe duplicado publish_queue.db en ambos (24576 B cada). Decision: pasar --project-root o cwd=raiz, o documentar subdirectorio como canonico y borrar duplicado de raiz. | Sesion p101 (hallazgo P-100a) |
## Pendientes nuevos (2026-09-26)

| ID | Estado | Creado | Descripcion | Origen |
|---|---|---|---|---|
| P-096 | OPEN | 2026-09-26 | Regla 34 ubicada fuera de secuencia: esta en L49, entre reglas 26 y 27, en vez de tras la 33. Cosmetico. | Sesion p086 |
| P-097 | OPEN | 2026-09-26 | HANDOFF p095 seccion 1 dice P-095 OPEN pero ledger ya lo marca DONE (commit 002a32b). | Sesion p086 |
| P-098 | DONE | 2026-09-26 | PID 7564=Python hijo (StartTime 25/9 22:37:55, CPU ~1808s); PID 12080=wrapper NSSM (Win32_Service.ProcessId). Sin reboot ni restart: ciclos 381-401 ininterrumpidos. Artefacto de medicion: p095 reporto PID hijo, p086 reporto PID wrapper. CERRADO 26/9 p087. | Sesion p086 |
| P-100 | DONE PARCIAL | 2026-09-26 | Extender schema versioning SQLite (ADR-005) a scripts/comet_repurposer/ (publish_queue.db, repurpose_dedup.db, semantic_dedup.db) y decidir energy_intel.db. HECHO p101: helper local comet_repurposer/migrations.py (~30 lineas, contrato identico a core) + SCHEMA_VERSION=1/MIGRATIONS=[] en dedup.py, semantic_dedup.py, publishers/base.py + tests/test_migrations_repurposer.py (7 passed; suite repurposer 11 passed). Addendum ADR-005. Decidir energy_intel.db DIFERIDO a P-100b (premisa 'no runtime' incorrecta). Commit a09a95e. | Sesion p100, parcial p101 |

> **Correccion P-091 (p092):** la hipotesis del HANDOFF p088 (bug en _post_own_reply L4611 o record_phase_b_comment L1423) fue DESCARTADA por lectura de codigo + logs. Causa raiz real: Phase A, phase_a_content.py:2193 llama track_action(action_type='post') y L2116 track_action(action_type='post_rejected'); track_action carece de discriminacion por tipo y escribe a comment_actions con source='own_post_reply' por default. Alcance: 24 publicados + 11 rejected = 35 filas espurias. P-091 DONE via P-092 (commit 03ec072).

---

## Cerrados esta sesión (2026-09-26 p099)

| ID | Descripción | Commit / artefacto |
|---|---|---|
| P-099 | battery_monitor: guardia _paused evita add_reason/remove_reason repetidos cada poll | d93cbbf |

*Actualizar en cada sesión. Nunca borrar filas.*

## Cerrados esta sesion (2026-09-29 p131)

| ID | Descripcion | Commit / artefacto |
|---|---|---|
| P-088 | Cierre formal como DONE. Re-medicion p129 (96/99 recuperables; A=22/22 B=63/63 C=11/14); 3 MISS son borrados reales (n estable 293/487/487). Los 63 feed_reply originalmente irrecuperables SI estan via next_cursor. Header PENDING p129->p131 + fila P-088 REOPENED->DONE. numstat 2/2. | c351d06 + HANDOFF_2026-09-29_p131.md |



## Pendientes nuevos (2026-09-26 p102)

| ID | Estado | Creado | Descripcion | Origen |
|---|---|---|---|---|
| P-113 | DONE | 2026-09-26 | Endurecer enum claimed|disputed|debunked en EnergyKnowledgeBase.update_claim_status (hoy no valida; el PATCH del node si). Sin caller en prod, pero API publica. CERRADO 26/9 p113: constante _VALID_STATUSES (L5) + guarda L58-60; test nuevo. Suite 1526 passed 1 skipped. | Sesion p102 (P-100b), cerrado p113 |
| P-114 | DONE | 2026-09-26 | Validar uv>=1 en runtime (EnergyKnowledgeBase.__init__): lee PRAGMA user_version; si <1, available=False y los metodos devuelven []/False. CERRADO 26/9 p114: gate en __init__ tras SELECT 1 FROM claims; test nuevo test_unavailable_when_schema_version_too_low; helper _create_test_db setea uv=1. Reproduccion real (copia uv=0): available=False. Suite 1525/1skip. | Sesion p102, cerrado p114 |
| P-115 | REJECTED | 2026-09-26 | Bug latente en docs/ein/energy_intel_node.py::main: DB_PATH = args.db (L710) reasigna sin `global`; db_conn() lee la global -> --db sin efecto. Sin impacto en prod (no se usa --db). | Sesion p102 (P-100b) |

## Cerrados esta sesion (2026-09-26 p102)

| ID | Descripcion | Commit / artefacto |
|---|---|---|
| P-100b | energy_intel.db: dueno del schema = docs/ein/energy_intel_node.py (unico). Helper apply_migrations inline (contrato core/sqlite_migrations.py, INV1c). SCHEMA_VERSION=1/MIGRATIONS=[] + llamada en init_db() (cubre L557/L711). KB: default db_path absoluto (elimina foot-gun cwd). Corregida premisa P-100a: update_claim_status NO tiene caller prod (solo 3 tests). 32/32 focalizados. | 38c157c (codigo) + ADR-005 addendum bis (docs) |

## Pendientes nuevos (2026-09-26 p103)

| ID | Estado | Creado | Descripcion | Origen |
|---|---|---|---|---|
| P-116 | DONE | 2026-09-26 | Pipeline LinkedIn/Twitter roto: content_distributor.py:157 invoca `comet_repurposer generate --source distribution_queue`, valor que NO existe en cli._select_items (valid: all, latest, social_content, published_posts, ebook, research_agenda). Argparse falla con returncode=2 antes de tocar DBs. Evidencia: service_stdout-20260923T223731.476.log:32576 (22/9 23:11:41). Efecto: 0 drafts enqueued desde el agente. Fix propuesto (Opcion A): anadir `distribution_queue` como source en repurposer (lee data/distribution_queue.json) + tests. Alternativa B: bypass escribiendo directo a publish_queue.db via QueueStore. | Sesion p103 (hallazgo P-101) |

## Cerrados esta sesion (2026-09-26 p103)

| ID | Descripcion | Commit / artefacto |
|---|---|---|
| P-101 | Fix BUG-2 (cwd del repurposer): pasar `--project-root <raiz>` explicito desde content_distributor.py, calculado con `Path(__file__).resolve().parents[1]` (no cwd). BUG-1 (source invalido) derivado a P-116 (Alta). | def7d6e |

## Cerrados esta sesion (2026-09-26 p116)

| ID | Descripción | Commit / artefacto |
|---|---|---|
| P-116 | Pipeline LinkedIn/Twitter end-to-end: (a) `choices` de --source ahora incluye `distribution_queue`; (b) nuevo reader `iter_distribution_queue()` lee `data/distribution_queue.json`; (c) `content_distributor.py` pasa `--platforms linkedin,x` (no `twitter`); (d) pasa `--enqueue-linkedin --enqueue-x` (antes queue=None, 0 jobs encolados); (e) parsea `Enqueued N` real de stderr en vez de `len(posts)` optimista. Tests: 5 nuevos. | e17645b |

## Pendientes nuevos (2026-09-26 p116)

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-117 | OPEN | 2026-09-26 | `services/content_distributor.py::run_distribution` usa `repurposer_path = Path("scripts/comet_repurposer")` relativo a cwd. Funciona hoy porque el agente corre con cwd=raiz (NSSM AppDirectory), pero rompe si se invoca desde otro dir. Cambiar a `Path(__file__).resolve().parents[1] / "scripts" / "comet_repurposer"`. Registrado como deuda en HANDOFF_2026-09-26_p103.md §4. | Sesión p116 |
| P-118 | DONE | 2026-09-26 | `content_distributor.py::_save_state` se llama SIEMPRE al final de `run_distribution()`, incluso si `errors` no esta vacio o `enqueued==0`. Resultado: el throttle de 20h se activa aunque el pipeline haya fallado o no haya encolado nada. Considerar no actualizar state si `errors` o `enqueued==0`. | Sesión p116 |



## Cerrados esta sesion (2026-09-26 p117)

| ID | Descripcion | Commit / artefacto |
|---|---|---|
| P-117 | Fix repurposer_path relativo a cwd en services/content_distributor.py L152 -> Path(__file__).resolve().parents[1] / "scripts" / "comet_repurposer". numstat 1/1; verificado desde cwd alterno; suite 1520 passed 1 skipped. | (commit codigo siguiente) |

## Pendientes nuevos (2026-09-26 p117)

| ID | Estado | Creado | Descripcion | Origen |
|---|---|---|---|---|
| P-119 | DONE | 2026-09-26 | Mismo anti-patron que P-117 en services/content_distributor.py L20-21: STATE_FILE y PUBLISHED_POSTS_FILE son Path relativos a cwd. No bloqueante hoy (agente cwd=raiz), pero rompe si se invoca desde otro dir. Fijar a Path(__file__).resolve().parents[1] / "data" / "...". | Sesion p117 |

## Cerrados esta sesion (2026-09-26 p118)

| ID | Descripcion | Commit / artefacto |
|---|---|---|
| P-118 | `_save_state()` condicional: solo se llama si `errors==[]` y `enqueued>0`. Rama 'no posts qualify' ya no escribe state. 4 tests nuevos en tests/test_content_distributor.py. Suite 1524 passed, 1 skipped. | 8afca4d |

## Cerrados esta sesion (2026-09-26 p119)

| ID | Descripcion | Commit / artefacto |
|---|---|---|
| P-119 | `services/content_distributor.py` L20-21: `STATE_FILE` y `PUBLISHED_POSTS_FILE` ahora absolutos desde `Path(__file__).resolve().parents[1] / "data" / "..."`. Reproducción desde cwd=C:\Windows: paths apuntan a `C:\comet-riobamba-v31\data\...`, `is_absolute()=True`. Suite 1524 passed, 1 skipped. | fc49403 |

## Pendientes nuevos (2026-09-26 p119)

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-120 | DONE | 2026-09-26 | Deuda estructural: anti-patron cwd-relativo en 7 archivos. Fix en bloque: paths absolutos via Path(__file__).resolve().parents[N]. model_cascade.py: os.path.join -> Path + import pathlib. Verificado desde cwd alterno. | Sesion p120 |

## Cerrados esta sesion (2026-09-26 p114)

| ID | Descripcion | Commit / artefacto |
|---|---|---|
| P-114 | EnergyKnowledgeBase.__init__ exige PRAGMA user_version>=1; available=False si <1. Test nuevo + helper uv=1. Suite 1525 passed 1 skipped. | 48f16ce |


## Cerrados esta sesion (2026-09-26 p115)

| ID | Descripcion | Commit / artefacto |
|---|---|---|
| P-115 | REJECTED: premisa falsa (no-op). Ver HANDOFF_2026-09-26_p115.md. Sin cambios de codigo. | (commit docs p115) |

## Pendientes nuevos (2026-09-26 p115)

| ID | Estado | Creado | Descripcion | Origen |
|---|---|---|---|---|
| P-121 | REJECTED | 2026-09-26 | Deuda fantasma. P-115 ya verifico que --db funciona correctamente (no hay shadowing). Flag no usado en produccion. Aplicacion de leccion P-115: no testear bugs refutados. Cerrado 2026-09-30 p121. | Sesion p115 |


## Cerrados esta sesion (2026-09-26 p113)

| ID | Descripcion | Commit / artefacto |
|---|---|---|
| P-113 | Validar enum en EnergyKnowledgeBase.update_claim_status: constante modulo _VALID_STATUSES (L5) + guarda L58-60; test test_update_claim_status_rejects_invalid_status (5 valores invalidos + estado DB intacto + valor valido OK). Suite 1526 passed 1 skipped. | bd31e01 |


## Auditoria sistematica (2026-09-27)

Resultado: 21/22 pendientes p079-p119 con evidencia (185 tests ejecutados,
numstat real vs declarado, paths verificados). Detalle en
docs/HANDOFF_2026-09-27_audit.md.

### Reaperturas por falso negativo

| ID | Estado | Creado | Descripcion | Origen |
|---|---|---|---|---|
| P-082 | DONE | 2026-09-27 | CERRADO 28/9 p129: re-medicion con cursor-loop (P-122/P-125) dio 96/99 recuperables (A=22/22, B=63/63, C=11/14). Los 3 restantes (6db7cb37, 9f3130a4, 39f094c4) son borrados reales en Moltbook (n estable 293/487 con max_pages=5 y =20). Backfill ejecutado sobre 96 filas (upd=96 skip=3), SQLite NULL published 99->3, suma score published=202. Snapshot previo data/karma_roi.db.snapshot-p082-20260928-135319.db. Detalle docs/P082_REMEDICION.md. | Auditoria 2026-09-27 (H4) |
| P-088 | DONE | 2026-09-27 | Falso negativo: los 3 "irrecuperables" probados (75ec581d, c61641b1, cdbb220d) SI estan en la API; aparecen en paginas 2-8 via next_cursor. Evidencia: probe cursor-loop, 527 top-level en 11 paginas para post 19b6e9bf-6ff9-4ea5-834a-cbbac714f546. La API SI pagina; offset NO funciona. CERRADO 2026-09-29 p131: re-medicion p129 dio 96/99 recuperables (A=22/22, B=63/63, C=11/14); los 3 MISS son borrados reales (n estable 293/487/487 con max_pages=20); los 63 feed_reply SI estan via next_cursor. Evidencia: docs/P082_REMEDICION.md + HANDOFF_2026-09-28_p129.md. | Auditoria 2026-09-27 (H3), cerrado p131 |

### Errata documental

| ID | Descripcion |
|---|---|
| P-115 | ERRATA: el veredicto REJECTED (no-op) es CORRECTO, pero la descripcion de la fila P-115 era incorrecta. El codigo en docs/ein/energy_intel_node.py:714 tiene `if __name__ == "__main__":` a nivel modulo; L723 `DB_PATH = args.db` tambien a nivel modulo -> sin shadowing, --db SI funciona. Confirmado por lectura de L700-736 (auditoria 2026-09-27 H5). No hubo bug. |

### Pendientes nuevos (2026-09-27 audit)

| ID | Estado | Creado | Descripcion | Origen |
|---|---|---|---|---|
| P-122 | DONE | 2026-09-27 | ALTA. Bug activo: `services/moltbook_api_client.py::fetch_post_comments` (L624) ignora `has_more`/`next_cursor` y solo devuelve pagina 1 (con replies anidados aplanados). La API SI pagina por cursor; `offset` es ignorado. Impacto: (a) `karma_updater.update_karma_from_moltbook` (L59) devuelve success:False silencioso para comentarios en pagina 2+ (afecta P-074/P-079); (b) `comment_votes.refresh_all_comment_votes` loop roto en pagina 2 (el propio codigo admite "la API ignora el offset" pero no busca cursor); (c) matcher follow-ups orchestrator.py:2165/3910/4192 -> replies_matched=0 en prod; (d) telegram_client.py:550 y phase_c_analytics.py:93 (probables). Fix: cursor-loop opt-in en fetch_post_comments (por defecto 1 pagina para no romper 13 callers; nuevo parametro `paginate=True`/`max_pages=N`); mapear callers que se beneficien. | Auditoria 2026-09-27 (H1/H2). CERRADO 2026-09-28 p122: cursor-loop opt-in implementado (paginate=False default, max_pages=5); karma_updater L59 + comment_votes migrados; contrato docs/P122_CURSOR_CONTRACT.md + probe scripts/recon_p122_comments_cursor.py; commits 3d5c6d5 + 79049ea; suite 1532 passed 1 skipped. Callers restantes pendientes -> P-125. |
| P-123 | DONE | 2026-09-27 | Baja. MAPA_TECNICO.md (2026-09-22) no lista ADR-004 (jsonl-obsolete-sqlite-canonical, 24/9) ni ADR-005 (sqlite-schema-versioning, 26/9). Ya anotado en HANDOFF_2026-09-25_p083 seccion 17; sigue sin atacarse. Actualizar tabla de ADRs. CERRADO 2026-09-30 p135: header fecha + seccion 7 con ADR-004 (24/9) + ADR-005 (26/9) + footer actualizados; EOL CRLF preservado (102/0/0); 3712->3921 B. | Auditoria 2026-09-27 (H6) |
| P-124 | DONE | 2026-09-28 | Corregido en esta sesion: HANDOFF_2026-09-27_audit.md L53 y PENDING.md L372 citaban 19b6e9bf como post_id; es prefijo (8 chars). La API exige UUID completo. Corregido a 19b6e9bf-6ff9-4ea5-834a-cbbac714f546. | Sesion P-122 |
| P-125 | DONE | 2026-09-28 | Media. CERRADO 2026-09-30 p136 (Regla 46: fila stale; cierre real en p125 commit 8003832). Migrado 1/5: orchestrator.py:3914 -> paginate=True,max_pages=3 si comment_count>50. 4 NO con evidencia en docs/P125_CALLERS_DECISION.md: 2165 MISSING_OURS=0; 4200 dead code -> P-127; phase_c:93 pag1 cubre; telegram_client:550 manual. Premisa "replies_matched=0 en prod" REFUTADA por probe real. | Sesion p122 + p125 |
| P-126 | OPEN | 2026-09-28 | Baja. P-098 reporto PID hijo 7564 con StartTime 25/9 22:37:55. Verificado 27/9 pre-restart: PID hijo real = 7620, StartTime 26/9 18:32:32. Hubo restart intermedio no documentado. Actualizar narrativa de P-098 o cerrarlo como impreciso. | Sesion p122 |

## Pendientes nuevos (2026-09-28 p125)

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-127 | OPEN | 2026-09-28 | Baja. `phases/phase_b/orchestrator.py::_process_own_post` (L4170) sin caller productivo (solo tests); docstring L42 sugiere que si esta cableado via _execute_own_post_replies pero no lo esta. Eliminar o documentar como dead code. | Sesion p125 |
| P-128 | DONE | 2026-09-28 | Media. CERRADO 30/9 p132: ruta canonica services/karma_roi_tracker.py:23 (DB_PATH=BASE_DIR/'data'/'karma_roi.db'). Huerfanos data/karma_roi_tracker.db (0B) + data/karma_roi_tracker.json (4B '[]') borrados; 0 refs codigo; gitignored; git status limpio. | Sesion p125, cerrado p132 |

## Cerrados esta sesion (2026-09-28 p130)

| ID | Descripcion | Commit / artefacto |
|---|---|---|
| P-129 | Karma updater: paginacion de comentarios via KARMA_FETCH_MAX_PAGES (default 50). Antes max_pages=5 (default cliente) dejaba sin refrescar comments del agente en posts >250 comentarios. Tests: 2 dirigidos + suite 1533 passed 1 skipped. | (commit p130) |

## Pendientes nuevos (2026-09-30 p132)

| ID | Estado | Creado | Descripcion | Origen |
|---|---|---|---|---|
| P-130 | DONE | 2026-09-30 | Media. CERRADO 30/9 p133: reconciliacion ledger. Filas stale corregidas in-place (P-082 DONE PARCIAL->DONE, P-088 OPEN->DONE); P-128 ya estaba DONE (descripcion original sobrevaloraba). Regla nueva anadida a DIRECTRICES.md (fuente unica de estado). Duplicados restantes son narrativa por diseno (no contradiccion). | Sesion p132, cerrado p133 |

## Cerrados esta sesion (2026-09-30 p132)

| ID | Descripcion | Commit / artefacto |
|---|---|---|
| P-128 | DB huerfana verificada y limpiada. Ruta canonica services/karma_roi_tracker.py:23. Borrados data/karma_roi_tracker.db (0B) + data/karma_roi_tracker.json (4B). 0 refs codigo, gitignored, git status limpio. | (commit p132) |


## Pendientes nuevos (2026-09-30 p134)

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-131 | DONE | 2026-09-30 | Alta. Deadlock balance_guard: agente pausado por `balance` no salía porque `check_and_trigger()` (post-ciclo, L1233) nunca corría (el `continue` del pause-check L1218 lo saltaba). Fix en 2 capas: (1) `check_and_trigger()` antes del pause-check en `core/agent.py`; (2) `register_rechecker`/`run_recheckers`/`start_pause_rechecker_thread` en `services/pause_controller.py` + thread daemon 60s + `_balance_ok` registrado en `services/balance_guard.py`. 5 tests nuevos (`tests/test_pause_rechecker.py`), suite 1538 passed 1 skipped. Verificado en prod: force-test con reason=balance limpiada en <60s sin intervención. Regla 47 añadida a DIRECTRICES.md. | p134 |
| P-132 | OPEN | 2026-09-30 | Baja. Anti-patrón EOL: replace CRLF->eol + LF->eol encadenado es incorrecto (la 1ra sustitución crea secuencias que la 2da vuelve a tocar, generando CR CR LF en archivos CRLF). Patrón correcto: normalizar primero (CRLF->LF, CR->LF), después LF->eol. Afectó a `tests/conftest.py` y `docs/DIRECTRICES.md` en p134; ambos corregidos in-situ. Candidato a Regla 48. | p134 |


| P-133 | OPEN | 2026-09-30 | Baja. Regla de metodo: scripts de parcheo a archivo `.py` (no `python -c` inline) cuando haya UTF-8, EOL o >5 lineas. Motivo: 3 bugs de la misma familia en p134 (conftest.py y DIRECTRICES.md con `\r\r\n` por `replace` encadenado; PENDING.py con SyntaxWarning y AssertionError por `\u` en byte strings; verify con comillas mal cerradas). Candidato a Regla 48. | p134 |

## Cerrados esta sesión (2026-09-30 p134)

| ID | Descripción | Commit / artefacto |
|---|---|---|
| P-131 | Deadlock balance_guard (fix 2 capas + 5 tests + Regla 47) | (commit p134) |


## Pendientes nuevos (2026-09-30 p136b)

| ID | Estado | Creado | Descripción | Origen |
|---|---|---|---|---|
| P-135 | DONE | 2026-09-30 | Baja. Reforzar Regla 46 con sub-regla 46b (DIRECTRICES.md): prohibido cerrar sesion sin actualizar la fila canonica del ID en PENDING.md en el MISMO commit; la narrativa "Cerrados esta sesion" NO cuenta como estado; verificacion pre-commit = exactamente 1 fila '| P-XXX |' con estado final. Origen: 3 casos (P-082/P-088 en p133; P-125 en p136) donde la narrativa decia DONE pero la fila canonica seguia OPEN. Aplicado en p136b. CERRADO 2026-10-02: fila actualizada in-place. | p136 |


## Cerrados esta sesion (2026-09-30 p120)

| ID | Descripcion | Commit / artefacto |
|---|---|---|
| P-120 | Fix anti-patron cwd-relativo en 7 archivos (13 paths absolutos + 1 import pathlib) | f0723de |

## Pendientes nuevos (2026-10-01 auditoria QA por capas)

| ID | Estado | Creado | Descripcion | Origen |
|---|---|---|---|---|
| P-136 | OPEN | 2026-10-01 | Alta. Contaminacion confirmada test->telemetria: test_prompt_injection_abstain usa _INJECTION_ATTEMPTS_PATH real; 101/153 filas de data/injection_attempts.jsonl son hostile_agent/post-1 sinteticas. Aislar path en tmp, preservar backup y separar/depurar historico sintetico con evidencia. | Auditoria QA 2026-10-01 |
| P-137 | OPEN | 2026-10-01 | Alta. Auditar toda la suite para detectar escrituras de tests sobre data/, logs/ o estado productivo real. Inventariar paths mutables, exigir tmp_path/monkeypatch y prueba de no-contaminacion. Hallazgo P-136 demuestra que el aislamiento actual no es completo. | Auditoria QA 2026-10-01 |
| P-138 | OPEN | 2026-10-01 | Media. Crear programa canonico QA_COMPORTAMIENTO.md que integre evals/run_evals.py, shadow_quality_checks, fabrication corpus, prompt-injection/ABSTAIN, claim_checker y self_eval. Definir dimensiones, fuentes, criterios PASS/FAIL y evidencia requerida; actualizar DOC_COHERENCE. | Auditoria QA 2026-10-01 |
| P-139 | OPEN | 2026-10-01 | Media. Sustituir el unico umbral global 85% de Phase B por benchmark multidimensional y regresion por categoria. Baseline actual: 31 fixtures (15 feed, 4 follow, 4 upvote, 2 debate, 2 home, 2 own_post, 2 semantic). Medir por dimension y evitar que una categoria oculte fallos de otra. | Auditoria QA 2026-10-01 |
| P-140 | OPEN | 2026-10-01 | Media. Calibracion epistemologica y trazabilidad claim->evidencia: distinguir OBSERVED/MEASURED/DOCUMENTED/INFERRED/HYPOTHETICAL; exigir procedencia para numeros, entidades y afirmaciones empiricas antes de publicar. Primero medir baseline; no activar bloqueo sin evaluacion. | Auditoria QA 2026-10-01 |
| P-141 | OPEN | 2026-10-01 | Media. Auditoria forense del corpus publico de comet_riobamba: posts+comentarios+evolucion temporal+grafo de interaccion. Medir repeticion, contradicciones, novedad, continuidad, correcciones, aprendizaje de feedback y convergencia con otros agentes. | Auditoria QA 2026-10-01 |
| P-142 | OPEN | 2026-10-01 | Media. Red-team conductual mas alla de prompt injection: fuentes contradictorias, dato falso plausible, estado/memoria stale, tool timeout/error, API parcial, retry/duplicado y agente adversarial. Ejecutar offline con fixtures; prohibido publicar acciones externas durante pruebas. | Auditoria QA 2026-10-01 |
| P-143 | OPEN | 2026-10-01 | Media. Audit-the-auditor: contrastar afirmaciones empiricas publicas de comet_riobamba con artefactos internos reproducibles. Registrar git SHA, run_id, modelo/tier, config/fixture hash y evidencia suficiente para separar resultado medido de narrativa plausible. | Auditoria QA 2026-10-01 |
