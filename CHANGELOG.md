# Changelog — COMET-RIOBAMBA

## [5.11.13] - 2026-09-24

### Sesion P-072: ADR-003 Aceptado + P-045 DONE + P-070 DONE

- **docs/adr/ADR-003-topic-source-priority.md:** status Propuesto -> Aceptado. Precedencia own_incident > evolution ratificada por Rafael.
- **docs/PENDING.md:** P-070 DONE (reglas 7b/12b verificadas en DIRECTRICES). P-045 DONE (capa A conftest.py + capa B ADR-003).
- **docs/MAPA_TECNICO.md:** ADR-003 agregado a lista de ADRs en seccion 7.
- **tests/conftest.py:** fixture _isolate_topic_state (autouse): aisla topic_evolution_state.json y topic_matrix_state.json. Suite 1507 passed, 1 skipped.

## [5.11.12] - 2026-09-23

### Cierre sesion P-071: handoff + anti-patron ERROR M

- **docs/HANDOFF_2026-09-23_p071.md (nuevo):** cierre de sesion. Cubre
  diagnostico P-045/P-071, ADR-003, reglas 7b/12b.
- **docs/PROMPT_APERTURA.md:** agrega ERROR M (diagnosticar sin reproducir).
  Alinea el prompt con regla 12b agregada hoy a DIRECTRICES.
- Pendientes abiertos para proxima sesion: P-045 (fix tests), P-070
  (aplicar 7b/12b), P-071 (fix produccion). Dependen de aprobar ADR-003.

## [5.11.11] - 2026-09-23

### ADR-003: precedencia de fuentes de tema en Phase A

- **docs/adr/ADR-003-topic-source-priority.md (nuevo, Status Propuesto):**
  define jerarquia own_incident > evolution > agenda > roadmap > matrix > niche.
- **Razon:** material unico (own_incident) no puede bloquearse por material
  derivado (evolution). Restaura coherencia con v5.3 documentado en choose_topic.
- **Bug P-071** documentado en el ADR. Fix de produccion y de tests queda
  pendiente de aprobacion del ADR.

## [5.11.10] - 2026-09-23

### P-045: causa raiz reproducida (P-071 registrado)

- **Reproduccion:** con data/topic_evolution_state.json alterado (1 serie status=active), el
  test TestIncidentFiguresGate::test_body_without_figures_rejected_and_incident_stays_unused
  falla con 'topic ... rejected by editorial filter, using fallback'. Con state restaurado (0 active), pasa.
- **Causa raiz (2 capas):** (A) tests/conftest.py no aisla topic_evolution_state.json ni
  topic_matrix_state.json; (B) evolution asigna topic antes que choose_topic, y el fallback de
  _apply_editorial_filter no restaura la prioridad own_incident (bug de produccion).
- **P-045 corregido:** no son 8 tests; son 2, y solo con series activas en disco.
- **P-071 (nuevo, OPEN):** bug de produccion por perdida de prioridad own_incident cuando evolution
  tiene serie active. Requiere ADR para decidir precedencia.
- **State restaurado** desde backups/topic_evolution_state.json.bak-20260923-210313. Servicio no afectado.

## [5.11.9] - 2026-09-23

### Directrices: regla 7b + operativa 12b (P-070)

- **P-070 (nuevo, OPEN):** registra violaciones a reglas 1/2/12 durante
  el diagnostico de P-045 en esta sesion.
- **DIRECTRICES.md Principios:** agrega regla 7b "No ser condescendiente."
- **DIRECTRICES.md Operativas:** agrega 12b exigiendo reproducir el fallo
  antes de proponer fix. Lectura estatica de codigo NO es verificacion.
- numstat 2/0 (DIRECTRICES) + 1/0 (PENDING). Commit 4684933.
- Nota EOL: PENDING.md arrastraba un LF-suelto pre-existente en linea de
  P-067 (commit b62de09); normalizado al commitear.

## [5.11.8] - 2026-09-23

### Fix auto-detect de handoff en PROMPT_APERTURA + saneamiento post-Claude

- **P-069 (nuevo, DONE):** PASO 1 del prompt usaba Sort-Object Name,
  que en ASCII ordena punto antes que underscore; un sufijo _p006
  quedaba segundo y el detectado era el handoff viejo. Ahora usa
  Sort-Object LastWriteTime -Descending. Verificado: detecta
  HANDOFF_2026-09-23_p006.md (54 lineas). numstat 4/3.

- **Saneamiento:** sesion previa con Claude cerro P-007 (05dd801:
  floors min=0->2/1/1; b62de09: P-007 DONE + P-068 + CHANGELOG 5.11.7)
  y enriquecio P-045 (gate _count_incident_figures existe; commits
  2e60d3f/93e72f2 verificados), pero dejo PENDING.md modificado sin
  commitear. Incorporado en este cierre.

## [5.11.7] - 2026-09-23
### Fixed
- P-007: floor `min=0` corregido en `max_comments_per_day` (0->2), `max_feed_replies_per_day` (0->1), `max_comments_per_post` (0->1) en `config/auto_appliable.py`. Impedia que el motor de auto-mejora silenciara al agente. 12 tests passed.
### Added
- P-068: registrado hallazgo `config/behavior_cfg.py` (v4.3.0) codigo muerto.


## [5.11.6] – 2026-09-23

### Post-mortem model_error + cierres P-006/P-058/P-067

- **docs/POSTMORTEM_MODEL_ERROR_2026-09.md:** nuevo (P-006). Sep 10 causa
  raiz: circuit breaker con 3 tiers abiertos (flash/fallback/pro) + bug
  phase_b (TypeError offset-naive/aware, 82 ocurr. en agent.log.2).
  Sep 1/2 sin logs de agente; 661 y 198 entradas en generation_attempts.

- **P-006 DONE.** Derivados: P-065 (anadir error_type a
  generation_attempts), P-066 (confirmar commit del fix datetime).

- **P-058 DONE:** verificado con Select-String que PROMPT_APERTURA.md no
  hardcodea HEAD. La premisa original ("contiene HEAD exacto") no aplicaba.

- **P-067 DONE:** PROMPT_APERTURA.md PASO 1 ahora detecta el handoff por
  nombre-fecha descendente ($h) y no hardcodea conteos. Duplicado HEAD
  eliminado. numstat 17/10. docs/HANDOFF_2026-09-23_p006.md creado.

## [5.11.5] – 2026-09-23

### Verificacion arranque automatico NSSM tras reboot real (P-002 cerrado)

- **Reboot real 17:39:47:** servicio CometRiobamba auto-arranco 17:40:13 (PID 6840)
  sin intervencion. StartType=Automatic (NSSM), cuenta LocalSystem.
- **Evidencia:** LastBootUpTime 17:39:47 vs StartTime proceso nssm 17:40:13;
  ciclo #283 completado OK post-boot (36.9s, sin error).
- **PENDING.md:** P-002 OPEN -> DONE.

## [5.11.4] – 2026-09-23

### Rotacion de key automatizada + ADR-002 actualizado (P-049, P-062, P-064 cerrados)

- **scripts/rotate_key.py:** nuevo script con validacion HTTP previa, backup
  timestamped del blob DPAPI, escritura atomica DPAPI+keyring, rollback
  automatico, y modo --dry-run. Reemplaza el procedimiento manual.
- **docs/adr/ADR-002:** Status -> Aceptado; Paso 3 sin Read-Host -AsSecureString
  (usa new_key.tmp); INV7 (rollback automatico); Consequences sin P-048 pendiente.
- **P-064:** PROMPT_APERTURA v6 corregido in-place (HANDOFF 10->9 en 3 sitios;
  200->112 en ERROR A). Sin bump.
- **Pendiente derivado:** P-058 (prompt HEAD vs verificacion git).

## [5.11.3] – 2026-09-22

### Unificación de wrappers de lectura de MOLTBOOK_API_KEY (P-048 cerrado)

- **Wrapper canónico único:** config/credentials.py::_get_secret() (DPAPI -> keyring -> env).
- **services/top_agents_tracker.py:** wrapper propio (keyring -> env) eliminado; delega en _get_secret. Bootstrap sys.path para ejecución directa.
- **services/editorial_self_audit.py::main():** keyring directo eliminado; delega en _get_secret.
- **Verificación:** py_compile OK; pytest test_editorial_self_audit 10 passed; smoke test import key len 44 (DPAPI/keyring) y len 0 con COMET_DISABLE_KEYRING=1; git grep sin lectores restantes (P-060 cerrado).
- **Sin reinicio de servicio:** módulos afectados son CLI/huérfanos; el ciclo del agente no se toca.
- **Pendientes nuevos:** P-061 (mensajes de error desactualizados), P-062 (ADR-002 desactualizado).
- **Documentación:** docs/PENDING.md, docs/MAPA_TECNICO.md §4.

## [5.11.2] – 2026-09-22

### Rotación de MOLTBOOK_API_KEY (P-047 cerrado)

- **Backup:** data\.secrets_backup\moltbook_api_key.20260922_200436.enc (hash DB0EF5C9...).
- **Validación previa:** HTTP 200 contra GET /api/v1/feed antes de sobrescribir.
- **Persistencia:** DPAPI + keyring actualizados, verificación post-escritura OK.
- **Servicio:** detenido 20:06, reiniciado 20:20:35, sin errores 401/403.
- **Procedimiento:** ver docs/adr/ADR-002-moltbook-key-rotation.md.
- **Archivos temporales:** scripts\_validate_key.py, scripts\_validate_key_file.py, scripts\_rotate_key.py, new_key.tmp (borrado).
- **Pendiente derivado:** P-048 (unificar los 3 wrappers de lectura de key).




## [5.11.1] – 2026-09-22

### Auditoría de entorno + preparación de rotación de key

- **docs/AUDITORIA_ENTORNO.md** creado — snapshot de servicios, wrappers, endpoints, secretos.
- **docs/MAPA_TECNICO.md** creado — mapa de servicios, módulos, wrappers y endpoints.
- **docs/adr/ADR-002-moltbook-key-rotation.md** creado — procedimiento con backup y rollback.
- **docs/PENDING.md** actualizado — P-048 a P-057 añadidos.
- **Hallazgo:** DPAPI y keyring contienen la misma MOLTBOOK_API_KEY; 2 wrappers ignoran DPAPI.
- **Hallazgo:** GET /api/v1/users/me no existe (404); endpoint correcto para validación es GET /api/v1/feed.
- **Pendiente:** P-047 (rotar key) en ejecución.

### Notas operativas

- Working dir del servicio: C:\comet-riobamba-v31
- Entry point: run_agent.py (Python 3.14.7)
- NSSM: C:\comet-riobamba-v31\tools\nssm.exe
- Frecuencia del agente: ciclo ~250s + espera 1800s

\# Changelog — COMET-RIOBAMBA


## [5.11.x] – 2026-08-29

### Fix: title_has_scaffold() detecta reasoning leaks

- **services/quality_governor.py**: Función 	itle_has_scaffold() reescrita para incluir patrones de scaffold interno además de clickbait SEO
  - Patrones agregados: "here's a thinking process:", "critique:**", "we need to critique", "post-mortem:", "analysis:", "step ", "step:"
  - Check agregado: títulos que terminan en : (instrucciones, no títulos declarativos)
  - Check agregado: títulos que empiezan como items de lista (- , * , 1. )
  - Agregado import re para soportar e.match() en los checks
- **Impacto**: Títulos con fugas de razonamiento interno ahora son bloqueados correctamente en el gate de validación de Phase A
- **Referencia**: docs/fixes/FIX-2026-08-29-title-has-scaffold-reasoning-leaks.md


\## \[5.0.0] – 2026-06-07



\### Cambios clave



\- Refactor mayor de arquitectura A–B–C usando OpenCode + OpenCode Zen como coding agent asistente.

\- Separación estricta de \*\*configuración\*\* vs \*\*credenciales\*\*:

&#x20; - Nuevo módulo `config/credentials.py` con `Credentials.from\_env()` como único loader de API keys y endpoints.

&#x20; - `config/config.py` se enfoca en `behavior\_cfg`, `content\_cfg`, `routing\_cfg`, `logging\_cfg` sin secretos.



\- Circuit breakers unificados:

&#x20; - Implementación canónica `CircuitBreaker` en `utils/resilience.py` con soporte opcional de persistencia.

&#x20; - `services/global\_circuit.py` convertido en wrapper delgado con `SQLiteCircuitPersistence` para el control del ciclo global.

&#x20; - `services/model\_cascade.py` y `services/moltbook\_api\_client.py` migrados a `CircuitBreaker`, eliminando implementaciones duplicadas.



\- Desac acople de fases:

&#x20; - Nuevas dataclasses `PhaseADeps`, `PhaseBDeps`, `PhaseCDeps` en `phases/deps.py`.

&#x20; - Fases A, B y C ya no reciben el objeto `agent` completo, sino sus dependencias explícitas.



\- Phase B unificada:

&#x20; - Nueva `phases/phase\_b.py` con clase `PhaseB`:

&#x20;   - `execute()` como entrypoint único.

&#x20;   - `\_execute\_feed\_replies()` y `\_execute\_own\_post\_replies()` como subfases internas.

&#x20; - Antiguas `phase\_b\_replies.py` y `phase\_b\_responses.py` archivadas.



\- Phase C Engagement modular:

&#x20; - Nuevo paquete `phases/engagement/` con:

&#x20;   - `PhaseCEngagement` (fachada),

&#x20;   - `Classifier` (`classifier.py`),

&#x20;   - `Tracker` (`tracker.py`),

&#x20;   - `Responder` (`responder.py`).

&#x20; - Archivo monolítico `phase\_c\_engagement.py` movido a `\_archive/`.

&#x20; - Corrección de todas las cadenas con mojibake en español (UTF‑8 limpio).



\- Manejo de errores y logging estandarizado:

&#x20; - Nuevo módulo `utils/phase\_utils.py` con:

&#x20;   - `phase\_error\_boundary` como decorador de `execute()` para cada fase.

&#x20;   - `validate\_phase\_deps` para asegurar deps bien formadas.

&#x20; - Loggers homogéneos (`phases.phase\_a\_content`, `phases.phase\_b`, `phases.phase\_c.\*`) y métricas de error por fase.



\- Limpieza de API Moltbook:

&#x20; - Eliminados alias camelCase en `MoltbookAPIClient` (`createpost`, `getfeed`, etc.).

&#x20; - Uso exclusivo de métodos snake\_case (`create\_post`, `get\_feed`, `get\_comments`, etc.).

&#x20; - Archivo legacy `core/model\_router.py` archivado en `\_archive/`.



\### Notas de migración



\- Si tenías scripts externos que usaban alias camelCase del cliente de Moltbook, debes actualizarlos a los métodos snake\_case canónicos.

\- La inicialización del agente ahora requiere un objeto `Credentials`:

&#x20; - Ejemplo:

&#x20;   ```python

&#x20;   from config.credentials import Credentials

&#x20;   from core.agent import COMETRiobambaAgent



&#x20;   creds = Credentials.from\_env()

&#x20;   agent = COMETRiobambaAgent(credentials=creds)

&#x20;   ```



\---



\## \[4.3.3] – 2026-05-XX



\- Última versión pre‑refactor A–B–C.

\- Fases acopladas al objeto `agent`, circuit breakers duplicados y Phase B/C en archivos monolíticos.

\- Punto de partida para la migración a la arquitectura v5.0.





