# ADR-005 — Schema versioning SQLite

**Estado:** Aceptado
**Fecha:** 2026-09-26
**Contexto:** sesion p099 → P-093 (deuda detectada en p093).

## Contexto

Las bases SQLite del agente se creaban con `CREATE TABLE IF NOT EXISTS`
(`SCHEMA_SQL`) y, cuando hacia falta una columna nueva, se agregaba con
`ALTER TABLE` manual inline. Casos reales:

- `services/karma_roi_tracker.py`: `action_type` agregado a mano (P-092).
- `services/persistence.py`: 7 columnas de `agent_state` agregadas por loop
  inline que absorbe `OperationalError`.

Ninguna DB llevaba marcador de version (`PRAGMA user_version = 0`).
Consecuencia: imposible saber si una DB en produccion ya paso por una
migracion, ni re-ejecutarla de forma reproducible.

## Decision

1. Cada modulo que posee una DB declara dos constantes:
   - `SCHEMA_VERSION: int` — version objetivo actual.
   - `MIGRATIONS: List[Tuple[int, Callable[[sqlite3.Connection], None]]]` —
     pasos ordenados por target.
2. `core/sqlite_migrations.py::apply_migrations(conn, schema_version,
   migrations, label)` es el unico aplicador. Contrato:
   - Lee `PRAGMA user_version`.
   - Si `user_version > schema_version` → `RuntimeError` (DB mas nueva que
     el codigo; no se degrada silenciosamente).
   - Aplica en orden los pasos con `target > user_version`; tras cada paso
     actualiza `user_version` y hace commit.
   - Si al final `user_version < schema_version` (caso `MIGRATIONS=[]`,
     baseline jump): sube `user_version` a `schema_version`.
   - Idempotente: segunda llamada es no-op.
3. `SCHEMA_SQL` (CREATE IF NOT EXISTS) sigue siendo la foto actual y se
   ejecuta antes de `apply_migrations` en DBs nuevas.
4. Las migraciones pasadas one-shot se vuelven codigo reproducible:
   envueltas en `_migrate_vN` idempotentes (`if col not in cols: ALTER`).

## Alcance (P-093a)

5 DBs del agente: `memory.db`, `comet_state.db`, `topic_memory.db`,
`comet_dedup.db`, `karma_roi.db`. Todas quedan en `SCHEMA_VERSION = 1`.

Pendiente (P-100): extender a `scripts/comet_repurposer/`
(`publish_queue.db`, `repurpose_dedup.db`, `semantic_dedup.db`) y decidir
`energy_intel.db` (escritor en `docs/ein/`, no en runtime).

## Invariantes

- INV1. Toda DB de runtime debe tener `user_version >= 1`.
- INV2. `apply_migrations` nunca reduce `user_version`.
- INV3. Una migracion declarada es idempotente respecto a su propio estado
  final (re-ejecutarla sobre una DB ya migrada no falla ni duplica).
- INV4. `SCHEMA_SQL` refleja el estado de `SCHEMA_VERSION` (no se desfasa).

## Consecuencias

- Pro: DBs auto-verificables; `PRAGMA user_version` es chequeo de salud.
- Pro: las migraciones manuales previas quedan capturadas en codigo.
- Con: si se olvida bumpear `SCHEMA_VERSION` al cambiar `SCHEMA_SQL`, la
  DB vieja no migra (INV4 lo mitiga como disciplina, no como enforcement).
- Con: `apply_migrations` no corre en `_get_conn()` de karma_roi con
  `conn.executescript` en cada llamada (mismo comportamiento que antes).


## Addendum 2026-09-26 (P-100a)

Extension al repurposer (los 3 DBs: `publish_queue.db`,
`repurpose_dedup.db`, `semantic_dedup.db`), todos en `SCHEMA_VERSION = 1`.

### Decisiones

1. **No importar `core/sqlite_migrations.py`.** El repurposer es paquete
   standalone (propio `requirements.txt`, `.env.example`, README; se invoca
   por subproceso `python -m comet_repurposer` desde
   `services/content_distributor.py`). Se duplica el helper en
   `scripts/comet_repurposer/comet_repurposer/migrations.py` (~30 lineas,
   mismo contrato). Trade-off aceptado: dos copias pequenas a mantener vs
   acoplar paquete independiente al core del agente.

2. **`energy_intel.db` NO se decide aqui (P-100b).** Correccion a la premisa
   de P-100: la DB SI se escribe desde runtime
   (`services/energy_knowledge_base.py::update_claim_status`) ademas del
   escritor primario `docs/ein/energy_intel_node.py`. Decidir dueno del
   schema requiere ADR aparte.

### Invariantes adicionales (repurposer)

- INV1b. `scripts/comet_repurposer/comet_repurposer/migrations.py` mantiene
  contrato identico a `core/sqlite_migrations.py`; divergencias entre ambos
  son deuda explicita, no evolucion independiente.
- INV5. `services/content_distributor.py` invoca el repurposer con
  `cwd=scripts/comet_repurposer`, por lo que `project_root = os.getcwd()`
  resuelve a ese subdirectorio. Los DBs activos en produccion viven en
  `scripts/comet_repurposer/data/*.db`, no en `data/*.db` (raiz). Existe
  duplicado `publish_queue.db` en ambos. Registrado como P-101.

### Consecuencias

- Pro: los 3 DBs del repurposer quedan auto-verificables.
- Con: helper duplicado (30 lineas); mitigado por INV1b.
- Con: la discrepancia cwd/DBs activos (INV5) puede inducir confusion al
  inspeccionar `data/` desde la raiz. P-101 propone fijar cwd a raiz.


## Addendum bis 2026-09-26 (P-100b) - energy_intel.db

**Contexto:** sesion p102. Cierre de P-100 (ultimas DBs fuera de core/).

### Correccion al addendum P-100a

El addendum P-100a afirmo que la DB "SI se escribe desde runtime
(services/energy_knowledge_base.py::update_claim_status)". La auditoria de
p102 (grep excluyendo tests/ y backups/) muestra que update_claim_status NO
tiene caller en produccion: sus unicos usuarios son 3 tests en
tests/test_energy_kb.py. Los unicos escritores reales viven dentro del node
standalone. Premisa corregida.

### Dueno del schema

docs/ein/energy_intel_node.py es el unico dueno: posee SCHEMA (tabla claims
+ idx_tech/idx_status/idx_date), init_db() y db_conn() con
PRAGMA journal_mode=WAL. Escritores reales (upsert_claim L122 via run_ingest;
POST /claims; PATCH /claims/{id}) estan dentro del mismo modulo standalone.

Consumidores runtime (solo lectura): phases/phase_b/orchestrator.py:205
(ruta absoluta BASE_DIR/data/energy_intel.db); scripts/generate_energy_report.py;
services/energy_intel_telegram.py:396.

### Decisiones

1. Helper de migraciones INLINE en el node (no sibling): el modulo se declara
   "single-file" y un import cross-cwd desde energy_intel_telegram.py:158
   seria fragil. Contrato duplicado de core/sqlite_migrations.py (~10 lineas
   activas; INV1c).
2. SCHEMA_VERSION = 1, MIGRATIONS = [] en el node. apply_migrations se llama
   justo despues de c.executescript(SCHEMA) en init_db() (cubre L557
   run_ingest y L711 main).
3. EnergyKnowledgeBase pasa a ruta absoluta por defecto:
   Path(__file__).resolve().parents[1] / "data" / "energy_intel.db".
   Alinea con DB_PATH del node (parents[2]) y elimina foot-gun de cwd.
4. update_claim_status permanece como via de escritura runtime permitida pero
   latente (sin caller hoy). Si se invoca, debe respetar el enum
   claimed|disputed|debunked del PATCH del node. Endurecer: P-113.
5. Validacion uv>=1 en runtime (KB) se difiere a P-114: (i) versionar node y
   correrlo -> DB queda en uv=1; (ii) luego KB valida.

### Invariantes adicionales

- INV1c. El helper inline apply_migrations del node mantiene contrato
  identico a core/sqlite_migrations.py y al del repurposer. Divergencias son
  deuda explicita (mismo criterio que INV1b).
- INV6. energy_intel.db tiene un unico dueno de schema:
  docs/ein/energy_intel_node.py. EnergyKnowledgeBase no crea ni migra; solo
  lee (y, si se invoca, actualiza status de una fila puntual).
- INV7. Todo lector runtime abre el archivo por ruta absoluta resuelta desde
  __file__ o BASE_DIR. Ruta relativa Path("data/...") prohibida en no-test.
- INV8. Contrato ruta node<->KB: DB_PATH del node ==
  BASE_DIR/data/energy_intel.db. Cubierto por
  tests/test_energy_intel_node.py::test_db_path_matches_orchestrator_energy_knowledge_base.

### Consecuencias

- Pro: energy_intel.db auto-verificable (uv>=1 tras primera corrida del node).
- Pro: P-100 cerrado completo (5 DBs agente + 3 repurposer + 1 energy_intel).
- Pro: eliminado el foot-gun de cwd en EnergyKnowledgeBase.
- Con: tercer duplicado del helper (~10 lineas); mitigado por INV1c.
- Con: update_claim_status sigue sin caller; se documenta pero no se elimina.
- Con: validacion uv>=1 en runtime diferida (P-114).
