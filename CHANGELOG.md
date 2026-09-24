# Changelog — COMET-RIOBAMBA

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





