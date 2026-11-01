# COMET-RIOBAMBA — Agent Guidance

## 1. Propósito y autoridad

Este archivo define reglas de trabajo para asistentes y operadores del repositorio COMET-RIOBAMBA.
No es fuente de verdad para estado operativo volátil.

Jerarquía mínima:
- `docs/PENDING.md`: estado canónico OPEN/DONE/REJECTED de IDs P-xxx.
- `docs/AUDIT_PROGRESS.md`: historia append-only de auditoría y cierres.
- `docs/DOC_COHERENCE.md`: mapa de roles/frescura documental.
- `docs/PROJECT_SYNC_MANIFEST.md`: precedencia entre evidencia, documentación, handoffs y memoria.
- `docs/SECRET_POLICY.md`: política SECRET-01.
- Código + evidencia reproducible: autoridad para comportamiento técnico observado.
- Memoria/handoffs: continuidad; nunca autoridad para HEAD, branch, Git status, hashes, PID, servicio, DB o resultados actuales.

Si dos fuentes entran en conflicto, no improvisar: detener la atribución y reconstruir evidencia.

## 2. Modo de trabajo obligatorio

- Evidence-first: verificar antes de afirmar.
- Reproducir un RED antes de atribuir causa raíz cuando sea practicable.
- Separar explícitamente:
  - `SOURCE_CLAIM`: una fuente afirma X.
  - `EIN_ASSESSED`: el claim atravesó EIN.
  - `CHECKED_NO_CONTRADICTION`: no se detectó contradicción aplicable; no significa verdad verificada.
  - `DISPUTED`: conflicto con evidencia/regla aplicable.
  - `DEBUNKED`: rechazo determinista por regla dura aplicable.
- `claimed != verified`.
- Resultado medido, inferencia e interpretación narrativa deben quedar diferenciados.
- No declarar un workstream cerrado hasta cumplir literalmente su criterio de aceptación.

## 3. MCP-first y PowerShell

Para auditoría normal read-only, usar primero `comet-local-auditor` mediante el Secure MCP Tunnel cuando esté disponible.

Superficies MCP read-only esperadas:
1. `repo_identity`
2. `git_status_summary`
3. `service_state`
4. `file_hash`
5. `read_text_file`
6. `file_metadata`
7. `list_directory`
8. `git_diff_readonly`
9. `git_file_at_revision`

Si MCP no está disponible, declarar el bloqueo antes de recurrir a PowerShell.

Cuando sea necesario PowerShell dentro del protocolo COMET/EIN:
- exactamente una línea física por turno;
- el usuario ejecuta localmente y devuelve la salida completa;
- contar untracked con `.StartsWith('??')`;
- no emitir una segunda línea/comando hasta analizar la salida anterior.

## 4. Control de mutaciones

Antes de cualquier mutación:
- verificar servicio/PID;
- verificar HEAD/branch;
- verificar Git status;
- fijar hashes de archivos protegidos/objetivo;
- crear backup/hash cuando aplique;
- declarar archivos y alcance exactos.

STOP inmediato ante:
- delta inesperado del working tree;
- hash inesperado;
- servicio/PID inesperado;
- expansión de alcance;
- drift de encoding/EOL no explicado;
- cambio inesperado de datos productivos.

Nunca sin autorización explícita:
- commit;
- push;
- restart de producción;
- cambio de servicio;
- borrado/archivo;
- schema/runtime switch-over;
- enforcement global P-140;
- escrituras externas;
- full suite si no estaba ya autorizada.

## 5. Seguridad de producción

`CometRiobamba` debe permanecer `Stopped` durante intervenciones hasta autorización explícita de producción.

No usar `taskkill` ni procedimientos NSSM alternativos fuera del camino operativo acordado.

Los tests que puedan escribir deben usar rutas/DB temporales o monkeypatches. No asumir aislamiento: verificarlo.

Antes de reiniciar producción deben resolverse los bloqueadores vigentes del handoff actual, incluyendo credenciales, outbox, pause state, OUTBOX-SAFETY y guards de servicio/PID/HEAD/tree cuando apliquen.

## 6. Integridad de archivos

- Preservar bytes y EOL.
- No normalizar CRLF/LF de forma incidental.
- Para non-ASCII usar UTF-8 explícito y verificación byte-aware.
- Evitar escrituras genéricas de texto PowerShell sobre fuentes sensibles.
- Si falla decoding, hacer forensia read-only antes de reescribir.
- `phases/phase_b/scoring.py` es superficie protegida: no modificar salvo cambio explícito de protocolo.

## 7. SECRET-01

Nunca solicitar, imprimir, pegar en ChatGPT ni versionar:
- API keys completas;
- tokens;
- passwords;
- session cookies;
- private keys;
- recovery codes;
- credenciales secretas.

Usar únicamente nombre de variable, presencia, longitud, últimos 4 cuando sea estrictamente necesario o hash/fingerprint irreversible.

Si un secreto aparece en chat o salida, tratarlo como comprometido y rotar/revocar.

## 8. Arquitectura runtime verificada

Entrypoint:
`run_agent.py` → `core.agent.main()`.

El agente construye `COMETRiobambaAgent` en `core/agent.py` y conecta dependencias de Phase A, Phase B y Phase C.

Phase B actual es un paquete modular bajo `phases/phase_b/`, no un archivo monolítico `phases/phase_b.py`. Entre sus módulos están `orchestrator.py`, `scoring.py`, `candidate_scorer.py`, `engagement.py`, `constants.py` y `value_log_utils.py`.

Phase C incluye al menos `phases/phase_c_analytics.py`, `phases/phase_c_watchlist.py` y `phases/engagement/`.

No convertir este resumen en autoridad eterna: si la arquitectura cambia, volver a verificar el árbol/imports antes de actualizar esta sección.

## 9. COMET ↔ EIN

Arquitectura objetivo:
- EIN = autoridad científica y de schema lógico.
- COMET = consumidor/orquestador mediante contrato versionado.
- COMET no realiza migraciones científicas autónomas de `energy_intel.db`.

Orden P-147:
`P147A Contract RED → P147B EIN parity → P147C Schema evolution → P147D COMET adapter → P147E Shadow comparison → P147F Controlled switch-over → P147G Embedded retirement`.

No saltar etapas.

## 10. Testing y evidencia

Para claims científicos o conductuales registrar cuando corresponda:
- git SHA;
- run_id;
- modelo/tier;
- hash de config/fixture;
- tests exactos;
- hashes before/after;
- filesystem delta;
- estado del servicio.

`tests/conftest.py` contiene aislamiento para múltiples sinks persistentes, incluido `data/state/health.json`, pero esto no autoriza asumir que toda la suite es inocua. La no-contaminación debe demostrarse para el alcance ejecutado.

No hardcodear en este documento el número de tests o el último resultado de suite: son estados volátiles.

## 11. Operación y scripts

`scripts/ops/` contiene utilidades operativas manuales. Su mera existencia no implica que formen un operador reproducible ni que estén vigentes.

Antes de ejecutar un script operativo:
1. leerlo;
2. verificar que sus paths/assumptions existan;
3. clasificar si es read-only o mutante;
4. aplicar guards;
5. pedir autorización cuando corresponda.

No usar referencias históricas a watchdog/health-check retirados como instrucciones activas. Verificar archivos actuales antes de ejecutar cualquier monitor o supervisor.

## 12. CI, supply-chain y GitHub

No asumir que existe CI/CD, GitHub Actions, branch protection, lint o type checking por documentación histórica.

P-151 es el workstream que debe construir y verificar estas superficies por etapas:
- operador reproducible;
- lint read-only;
- CI/GitHub Actions;
- supply-chain;
- branch protection;
- reconciliación local-GitHub.

La reconciliación con GitHub ocurre solo después de validación documental/tests y autorización explícita para cualquier commit/push o cambio remoto.

## 13. Git y documentación

- No commit/push sin autorización explícita.
- No inventar un nuevo P-xxx casualmente.
- Actualizar la fila canónica de `docs/PENDING.md` cuando cierre un ID real.
- `docs/AUDIT_PROGRESS.md` es append-only.
- Handoffs son derivados de continuidad, no fuente canónica de estado.
- Antes de declarar una capacidad cerrada, reconciliar implementación, evidencia, docs y GitHub cuando el contrato del workstream lo exija.

## 14. Principio científico del agente

Pipeline objetivo:
`OBSERVE → EXTRACT CLAIMS → GROUND → TEST/FALSIFY → DECIDE → ACT`.

COMET debe priorizar mecanismos, falsabilidad, trazabilidad y utilidad verificable. EIN aporta contraste determinista cuando aplica. Reputación/karma es una consecuencia observable, no la función objetivo primaria.

Regla de estilo científico:
**Invent the mechanism, never the evidence.**
