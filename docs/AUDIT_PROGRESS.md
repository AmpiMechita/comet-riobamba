# AUDIT_PROGRESS — Estado de la auditoría integral

> Actualizado: 2026-09-12
> Este archivo es la fuente de verdad del progreso. Si algo contradice
> este documento, actualizar aquí primero.

---

## Resumen de fases

| Fase | Estado | Producto | Fecha |
|------|--------|----------|-------|
| 0   | Cerrada | Higiene repo (Fase 0) | 2026-09-11 |
| 0.5b| Cerrada | _diag_config_05b.out.txt | 2026-09-10 |
| 1   | **CERRADA** | data/code_inventory_20260912.json | 2026-09-12 |
| 2   | PENDIENTE | (archivo por archivo) | — |
| 3   | PENDIENTE | (tests) | — |
| 4   | PENDIENTE | (scripts huérfanos) | — |
| 5   | PENDIENTE | (backups/trash) | — |

---

## Fase 1 — Inventario de código

**Cerrada:** 2026-09-12

**Producto:** `data/code_inventory_20260912.json`

**Hallazgos:**
- 372 archivos .py en el repo (sin backups/trash/.venv)
- 63 huérfanos (nadie los importa, no ejecutables, no tests)
- 12 scripts sueltos con `if __name__`
- 8 grupos de posibles duplicados (algunos cosméticos como `__init__.py`)

**Distribución:**
- tests: 99
- scripts: 72
- services: 68
- raíz: 52 (mayoría huérfanos)
- core: 14
- phases: 16
- config: 8
- utils: 9
- monitoring: 3
- otros: 31

**Duplicados críticos a resolver en Fase 2 (prioridad ALTA):**
1. `core/challenge_solver.py` vs `services/challenge_solver.py`
2. `core/metrics.py` vs `services/metrics.py`
3. `services/telegram_client.py` vs `services/telegram_client_verified.py`
4. `model_router_fixed.py` vs `services/model_router.py`

**Duplicados menores:**
5. `monitor_groq_usage.py` vs `monitoring/monitor_groq_usage.py`
6. `config/config.py` vs `scripts/comet_repurposer/comet_repurposer/config.py`
7. `deploy/validated-20260617-moltbook/moltbook_api_client.py` (versión antigua)

---

## Contexto previo (de sesiones anteriores)

- **CONFIG_TRUTH.md** — fuente de verdad de configuración. Ver también.
- **Fases cerradas previamente**: cascada bug identificado (pendiente fix),
  quota_manager bug identificado (pendiente arreglo), Fase C auditada
  (niche_prompts huérfanos, diseño inbound_learnings sin implementar).
- **Pendientes globales**:
  - Fix cascada (2 líneas en model_cascade.py, verificado por hash)
  - Arreglar quota_manager (bloqueado por Fase 2)
  - Decidir destino de 63 huérfanos
  - Decidir destino de niche_prompts.py (diseño huérfano)
  - Recarga DeepSeek $5 (en espera)

---

## Fase 2 — Planificación

**Orden propuesto:**
1. **Fase 2.1 — Duplicados críticos** (4 grupos) ← empezar aquí
2. Fase 2.2 — Core (14 archivos)
3. Fase 2.3 — Services (68 archivos)
4. Fase 2.4 — Phases (16 archivos)
5. Fase 2.5 — Config + Utils (17 archivos)

**Método por archivo:**
1. Leer completo
2. Decidir: conservar / refactorizar / archivar / borrar
3. Verificar que nadie depende de él
4. Documentar decisión
5. Commit atómico
---

## Fase 2.1 — Duplicados críticos (CERRADA)

**Cerrada:** 2026-09-12
**Producto:** data/duplicates_audit_20260912.json

### Hallazgos y decisiones

| Grupo | Diagnóstico real | Acción |
|-------|------------------|--------|
| challenge_solver | Dos APIs complementarias (adaptador + clase) | REFACTOR: core/ pasa a wrapper fino de services/ |
| metrics | Dos sistemas con nombre genérico | RENAME: desambiguar nombres + actualizar imports |
| telegram_client | Duplicado literal | DELETE: borrar `_verified`, actualizar 2 tests |
| model_router | Bug real: producción usa versión con `Path.cwd()` | FIX: portar corrección a services/, borrar raíz |

### Orden de ejecución propuesto

1. **FIX model_router** (bug real, prioridad máxima)
2. **DELETE telegram_client_verified** (riesgo cero)
3. **RENAME metrics** (riesgo bajo, actualizar 2 imports)
4. **REFACTOR challenge_solver** (riesgo medio, último)

### Pendientes de Fase 2.2 (core/)
- 14 archivos de core/ por auditar
- Prioridad: `agent.py` (68 KB, el más grande del repo)

---

## Fase 2.1 — Grupo 4 (model_router) — CERRADA

**Cerrada:** 2026-09-12

**Diagnóstico:**
- `model_router_fixed.py` (raíz) era un parche que nunca se portó a producción.
- `services/model_router.py` usaba `BASE_DIR = Path.cwd()` → fallaba desde subdirectorios.
- Bug reproducido en vivo: import desde TEMP devolvía `.env` no encontrado.

**Fix aplicado:**
- `services/model_router.py`: `BASE_DIR = Path(__file__).resolve().parent.parent`
- Hash antes: 97F5B83EFAF3108E5A9A2454A68CB82A
- Hash después: 037007CF8EF05E79DA288EFFCE094583
- Backup: `%USERPROFILE%\backups\comet-riobamba\model_router.py.20260912_203702.bak`

**Verificación:**
- Import normal: BASE_DIR = C:\comet-riobamba-v31, ENV_FILE exists = True
- Import desde TEMP: BASE_DIR = C:\comet-riobamba-v31, ENV_FILE exists = True
- Caller real (phase_a_content): importable OK

**Acción secundaria:**
- `model_router_fixed.py` borrado (huérfano, backup previo).

**Siguiente:** Grupo 3 (telegram_client_verified, borrado).

---

## Fase 2.1 — Grupo 3 (telegram_client) — CERRADA

**Cerrada:** 2026-09-12

**Diagnóstico:**
- `services/telegram_client.py` y `services/telegram_client_verified.py` son
  duplicados literales (MD5 288AFE3D5020FECFF2244458BAB2B93D).
- El "_verified" fue creado por `final_check.py` como supuesto respaldo.
- Corrección al informe inicial de opencode: NO hay tests que lo usen.
  Solo referencias: `final_check.py` (creador) y `code_inventory.py` (auditor).

**Acción:**
- Borrado `services/telegram_client_verified.py`.
- Backup: `%USERPROFILE%\backups\comet-riobamba\telegram_client_verified.py.<stamp>.bak`.

**Pendiente colateral:**
- `final_check.py` (raíz) es un script historico que creo el duplicado.
  Candidato a borrado en Fase 4 (scripts huérfanos).

**Siguiente:** Grupo 2 (metrics, rename).

---

## Fase 2.1 — Grupo 2 (core.metrics) — CERRADA OFICIALMENTE

**Cerrada:** 2026-09-12

**Cambios aplicados:**
- Rename `core/metrics.py` -> `core/daily_metrics.py`
- 5 consumidores editados: observability.py, 3 scripts, 2 tests
- 1 test adicional arreglado: `tests/test_observability.py`
  (usaba `patch("core.metrics.ingest_event")` -> cambiado a daily_metrics)
- `core/metrics.py` borrado (backup previo).

**Verificacion:**
- 16 tests selectivos: PASS
- test_observability.py: 5/5 PASS
- pytest completo: 245 fails preexistentes (no relacionados), 0 fails causados.

**Leccion aprendida (para futuros renames):**
El grep de referencias debe incluir:
  - import_module("modulo")
  - __import__("modulo")
  - mock.patch("modulo.X")
  - monkeypatch.setattr("modulo.X", ...)
  - importlib.util.spec_from_file_location
El grep original solo cubria "from X import Y" y "import X as Y".
El punto ciego se descubrio con test_observability.py.

**Siguiente:** rename services/metrics.py -> services/counters.py.
Aplicar grep ampliado antes de tocar.

**Base de tests actual:** 1,424 total / 1,179 pass / 245 fail preexistentes.

---

## Fase 2.1 — Grupo 2A' (services.metrics) — CERRADA

**Cerrada:** 2026-09-12

**Cambios:**
- Rename `services/metrics.py` -> `services/counters.py`
- Editados: `utils/phase_utils.py`, `tests/test_phase6_error_boundary.py`
- Borrado `services/metrics.py` (backup previo)

**Verificacion:**
- test_phase6_error_boundary.py: 3/3 PASS
- pytest global: 245 fails / 1179 passed (identico al baseline, 0 regresiones)

**GRUPO 2 (metrics) CERRADO AL 100%.**
Rename core.metrics -> daily_metrics + rename services.metrics -> counters.

**Siguiente:** Grupo 1 (challenge_solver).

---

## Fase 2.1 — Grupo 1 (challenge_solver) — CERRADO

**Cerrada:** 2026-09-12

**Diagnostico confirmado por analisis de uso (data/challenge_solver_usage_20260912.json):**

- core/challenge_solver.py (311 lin):
  * Capa de bajo nivel. LLMClientAdapter + solve_sync.
  * Uso: core/agent.py (init 1 vez), moltbook_api_client (al exigir CAPTCHA).
  * Frecuencia: ocasional.
  * Tests: ninguno especifico.

- services/challenge_solver.py (361 lin):
  * Capa de alto nivel. ChallengeSolver clase con solve_and_verify.
  * Uso: phases/phase_a_content.py (post-publicacion).
  * Frecuencia: ocasional.
  * Tests: tests/test_challenge_solver.py (cubre _solve_native_math,
    _safe_eval_expression, _fix_mojibake, solve_and_verify).

**Solapamiento:** NINGUNO. Capas distintas con responsabilidades distintas.

**Decision:** COEXISTIR. Refactor NO necesario.
Razon: la separacion es limpia. Fusionar implicaria mover LLMClientAdapter
o duplicarlo. Bajo ROI.

**GRUPO 1 CERRADO.**

---

## RESUMEN FASE 2.1 (duplicados) — CERRADA COMPLETA

| Grupo | Diagnostico | Accion |
|-------|-------------|--------|
| model_router | version_vieja | Fix portado + fixed borrado |
| telegram_client | duplicado_exacto | verified borrado |
| metrics | names genericos | rename core->daily_metrics + services->counters |
| challenge_solver | capas complementarias | coexistir (documentado) |

**Siguiente:** Fase 3 — clasificar los 245 tests fallidos.

---

## Fix cascada (model_cascade.py) — CERRADO

**Cerrado:** 2026-09-13

**Bugs corregidos:**
1. `_fallback_priority`: pagados primero -> gratis primero.
2. `tier_fallback`: `paid=False` -> `paid=True`.

**Efecto esperado:**
- Reduccion ~$1.30/5d (~$78/mes) al evitar 964 llamadas pagadas innecesarias.

**Hashes:**
- Antes:  494593B0E79663E044BC3D64803E0DFC
- Despues: B248D432BF774F7D8ACE3B755B6D2D90
- Backup: %USERPROFILE%\backups\comet-riobamba\model_cascade.py.20260913_055826.bak

**Verificacion:**
- ModelCascade importable: OK.
- Suite completa: 244 failed / 1180 passed.
- Regresiones: 0.
- Arreglados: 2 (uno era del rename core.metrics, otro efecto colateral positivo:
  test_phase_b_dedup_limits TestPriority).

**Baseline tests actualizado:** 244 fails (era 245).

**Nota:** el "245" original era aproximado. La cuenta exacta previa al fix
era 246 lineas de FAILED en el archivo (probablemente una duplicada por tee).
El conteo real post-fix es 244.

---

## Fix quota_manager.py — CERRADO

**Cerrado:** 2026-09-13

**Bugs corregidos (3 ocurrencias del mismo patron):**
1. handle_quota_exceeded: walrus + and -> guard clause.
2. check_scheduled_reactivations: walrus + and -> guard clause.
3. check_scheduled_reactivations (reset): usaba _tmp redundante,
   ahora usa la variable qm ya disponible.

**Patron buggy eliminado:**
(_tmp := get_global_quota_manager()) and (_tmp.X)()
Explotaba con TypeError: NoneType not iterable cuando no habia
QuotaManager global inicializado.

**Hashes:**
- v0: 564D8B8ECCF9E31C8E0ED3934050B3FC
- v1 (fix 1+2): 9EB65EAE0DAEFB2F1A7888C52506A2BE
- v2 (fix 3): 4C1FD1D94B68E460FB4E2AD78CC1B2B7
- Backup: %USERPROFILE%\backups\comet-riobamba\quota_manager.py.fix3.20260913_090102.bak

**Verificacion:**
- check_scheduled_reactivations() con qm=None: no explota.
- Suite completa: 203 failed / 1221 passed.
- Arreglados: 11 tests unicos (214 -> 203).
- Regresiones reales: 0.

**Baseline de tests:**
- Inicial (con cascada rota): 245
- Tras fix cascada: 244
- Tras pip install bs4: 214 (-30)
- Tras fix quota_manager: 203 (-11)
- Total arreglados: 41

**Siguiente:** bugs reales de codigo.
- UnboundLocalError: os (phase_a_content.py:673) - ~14 tests
- datetime naive/aware (phase_b/orchestrator.py:2080) - ~14 tests
- Typo _watchlist_author_at_cap - ~7 tests
- Spend methods en ModelCascade (Fase 5) - 8 tests

---

## Fix test_phase_a_research.py — CERRADO

**Cerrado:** 2026-09-13

**Bugs/fixes aplicados:**
1. UnboundLocalError en choose_topic: eliminado `import os` duplicado en el branch niche_technical que creaba sombra de variable local.
2. Mock cascade: helper `_mock_cascade()` configura TIER_MAPPING y _last_usage reales (AsyncMock los creaba como coroutines).
3. Test pacing: reescrito con monkeypatch de PACING_MIN_HOURS=2. v5.3 lo puso a 0 (sin limite) por decision, pero el mecanismo sigue vivo. El test ahora verifica el MECANISMO, no la politica actual.
4. Test prompt: reescrito para verificar la estructura nueva (tension -> mechanism+intervention -> question/assertion). El prompt anterior tenia PROBLEM/PROPOSAL/RESEARCH QUESTION, sustituidos por lenguaje nuevo.

**Backups:**
- phase_a_content.py.20260913_102151.bak (UnboundLocal fix)
- test_phase_a_research.py.20260913_103916.bak (mock fix base)
- test_phase_a_research.py.20260913_104000.bak (mock fix definitivo)
- test_phase_a_research.py.20260913_105918.bak (pacing + prompt fix)

**Verificacion:** test_phase_a_research.py: 60/60 PASS.

**Siguiente:** corrida completa para baseline actualizado. Luego siguiente grupo.

---

## Fase 5 — DeepSeek spend guard + payload — CERRADA

**Cerrada:** 2026-09-13

**Implementado en model_cascade.py:**
- `_is_deepseek_direct(provider)`: static, excluye URLs con opencode.ai o /zen/.
- `_deepseek_spend_limit()`: lee DEEPSEEK_SPEND_LIMIT_USD, default 0.50.
- `_get_deepseek_spend()`: lee tracker, reset implicito si fecha != hoy UTC.
- `_record_deepseek_spend(provider, in, out)`: acumula coste con precios PEAK como cota.
- `_call_provider_once()`: sync — guard + HTTP + record. Guard bloquea si gasto >= cap SIN tocar la API.
- `_call_provider()`: async wrapper que ejecuta _call_provider_once via to_thread.
- Payload DeepSeek: anade `thinking: {type: disabled}` y floor max_tokens a 2048.

**Bug encontrado y arreglado durante la implementacion:**
- Habia una SEGUNDA definicion de `_is_deepseek_direct` (linea 849) que sobrescribia la nueva. Eliminada.
- `_call_provider_once` usaba `resp.status_code != 200`; los tests usan mock sin status_code. Cambiado a `raise_for_status()` con fallback a `text`.

**Efecto:**
- test_deepseek_spend_guard.py: 5/5 PASS.
- test_model_cascade.py: 16 -> 12 fails (4 payloads arreglados).

**Hashes:**
- v0 (pre-fase5): B248D432BF774F7D8ACE3B755B6D2D90
- v1 (post-fase5): 1E3C6F036FD7CF39B5647C06E5DFDF1D
- v2 (post-fix duplicado): (ver backup .fase5fix.*)
- Backups: %USERPROFILE%\backups\comet-riobamba\model_cascade.py.fase5.* y .fase5fix.*

**Pendiente Fase 5b (si se quiere):**
- Exponer el gasto actual via Telegram (/spend ya lee tracker).
- Test end-to-end: hacer una llamada real y verificar que se acumula.
- Configurar DEEPSEEK_SPEND_LIMIT_USD=0.50 (o el valor decidido) en .env.

---

## Fix contaminacion Telegram en tests — CERRADA

**Cerrada:** 2026-09-13

**Sintoma:** Cada corrida de pytest enviaba alertas REALES a Telegram
(test_provider, prov_a). El operador recibia mensajes del "Model Cascade"
aunque el agente NO estaba corriendo.

**Causa raiz:**
- `model_cascade._alert_circuit_open` -> `notify_model_event` -> `TelegramClient` real.
- `notify_model_event` esta importado DIRECTAMENTE en model_cascade.py:24,
  asi que parchear en model_status_telegram no lo alcanza.
- `TelegramClient` se instancia directo en model_status_telegram:36,
  no hay factory que interceptar.
- Singleton `_model_status_telegram` persiste entre tests si no se resetea.

**Fix:** `tests/conftest.py` con fixture autouse que:
1. Parchea `services.telegram_client.TelegramClient` con un _NoOpTelegramClient.
2. Parchea `mc.notify_model_event` en la referencia LOCAL de model_cascade.
3. Resetea `mst._model_status_telegram` a None para forzar reinstancia.

**Verificacion:**
- Ledger Telegram: 6557 -> 6557 (0 mensajes nuevos al correr 2 tests que antes enviaban).
- test_phase_a_research.py: 60/60 PASS (sin regresion).

**Efecto colateral benigno:** los tests siguen disparando el codigo pero ahora
el envio es no-op. La cobertura no cambia.

**Backup:** %USERPROFILE%\backups\comet-riobamba\conftest.py.v3.20260913_153434.bak

---

## Fix datetime naive/aware (orchestrator.py) — CERRADO

**Cerrado:** 2026-09-13

**Bug:** _execute_thread_followups comparaba ts_dt (naive, de
datetime.fromisoformat) contra cutoff (aware, UTC). TypeError en cada
ciclo real (observado en produccion 10/09/2026 8:40) y en 14 tests.

**Fix:** 3 lineas tras el fromisoformat:
    if ts_dt is not None and ts_dt.tzinfo is None:
        ts_dt = ts_dt.replace(tzinfo=timezone.utc)

**Efecto:**
- test_phase_b_thread_followups.py: 14 -> 2 fails (-12)
- test_phase_a_research.py: 60/60 sin regresion
- Ledger Telegram: 6557 sin cambios

**Backups:**
- orchestrator.py.dtfix3.20260913_153813.bak (version buena)
- orchestrator.py.dtfix2.20260913_153737.bak

**Leccion de proceso:**
Los bloques de reemplazo con regex (?s) y \s+ pueden capturar indentacion
adyacente incorrectamente. Para cambios de menos de 5 lineas: reemplazo
literal de 1 linea + verificacion count==1 antes de tocar. Probado 3 veces
en la misma sesion. La regla queda.

**Siguiente:** los 2 fails restantes de thread_followups (dedup + antidogpile)
y los archivos phase_b hermanos (dedup_limits, anti_dogpile) con sus causas
propias.

---

## Aislamiento de estado persistente en tests — CERRADO

**Cerrado:** 2026-09-13

**Sintoma:** test_phase_b_thread_followups.py fallaba de forma NO determinista
(2 fails en una corrida, 8 en la siguiente, segun estado residual en data/*.json).

**Causa raiz:** La fixture _iso del archivo redirigia 4 paths, pero faltaban
2 de reply_cap:
- _TOTAL_REPLIES_PER_POST_PATH  (culpable directo)
- _UNREPLIABLE_IDS_PATH
Los tests leian data/total_replies_per_post.json real (20KB con entradas
del agente) y veian el post de prueba con 6/6 replies -> skip.

Y 13 archivos test_phase_b_*.py tenian el mismo problema sin resolver.

**Fix:** tests/conftest.py v4 con fixture autouse `_isolate_persistent_state`
que redirige a tmp_path:
- reply_cap: los 5 paths (replies_per_post, followups_per_post,
  replied_comment_ids_durable, total_replies_per_post, unrepliable_ids).
- dedup_store: comet_dedup.db.
- conversation_state: conversations.json.

**Efecto:**
- test_phase_b_thread_followups.py: 8 fails -> 22/22 PASS, dos corridas identicas.
- test_phase_a_research.py: 60/60 sin regresion.
- Ledger Telegram: sin cambios.

**Leccion:** los tests que persisten estado deben aislar TODOS los paths.
El aislamiento parcial es peor que no tener aislamiento: genera falsos
positivos que enmascaran el estado real.

**Backup:** %USERPROFILE%\backups\comet-riobamba\conftest.py.v4.20260913_154840.bak

---

## Conftest v5 (Telegram + aislamiento) — CERRADO

**Cerrado:** 2026-09-13

**Contexto:** conftest v4 introdujo 28 errors en test_telegram_integration.py
porque parcheaba TelegramClient globalmente, y el fixture autouse de ese
archivo (que setea LEDGER_FILE) explotaba con AttributeError.

**Fix v5:** retirada la capa que parcheaba la clase TelegramClient. Las 2
capas restantes cubren la contaminacion real:
1. mc.notify_model_event -> None (referencia local, linea 24).
2. Reset singleton ModelStatusTelegram.

Los tests de integracion de Telegram usan la clase real + patch de
requests.post. Funcionan y mantienen su aislamiento de ledger propio.

**Efecto:**
- test_telegram_integration.py: 28 errors -> 28/28 PASS.
- test_phase_b_thread_followups.py: 22/22 PASS.
- Ledger Telegram: 6557 sin cambios.

**Backup:** conftest.py.v5.20260913_161650.bak

---

## Fixes 2026-09-13 (tarde)

### watchlist_cap predicate — CERRADO
Bug: tests esperaban `_watchlist_author_at_cap` (predicado puro, sin
side effects). El codigo solo tenia `_check_increment_watchlist_cap`
(check + incremento). El predicado puro se perdio en un refactor.

Fix: añadido `_watchlist_author_at_cap(author) -> bool` en orchestrator.py
junto al metodo existente. 5 lineas.

Efecto: test_watchlist_cap_fallthrough.py 7 fails -> 9/9 PASS.

Backup: orchestrator.py.wlcap.20260913_162823.bak

### Fantasma test_template_fatigue_gate.py — ARCHIVADO (2do intento)
Reaparece automaticamente (mtime 13/9 7:27:44, untracked). Movido a
_audit_trash/tests_removed_20260913_ghost/. Causa raiz desconocida (posible
sync de OneDrive/FileHistory o script externo). Si vuelve, mirar proceso
que lo restaura.

Backup: test_template_fatigue_gate.py.removed.20260913_162823.bak

---

## A.3 test_model_cascade.py — CERRADO

**Cerrado:** 2026-09-14

**Fixes aplicados a services/model_cascade.py:**

1. Bug de produccion real: `random.uniform` en el jitter del backoff sin
   `import random`. Si el agente caia en ese path, crasheaba. Añadido el
   import (1 linea).

2. `_infer_caller` devolvia "unknown" para cualquier caller que no fuera
   phase_a/phase_b/phase_c/run_cycle/run_phase. Reescrito para caer al
   nombre del modulo del primer frame externo. 3 tests arreglados.

3. `_append_telemetry_jsonl` tragaba excepciones silenciosamente. Ahora
   emite WARNING ("failed to write telemetry"). 1 test arreglado.

4. `ordered_providers` ordenaba por `(paid, name)` — alfabeticamente.
   Cambiado a `(paid, index_of_registration)` para preservar orden de
   registro. 2 tests arreglados.

5. `_get_health_score` / `_update_health`: deque(maxlen=100) -> maxlen=10.
   2 tests arreglados (rolling window).

6. `get_provider_health` leia circuit_breakers (siempre 1.0 por defecto).
   Ahora usa `_get_health_score` (ratio rolling de exito). 1 test.

**Tests archivados (obsoletos por diseño):**
- `test_fallback_content_openrouter_then_cloudflare` (tier_premium obsoleto).
- `test_circuit_alert_cooldown_suppresses_spam` (API _circuit_alert_cooldown_minutes eliminada; ahora usa notify_model_event).
- `test_alert_circuit_open_sends_alert_with_provider_name` (idem).

**Efecto:** test_model_cascade.py 12 fails -> 0/66 PASS.

**Backups relevantes:**
- model_cascade.py.importrandom2.*.bak
- model_cascade.py.infercaller3.*.bak
- model_cascade.py.maxlen.*.bak
- model_cascade.py.a3fix4.*.bak (sort)
- model_cascade.py.a3fix5.*.bak (get_provider_health)
- test_model_cascade.py.archive.*.bak (tests archivados)

**Lecciones de proceso (repetidas hoy):**
- `[System.IO.File]::ReadAllLines` requiere path ABSOLUTO en PowerShell.
  Con path relativo, resuelve contra C:\WINDOWS\system32.
- `return` dentro de bloque pegado en consola NO detiene la ejecucion.
- Para cambios <5 lineas: reemplazo literal de 1 linea, no bloques.
- Verificar hash antes Y despues de cada escritura.

---

## Fixes 2026-09-14 (noche)

### test_own_incident_source — CERRADO (7 fails -> 0)
- _mock_cascade helper (AsyncMock con TIER_MAPPING y _last_usage reales).
  Mismo patron que test_phase_a_research: sin esto, Phase A rompia con
  "'coroutine' object has no attribute 'get'".
- test_core_principles_require_calibratable_thresholds: verifica el CONCEPTO
  ("starting point" + "calibrate") en vez de strings literales obsoletos.

### degraded_mode_cooldown — CERRADO (7 tests, feature implementada)
Feature util: alertas Telegram de cascada LLM agotada con cooldown
configurable (DEGRADED_ALERT_COOLDOWN_MINUTES, default 30).

Implementado en services/model_cascade.py:
- __init__: carga since_ts y last_alert_ts del state persistido.
- _degraded_alert_cooldown_minutes(): lee env, default 30.
- _enter_degraded_mode(): 
    * Primera entrada: 1 alerta inmediata, guarda since_ts + last_alert_ts.
    * Dentro del cooldown: NO alerta.
    * Tras el cooldown: re-alerta con minutos transcurridos.
    * Fallo de send_alert: last_alert_ts NO avanza (reintenta antes).
- _save_degraded_state(): persiste is_degraded + since_ts + last_alert_ts.
- _clear_degraded_state(): escribe state con None (antes borraba el fichero,
  lo que impedia que el state limpio viajara a disco).

Efecto: test_degraded_mode_cooldown.py 7/7 PASS.
Backup: model_cascade.py.degraded.20260914_202612.bak

**Leccion de proceso (repetida N veces hoy):**
Para PowerShell + edicion de codigo Python con CRLF, usar SIEMPRE la
tecnica por lineas:
    $lines = [System.IO.File]::ReadAllLines($absPath)  # path ABSOLUTO
    ... modificar $lines ...
    [System.IO.File]::WriteAllText($absPath, ($lines -join "`r`n"), ...)
Los here-strings y .Contains() fallan silenciosamente por CRLF vs LF.

---

## Fixes 2026-09-14 (noche-2)

### quality_governor: text_has_reasoning_leak unificado a bool + patrones ampliados

Bug 1 (contrato): la funcion devolvia tupla (bool, str) al detectar y bool
al no detectar. Los consumidores solo usaban truthiness, los tests
esperaban bool siempre. Firma unificada a bool.

Bug 2 (patrones): faltaban 6 patrones reales de fuga. Añadidos:
- Labels estructurados: TITLE: / **Role**: / Structure: / Core principles:
- Paragraph N (X): con parentesis
- "Here's a thinking process" en body (no solo en title)
- Instrucciones narrativas: "We need to respond to/reply/produce a/
  acknowledge/address the specific"
- Variantes español: "Necesitamos responder", "Debemos reconocer puntos"
- Persona directives: "Must be in X mode", "as an engineer, addressing"
- Separador HR (---) y flechas de scaffold (A -> B -> C)

**Archivos cerrados con este fix (15 tests):**
- test_leak_gate_titles.py: 6 -> 0
- test_quality_governor_gate.py: 5 -> 0
- test_instruction_echo_leak.py: 4 -> 0

Backup: quality_governor.py.patterns.20260914_203649.bak

**Nota:** el fix anterior (boolfix) ya movio 4 tests pero dejo 7 con patrones
faltantes. La expansion v2 cierra el grupo.

---

## Fixes 2026-09-14 (noche-3)

### quality_bestof: _mock_cascade helper (mismo patrón)
9/9 PASS. 4 fails -> 0.

### fast_lane_watchlist: _post_age_minutes helper (nuevo)
Feature pequeña. Helper `_post_age_minutes(post)` añadido a PhaseB:
acepta created_at o published_at, soporta Z y naive, devuelve minutos o None.
5/5 PASS. 4 fails -> 0.

### classify_tier: 3 tests archivados (feature deepseek-only)
Prueban que "classify NO va a Anthropic" — Anthropic ya no existe.
Archivados a _audit_trash/tests_pending_deepseek_only_*.

### openrouter2: 3 tests archivados (feature openrouter_2 + zen bucket)
Features eliminadas en la migración a DeepSeek-only.

### outbox_unrepliable: aislamiento DB (mismo patrón que comment_outbox_retry)
Fixture autouse con monkeypatch de sp.DB_PATH a tmp_path. 19/19 PASS.
3 fails -> 0.

**Backups:**
- test_quality_bestof.py.20260914_205149.bak
- orchestrator.py.postage.20260914_205428.bak
- test_classify_tier.py.v2.20260914_205733.bak (original)
- test_openrouter2.py.20260914_205638.bak (original)
- test_outbox_unrepliable.py.v2.20260914_210106.bak

**Pendiente proxima sesion:**
- test_queue_value_turns (3): decisiones de diseño (watchlist cap default 5 vs 3,
  semantic filter). Requiere conversacion.
- test_budget_protection (2): Anthropic en el test, obsoleto.
- test_flash_only_guard (2): mapping de providers cambio.
- Grupos restantes de 2 y 1.

---

## Fix UnboundLocalError random en choose_topic (produccion)

Bug real: `import random` interno en la rama niche_technical de `choose_topic`
sombraba la variable en TODA la funcion. Cuando corria el path research
(lineas 756/758), random estaba sin asignar -> UnboundLocalError.

Mismo patron que el `import os` fixeado antes en la misma funcion. Leccion:
no hacer imports dentro de ramas condicionales.

Fix: eliminado el `import random` interno (linea 659). Modulo ya importa
random a nivel top (linea 18).

Efecto: test_topic_performance.py 1 fail -> 7/7 PASS.
        test_phase_a_research.py 60/60 sin regresion.
Backup: phase_a_content.py.randomsombra.20260914_211352.bak

---

## Fixes 2026-09-14 (cierre de sesion)

### core_logic: asserts v5.x
- max_comments_per_day, max_comments_per_post, max_replies_per_cycle
  ahora se verifican como None (v5.x = sin limite).
- 82/82 PASS.

### prompt_injection_abstain: _mock_cascade helper
- 21/21 PASS.

### topic_performance: bug produccion UnboundLocalError random
- Mismo patron que import os: `import random` interno en rama niche_technical
  sombreaba la variable en toda la funcion choose_topic.
- 7/7 PASS.

### phase_b_frontier: quality -> tier_pro
- Decision de diseno: content premium = tier_pro (V4 Pro primary), no fallback.
- 23/23 PASS.

### queue_value_turns: watchlist cap default 5
- Decision de diseno: default 5 (era 3).
- Test actualizado.

### phase_b_anti_dogpile: record_interaction acepta path
- services/interlocutors.py: firma ampliada con path opcional.
- 2 tests actualizados para pasar path=tmp_path.
- 8/8 PASS.

**Backups de la sesion:**
- model_cascade.py.quality3.20260914_212723.bak
- phase_a_content.py.randomsombra.20260914_211352.bak
- test_core_logic.py.v2.20260914_211946.bak
- test_prompt_injection_abstain.py.20260914_211758.bak
- test_phase_b_frontier.py.20260914_212923.bak
- test_queue_value_turns.py.v2.20260914_212723.bak
- interlocutors.py.20260914_213231.bak
- test_phase_b_anti_dogpile.py.v2.20260914_*.bak

**Pendientes proxima sesion (5 fails, causas unicas cada uno):**
1. test_phase6_error_boundary: phase_b_errors no se incrementa.
2. test_phase_b_dedup_limits: feed no corre tras own (razon desconocida).
3. test_critique_rewrite_leak: gate anti-leak en rewrite no preserva draft.
4. test_queue_value_turns::semantic (x2): filtros semanticos no dejan pasar.
5. test_phase_c_analytics: energy_intel no salta sin telegram.

**TODOS son investigacion individual, sin causa compartida.**

---

## Conftest v7: bloqueo de envios directos de Phase A — CERRADO

**Cerrado:** 2026-09-15

**Contexto:** Ledger Telegram subio de 6557 a 6594 (+37) durante la sesion del
14/09. Los mensajes eran "POST GENERADO (Phase A)" con temas de tests
(fixtures de test_own_incident_source, test_quality_bestof). NO fue el agente.
agent.log parado desde 10/09 8:40, tracker DeepSeek congelado en 6/09.

Causa: conftest v5 retiro la capa que parcheaba TelegramClient (para no
romper test_telegram_integration). phase_a_content envia POST GENERADO
directamente via TelegramClient.send_message, sin pasar por notify_model_event.
Ese era el hueco.

**Fix v6→v7:**
- v6: parcheo TelegramClient.send_message a no-op. Rompio 1 test de
  test_telegram_integration (necesita el metodo real con requests.post mockeado).
- v7: marker @pytest.mark.allow_telegram. Si el test lo lleva, no se bloquea.
  pytest.ini registra el marker. test_telegram_integration.py lleva
  pytestmark = pytest.mark.allow_telegram.

**Verificacion:**
- test_own_incident_source.py: 53/53 PASS, ledger delta 0.
- test_telegram_integration.py: 28/28 PASS, ledger delta 0.
- Delta total en ambas corridas: 0.

**Backups:**
- conftest.py.v7.20260915_084102.bak
- test_telegram_integration.py.20260915_084102.bak

**Nota:** el ledger no se puede limpiar (Telegram no lo permite). Los 37
mensajes son historico. A partir de ahora la suite es limpia.

---

## Fixes 2026-09-15

### conftest v7: bloqueo de envios directos de Phase A
Marker @pytest.mark.allow_telegram opt-in. test_telegram_integration lo usa.
Ledger delta 0 verificado en test_own_incident_source y test_telegram_integration.

### phase6_error_boundary: test_metrics_incremented dispara errores
El archivo esta disenado para correr como script. Bajo pytest cada test corre
aislado. El test ahora dispara los dos errores antes de snapshot. 3/3 PASS.

### phase_c_analytics: test_energy_intel_runs_ingest_without_telegram
El diseno cambio: ingest y bridge a research_agenda corren SIEMPRE; solo las
alertas Telegram dependen del toggle. Test renombrado y reescrito al diseno
v5.x. 9/9 PASS.

### critique_rewrite_leak: guard anti-prompt-leak en rewrite
services/quality_governor.text_has_reasoning_leak ahora detecta
"we need to rewrite the draft". En _critique_quality_draft, si el rewrite
trae leak, se conserva el borrador original. 3/3 PASS.

### queue_value_turns: timestamps relativos
Los tests usaban fechas fijas (2026-08-25) que envejecian y caian del age
gate de 7 dias. Añadido helper _iso_ago + variables FRESH_TS/STALE_TS/RECENT_TS
relativas a now(). 23/23 PASS.

**Backups:**
- quality_governor.py.v3.20260915_110137.bak
- test_queue_value_turns.py.v3.20260915_110137.bak
- test_phase6_error_boundary.py.20260915_084337.bak
- test_phase_c_analytics.py.20260915_084337.bak
- conftest.py.v7.20260915_084102.bak
- test_telegram_integration.py.20260915_084102.bak

---

## Fix test_zen_deepseek_wiring: determinista en hora valle

Bug: el test asumia hora PICO siempre. Fallaba si corria en hora valle
porque _estimate_cost_usd aplica 50% descuento a tier_fallback/tier_pro.
5.28 (pico) vs 2.64 (valle) -> mismatch.

Fix: monkeypatch de _is_deepseek_peak_hour a True. El test verifica lo que
promete (cotizacion por provider_name) sin depender de la hora UTC.

Verificacion: valle=2.64, pico=5.28 (ambos correctos). 3/3 PASS.
Backup: test_zen_deepseek_wiring.py.v2.20260915_111413.bak

---
## 2026-09-15 — Incidente: falso positivo de create_post sobre contenido trivial

**Síntoma**: 6 filas T/B en outbox (ids 3-8). Al arrancar el agente,
_retry_outbox() reportó "post publicado exitosamente (ID:
09a927cf-6dc0-4d2a-94c9-29124a8c6e52)" dos veces (12:12:01 y 12:17:01),
marcando las filas como published.

**Investigación**:
- GET /posts/09a927cf-...: pertenece a SparkLabScout (author_id
  63e9d98a-...), post creado 2026-05-10 con title="t", content="b".
  updated_at == created_at (nunca modificado).
- Scan de 1000 posts de la feed: 0 hits con T/B de nuestro autor.
- Nuestro agent_id: ed0f783b-4867-4d6b-b235-d481e582ff41
  (endpoint válido: GET /agents/me/posts).

**Causa raíz**: Moltbook deduplica server-side por contenido. POST con
{"title": "T", "body": "B"} devuelve 201 con el UUID de un post
existente ajeno. El cliente no detecta que el author_id de la respuesta
no es el nuestro, y marca el outbox como published.

**Impacto**:
- Real: NINGUNO. No se publicó ningún T/B en Moltbook.
- Lógico: 2 filas mentirosas en outbox (ya purgadas).
- Futuro: si algún test filtra contenido trivial al outbox real, se
  repetirá el falso positivo.

**Fix futuro (no bloqueante)**: en create_post(), tras un 201,
comparar data["post"]["author"]["id"] con self.author_id. Si difieren,
marcar needs_reconciliation en lugar de published. Añadir test.

**Pendientes relacionados**:
- Sin lock entre create_post y mark_outbox en _retry_outbox: una SIGINT
  en la ventana deja post real sin marcar → posible duplicado al
  reiniciar. Bajo impacto (ventana ~100ms) pero real.
- SIGINT no interrumpe el ciclo en curso. _run_cycle corre completo.
- deepseek_balance check falla con "no API key configured
  (MODEL_TIER_OPUS_API_KEY)". Verificar que el spend guard funcione
  por contador aunque el saldo real no esté disponible.

---

## 2026-09-16 — Hito: primer post verificado en Moltbook desde 9/9

### Contexto
El challenge solver de Moltbook estaba roto: el parser nativo regex
matcheaba dígitos sueltos en texto ofuscado, producía respuestas
incorrectas, consumía el challenge, y el retry LLM recibía 409.
Resultado: 7 días sin posts visibles (último verificado: 9/9, id 9243e144).

### Fixes aplicados hoy
1. Challenge solver reescrito (services/challenge_solver.py):
   - LLM primero (sabe leer ofuscación).
   - Fallback nativo solo si texto NO está ofuscado.
   - Submit único, sin reintento tras 400 (challenge single-use).
   - 7 tests nuevos en tests/test_challenge_solver_fix.py.
2. SIGINT cooperativo en _run_cycle (core/agent.py):
   - 4 chequeos de shutdown_requested entre sub-fases.
   - Cancelación limpia de phase_b_task.
   - state.save() siempre se ejecuta (idempotente).
3. tzdata + fallback endurecido:
   - requirements.txt: tzdata>=2026.4.
   - phase_a_content.py y orchestrator.py: fallback a timedelta(hours=-5).
4. Aislamiento de tests (tests/conftest.py):
   - Nueva fixture _isolate_hours vacía quiet/post/comment_hours.
5. Bug Telegram 2º cliente (services/model_status_telegram.py):
   - Usa create_telegram_client() en vez de TelegramClient() directo.

### Validación E2E
- Post 859183a0 (topic=hallucination detection in tool outputs).
- challenge_text: "A lobster exerts twenty five nootons with one claw..."
- LLM extrajo "25 + 12", calculó 37.00.
- submit_verification: status=200, verification_status=verified.
- 4 comentarios en la primera hora (post visible al feed público).

### Bugs residuales (no bloqueantes)
- Telegram interno: mensajes con "chat not found" intermitente.
  Los mensajes al usuario sí llegan. Causa sin identificar (¿2º cliente?).
- zoneinfo no importado en phase_a_content.py: siempre cae al fallback.
  Funciona correctamente por casualidad, pero hay que añadir el import.
- SQL error: NOT NULL constraint failed: comment_actions.post_id en
  karma_roi_tracker. No bloquea operación.
- database is locked: concurrencia en karma_roi_tracker con Phase B.
- Phase B en quiet hours procesa 596 candidatos sin cap.
  Recomendación: añadir caps en .env para phase_b_max_own_comments_per_cycle.
- own_post_store cambió de fuente (published_posts.json vs own_post_ids.json).
  Investigar por qué.
- SIGINT durante Phase B no aborta la iteración en curso.
  Solo entre sub-fases. Para fix completo hay que añadir chequeo en el loop.

---

## 2026-09-16 (tarde) — Bug Telegram: chat_id=12345 filtrado desde tests

### Síntoma
20-30 mensajes "chat not found" por test, cada ~7s, sin parar. Un solo
ciclo generaba 15 errores. Rate limit global de Telegram (aplicado
antes) no los detenía porque el problema no era volumen.

### Causa raíz
tests/test_telegram_integration.py usa `chat_id="12345"` como valor
falso. Cuando ese test falla (usa @pytest.mark.allow_telegram y mockea
requests), _queue_outbox() guarda la entrada en el outbox real
(data/telegram_outbox.json). El agente, al arrancar y en cada iteración
de retry_outbox(), la reintenta → chat not found → la re-encola → loop
infinito. Mismo patrón que el bug T/B de Moltbook del 15/09.

### Fix aplicado
1. `data/telegram_outbox.json` vaciado (`[]`).
2. `tests/conftest.py`: nueva fixture `_isolate_telegram_outbox`
   (autouse) que redirige OUTBOX_FILE a tmp_path.
3. `services/telegram_client.py`: rate limit global de clase
   (`_global_send_window`, `_global_send_lock`,
   `_global_max_per_min = 15`). Aplicado en `_send` tras el guard
   `if not self.enabled`. Cubre TODAS las instancias futuras.
4. `services/model_status_telegram.py`: rate limit adicional
   (5/min global) + uso de `create_telegram_client()` en vez de
   `TelegramClient()` directo.
5. `services/model_cascade.py`: silenciados los eventos
   `_on_circuit_half_open` y `_on_circuit_close` (eran ruido).

### Verificación
- Suite: 1397/0 (antes y después).
- Test 90s: 0 `chat not found` (antes: 15).
- Outbox post-test: `[]` (antes: `[{"chat_id":"12345",...}]`).
- Mensajes importantes al usuario: 100% (prueba conexión, POST
  GENERADO, Engagement spike, Agente detenido).
- Ctrl+C: <30s, limpio.

### Bugs residuales identificados
- Traceback cosmético `asyncio.CancelledError` en shutdown (de
  `asyncio.to_thread` en `_call_provider`). Proceso muere bien,
  solo imprime feo. No urgente.
- `SQL error: NOT NULL constraint failed: comment_actions.post_id`
  en `services/karma_roi_tracker.py`. 2 veces hoy.
- `SQL error: database is locked` en el mismo tracker. Concurrencia
  con Phase B en background.

### Regla aprendida
Cualquier archivo de estado persistente escrito por el agente en
producción DEBE estar aislado en conftest.py. Revisar periódicamente
data/*.json para detectar valores placeholder (T/B, 12345, test-*).

---

## 2026-09-16 (tarde) — Bloque SQL: 7 bugs en karma_roi_tracker

### Síntoma
En cada ciclo: 2-3 "SQL error insertando comment_action: NOT NULL
constraint failed: comment_actions.post_id" + "database is locked"
intermitente. Los intentos de Phase A rechazados por quality gate no
se trackeaban correctamente. Los tests escribían fixtures en la DB
de producción (post_id=top-12345678-*, comment_id=c1/c2/new).

### Bugs encontrados (7)
1. **_get_conn con conexión huérfana** (líneas 82-83):
   `c = sqlite3.connect(...)` + `c.row_factory = sqlite3.Row` nunca
   se usaban. Cada llamada dejaba una conexión abierta → "database
   is locked" con concurrencia de Phase B.
2. **post_id=None en post rechazado** (línea 221): schema exige
   `post_id NOT NULL`, el branch de posts no tenía fallback.
3. **status hardcoded** (línea 261): el dict sqlite_entry usaba
   `"status": "published"` ignorando el parámetro status recibido.
4. **action_type="post_rejected" sin status** (phase_a_content:2044):
   el caller no pasaba status="rejected", caía al default.
5. **Filas de test en DB real**: test_queue_value_turns,
   test_credibility_gates escribían a data/karma_roi.db.
6. **karma_roi.db no aislada en conftest**: no había fixture para
   redirigir DB_PATH a tmp_path.
7. **test_karma_roi_tracker.py con paths hardcodeados**: usaba
   "data/karma_roi.db" y os.path.join("data", "karma_roi_tracker.jsonl")
   que no respetaban el monkeypatch.

### Fix aplicado
- services/karma_roi_tracker.py:
  * _get_conn() simplificado (una conexión, WAL, busy_timeout).
  * Fallback `pending-post-{ms}` si no hay moltbook_id.
  * status: str = None por defecto + inferencia por sufijo del
    action_type (_rejected → rejected, _duplicate → duplicate,
    _failed → failed).
- tests/conftest.py:
  * Nueva fixture _isolate_karma_roi_db (DB_PATH + JSONL_PATH +
    KARMA_TRACKER_FILE a tmp_path).
- tests/test_karma_roi_tracker.py:
  * import services.karma_roi_tracker as krt.
  * 10 reemplazos de paths hardcodeados (data/karma_roi.db,
    data/karma_roi_tracker.jsonl, os.path.join...).
- data/karma_roi.db: filas de test borradas (4).

### Verificación
- Suite: 1397/0.
- Test 60s tras fix: 0 SQL errors (antes: 2-3 por ciclo).
- DB real intacta tras la suite (hash + mtime idénticos).
- 3 tests unitarios nuevos OK: post_rejected→rejected,
  comment→published, comment_rejected→rejected.

### Regla general consolidada
**Cualquier archivo de estado persistente escrito por el agente
en producción DEBE tener fixture de aislamiento en conftest.py.**
Bugs por violación de esta regla hasta ahora:
- T/B de Moltbook (2026-09-15) → data/comet_state.db.
- chat_id=12345 Telegram (2026-09-16 AM) → data/telegram_outbox.json.
- top-12345... karma_roi (2026-09-16 PM) → data/karma_roi.db.
Chequeo periódico: `git grep -E "top-|test_|12345|pending-post-" data/`
para detectar contaminación.

---

## 2026-09-16 (tarde) — Cierre del bloque SQL + contaminacion

### Bugs resueltos (7)
1. _get_conn con conexion huerfana (services/karma_roi_tracker.py).
2. post_id=None en post rechazado (schema exige NOT NULL).
3. status hardcoded a "published" en dict sqlite_entry.
4. action_type="post_rejected" sin status en caller.
5. Fixtures de tests filtrandose a data/karma_roi.db.
6. karma_roi.db sin aislamiento en conftest.
7. test_karma_roi_tracker.py con paths hardcodeados.

### Fixes aplicados
- services/karma_roi_tracker.py:
  * _get_conn simplificado (sin conexion huerfana).
  * post_id fallback a pending-post-<ms> si no hay moltbook_id.
  * status=None por defecto + inferencia por sufijo del action_type.
- tests/conftest.py:
  * _isolate_karma_roi_db (DB_PATH + JSONL_PATH + KARMA_TRACKER_FILE).
- tests/test_karma_roi_tracker.py:
  * import krt + 10 paths reemplazados.

### Limpieza de contaminacion residual
- karma_roi_tracker.jsonl: 78 lineas eliminadas (13 legitimas).
- comment_votes.jsonl: 2 eliminadas.
- conversations.json: 1 clave eliminada.
- comet_dedup.db dedup_store: 1 fila eliminada.
- VACUUM en karma_roi.db (122880 -> 32768 bytes) y comet_dedup.db
  (1708032 -> 1331200 bytes).

### Verificacion final
- SQL directo: 0 filas con fake markers en karma_roi.db.
- Select-String en .db tras VACUUM: 0 hits.
- JSONs: 0 errores de parseo (usar utf-8-sig por BOM).
- Suite: 1397/0.
- DB real intacta tras la suite (hash + mtime identicos).

### Aprendizajes consolidados
- Regla: cualquier estado persistente escrito por el agente debe
  tener fixture de aislamiento en conftest.py. Historial de bugs:
  T/B Moltbook (comet_state.db), chat_id=12345 Telegram
  (telegram_outbox.json), top-12345 karma_roi (karma_roi.db).
- Filtrar contaminacion mirando TODOS los campos, no solo el "id"
  principal. thread_id, model, tier tambien pueden llevar fixtures.
- Select-String sobre .db da falsos positivos (paginas libres).
  Verificar por SQL (PRAGMA table_info + WHERE).
- VACUUM es necesario tras deletes masivos para recuperar espacio.

### Pendientes
- submolts_discovery.json tiene BOM UTF-8. Usar utf-8-sig en
  validadores y scripts que lo lean.
- Traceback cosmetico asyncio.CancelledError en shutdown.
- Challenge solver: reforzar prompt (caso "twenty seven + four ten"
  fallo el 16/09 con post bd927a39).
- Documentacion general: CONFIG_TRUTH.md, README.md.

---

## 2026-09-16 (noche) — Challenge solver reforzado (fix E2E validado)

### Sintoma
Challenges con numeros partidos por ofuscacion ("tW/ eNnTtYy sEeVvEeN",
"ThIr Ty TwO") fallaban en el LLM. Caso bd927a39 (2026-09-16 am):
"twenty seven + four ten" -> LLM extrajo "10 + 14" -> 400 Incorrect answer.

### Fix aplicado
- services/challenge_solver.py:
  * Prompt reforzado (22 lineas): advierte OBFUSCATED, ejemplos de
    reconstruccion de numeros-en-palabras partidos, input/output
    examples.
  * Fallback ampliado: tiers [classify, flash, pro] (antes solo
    classify y flash).
- tests/test_challenge_solver_fix.py: 4 tests nuevos (smoke tests del
  prompt).
- tests/test_classify_tier.py: assertion actualizada (3 tiers).

### Validacion E2E
Post bd65663d (2026-09-16 17:35 UTC):
  Raw: "A] lO b-StEr SwImS^ aT tW/eN tY tHrEe] cMeNtI..."
  LLM extrajo "23 - 7" = 16.00
  submit_verification status=200
  verification_status=verified

Post ebe9f9d9 (~18:35 UTC, ciclo #13):
  Similar pattern ofuscado.
  verification_status=verified

### Verificacion
- Suite: 1401/0 (7 + 4 challenge + resto).
- 4 de los ultimos 5 posts: verified (el unico failed es bd927a39
  previo al fix).
- Sin regresion en 90 min de ciclo #14 (quiet_hours activo).

### Pendientes
- Traceback cosmetico asyncio.CancelledError en shutdown. El
  proceso muere limpio, solo imprime feo. Anotado como bug #5.
- Documentacion general (CONFIG_TRUTH.md, README.md, consolidar
  operacion.md / OPERACIONES.md / RUNBOOK_AGENT.md).

---

## 2026-09-17 — Fixes A/B/C: cap Phase B, persistencia health, SIGINT blindado

Tres fixes cerrados el mismo dia, todos con verificacion empirica.

### A. Cap de Phase B — CERRADO (commit fff11fe)

**Problema:** Phase B procesaba la cola COMPLETA de comentarios sin responder
en posts propios sin limite. Con ~200 candidatos x ~3s por llamada LLM, un
ciclo tardaba 10+ minutos y gastaba sin techo (~$0.03 por corrida). Los 3
caps existian en config pero estaban en None.

**Diagnostico:**
- behavior_cfg.phase_b_own_queue_per_cycle = None -> L4029 nunca corta
- behavior_cfg.max_comment_replies_per_cycle = None -> L4051 nunca corta
- El overlay data/auto_applied_config.json {"phase_b_max_replies": 1}
  era DECORATIVO: la clave no existia en behavior_cfg ni tenia lector.
- La allowlist de config/auto_appliable.py permitia un parametro fantasma.

**Fix:**
1. .env: AGENT_PHASE_B_OWN_QUEUE_PER_CYCLE=30
   .env: AGENT_MAX_COMMENT_REPLIES_PER_CYCLE=15
2. config/auto_appliable.py: reemplazado parametro fantasma
   phase_b_max_replies por phase_b_max_own_comments_per_cycle.
3. Overlay reseteado a {}.

**Efecto medido:** Phase B acotada a 30 candidatos. Ciclos terminan.
health.json se escribe al final (antes nunca llegaba).

### B. Persistencia health.json en shutdown — CERRADO (commit 24715d2)

**Problema:** health.json solo se escribia en el path NORMAL del ciclo
(L1006, dentro del else del try/except). Si el agente recibia SIGINT durante
el sleep entre ciclos, o una excepcion cancelaba el ciclo, el archivo quedaba
con datos del ciclo anterior. Se observo cycle: 1, updated_at: <hace 46 min>
tras matar el proceso mid-Phase-B.

**Diagnostico:**
- AgentState._save() escribe data/comet_state.db (SQLite).
- _write_health_snapshot() escribe data/state/health.json.
- Dos sistemas de estado separados con writers separados.
- asyncio.CancelledError no es atrapado por except Exception (hereda de
  BaseException) -> sale de _run_cycle sin persistir.

**Fix:**
- Nuevo metodo _write_partial_health(reason) en core/agent.py.
- Llamado en 3 paths:
  1. _shutdown_watcher() tras cancelar phase_b_task.
  2. run() shutdown loop antes del mensaje Telegram final.
  3. main() finally, ultimo guardado defensivo.

**Efecto verificado:** tras Ctrl+C, health.json tiene
{partial: true, reason: "...", updated_at: <fresco>} en cada path.

### C. Blindaje handle_signal — CERRADO (commit a982d6b)

**Problema:** en la primera prueba SIGINT real (foreground + Ctrl+C), el log
cortaba en "Senal 2 recibida. Iniciando shutdown..." sin llegar a
"Shutdown solicitado..." (que esta en request_shutdown()). El handler moria
ANTES de marcar shutdown_requested.

**Diagnostico:** alguna excepcion dentro del handler (encoding de emoji,
Telegram, logging) mataba el flujo antes de setear el flag. Los 2 intentos
previos con redireccion > log.txt y Tee-Object mataban el proceso antes por
BrokenPipeError cuando PowerShell cerraba stdout al recibir Ctrl+C.

**Fix:**
1. agent.shutdown_requested = True PRIMERO, sin logging previo.
2. Cada bloque en su propio try/except (log signal, setear flag, log
   diagnostico, telegram).
3. Emoji cambiado a texto plano en el log del handler.
4. Fallback a stderr directo con FATAL si el flag no se puede setear.

**Verificacion empirica (prueba real con Start-Transcript):**
- Senal 2 recibida. Iniciando shutdown...                 [OK]
- handle_signal: shutdown_requested=True                  [OK]
- Shutdown watcher: shutdown_requested                    [OK]
- Shutdown watcher: cancelando phase_b_task               [OK]
- health.json parcial escrito (watcher)                   [OK]
- health.json parcial escrito (run)                       [OK]
- Agente detenido / Shutdown completado                   [OK]
- Sin tracebacks                                          [OK]

**health.json final:** {cycle: 19, posts_today: 4, comments_today: 5,
partial: true, reason: "main_finally", updated_at: "2026-09-17T20:16:18+00:00"}

### Pendientes documentados

- **BrokenPipeError con redirecciones PowerShell:** python run_agent.py >
  log.txt en foreground mata el proceso antes de completar shutdown porque
  PowerShell cierra el handle de stdout al recibir Ctrl+C. Workaround para
  pruebas: Start-Transcript (sin pipe). En produccion (run-prod.ps1)
  el patron es distinto y no afecta.
- **Phase A no aborta on SIGINT:** el shutdown cooperativo termina la fase
  en curso (Phase A completo publico un post verificado tras Ctrl+C). Es
  comportamiento deseable: no arrancar trabajo nuevo, no abortar el actual.

### Commits

    a982d6b  fix(agent): blindar handle_signal contra excepciones internas
    24715d2  fix(agent): persistir health.json en shutdown paths
    fff11fe  fix(phase_b): cap de candidatos y replies por ciclo

### D. Limpieza repo — FASE 5a CERRADA

**Backup:** `~\backups\comet-riobamba\fase5a_cleanup_20260917_153545.zip` (23.6 MB)

**Borrado (12 rutas, 99.5 MB liberados):**
- `_archive/` (9.6 MB, 95 files) — recursión rota 15 niveles
- `_audit_trash/` (0.5 MB, 121 files)
- `backups/` (1 MB, 11 files)
- `_logs/` (1.4 MB, 32 files)
- `_cleanup_backup/` (0 MB)
- `data/_backup_dryrun2/3/4_*` (39.4 MB)
- `data/_backup_pretest_*` (13.1 MB)
- `data/moltbook_archive/` (0.6 MB)
- `data/moltbook_full_archive/` (33.9 MB)
- `tools/legacy_launchers/` (0 MB, 9 files)

**NO borrado (justificado):**
- `docs/ein/` (3 archivos tracked + tests/servicios activos lo referencian).
  Decisión: mantener intacto. Se estudiará al final cuando se decida
  el acoplamiento de EIN con el agente en Moltbook.
- `.venv/` (243 MB): infraestructura, no se versiona.
- `data/` (50 MB): estado activo del agente.
- `logs/`, `traces/`: runtime output — limpieza selectiva queda pendiente (Fase 5b opcional).

**Tamaño repo:** 697 MB -> 597 MB.

**Verificación:** suite rápida 119/119 OK (incluye tests EIN).

### E. Limpieza logs/traces — FASE 5b CERRADA

**Backup:** ~\backups\comet-riobamba\fase5b_cleanup_20260917_160558.zip (23.3 MB)

**Borrado (342 archivos, 264.4 MB):**
- logs/ (261 archivos, 233.1 MB): V63_*, V59_*, agent.log.1-5, comet_2026-05-21.*, REAL_*, OWNINCIDENT_*, etc.
- traces/ (81 archivos, 31.3 MB)

**Preservado:**
- logs/agent.log (activo, 7.4 MB)
- logs/fase_c_* y logs/run_obs_* (de hoy)
- monitoring/ (nada >30 días)

**Regla aplicada:** borrar archivos con LastWriteTime > 7 días,
preservando agent.log activo y cualquier archivo del día actual.

**Repo:** 597 MB -> 340 MB (acumulado del día: 697 -> 340 MB, -357 MB).

Sin commit (logs/ y traces/ están en .gitignore).

### F. Fase 4 — scripts huerfanos y .gitignore residual — CERRADA

**Hallazgo critico adicional:**
- config/niche_prompts.py -> importado por phases/phase_a_content.py:28.
  Estaba ignorado por .gitignore (entrada DUPLICADA en L174 y L205).
- patches/patch_phase_b_pre_generation_gate.py -> importado por
  phases/phase_b/orchestrator.py:137. Ignorado por .gitignore L239 ('patches/').

Ambos afectaban clone fresco (ImportError en Phase A y B).

**Fix aplicado (commit 17f9c88):**
- .gitignore: removidas 3 lineas (niche_prompts x2 + patches/).
- Trackeados: config/niche_prompts.py + patches/patch_phase_b_pre_generation_gate.py.

**Limpieza (sin commit, ignorados no versionados):**
- 51 scripts .py de iteracion borrados del disco (142.2 KB).
- Backup: ~\backups\comet-riobamba\fase4_cleanup_20260917_165215.zip

**Scripts preservados (decision):**
- scripts/ (52): utilidades CLI legitimas (audit_, recon_, smoke_test_, etc.).
- tools/ (3): comet_mcp_server.py, agent_inspect.py, comet_mcp_server_lowlevel.py.
- scripts/ops/ (7): promovidos en commit b226f2f.

**Deteccion falsa positiva:** el detector de "huerfanos" por imports dio 49
falsos positivos porque scripts CLI se invocan por linea de comandos, no por
import. Corregido el criterio: solo se consideran criticos los .py ignorados
que SI son importados por codigo tracked.

### G. Fase 2.2 — Auditoría core/ — CERRADA

**2.2.1 — Tests de `core/write_policy.py` (commit 8f54603):**
- 33 tests, cubren TokenBucket, predicados de texto, hash/idempotency,
  editorial fit, topic cooldown, decide(), log_write().
- Archivo: `tests/test_write_policy.py`.
- Resultado: 33/33 passed.

**2.2.2 — Tests de `core/value_log.py` + `core/value_review.py` (commit ddfc4dc):**
- 15 tests (8 + 7). Cubren JSONL, filtro por timestamp, línea inválida,
  summarize_events, run_value_review con mocks del LLM, JSON válido/inválido,
  markdown fence strip.
- Archivos: `tests/test_value_log.py`, `tests/test_value_review.py`.
- Resultado: 15/15 passed.

**2.2.3 — Refactor de `core/agent.py` — DIFERIDO (deuda aceptada):**
- 1262 L / 34 métodos. ~600 L son utilidades que podrían ir a submódulos
  (notificaciones, outbox retry, dashboard, health, logs, flags).
- Decisión: NO refactorizar ahora. Razones:
  - Funciona, 7 tests existentes.
  - Sin bugs reportados.
  - Refactor de 1262 L sin causa = riesgo de regresión.
  - El refactor del SHUTDOWN ya está hecho (commits 24715d2 + a982d6b).
- Candidato a Fase 2.2.3 para sesión dedicada, si aparece dolor real.

**Cobertura core/ post 2.2:**
- 10 de 13 archivos con tests.
- 3 sin tests (era 3): los dos anteriores + write_policy (cerrados).
- Sin tests: ninguno → todos los archivos de core/ tienen cobertura.
  (agent.py: 7 tests, challenge_solver: 1, claims_tracker: 1, daily_metrics: 3,
  memory_store: 1, observability: 1, self_monitor: 1, state_manager: 4,
  strategy_state: 1, tracer: 1, value_log: 8, value_review: 7, write_policy: 33)

### H. Fase 2.3 — Recalibración del quality gate de Phase B — CERRADA

**Contexto (no planificado):** durante la verificación rutinaria del agente
PID 14136 (log `nightly_run_20260917_202743.log`), se detectó una tasa de
rechazo anómala en watchlist: ~107 rechazos del gate de sustancia
(`tier=quality sin señal de sustancia`) contra ~3 replies publicadas en 24
ciclos. Spend $0.153 con output casi nulo.

**Diagnóstico (log 2026-09-17/18, sin cambios de código):**
- Drafts técnicos válidos con `evidence=False metric=False mechanism=False
  derivation=False`:
  - `"Re-scored, not requeued. The carry-over weight is a decay function..."`
  - `"Decay is the right instinct, but halving per cycle makes..."`
  - `"The distinction you want is exactly what the Linux CFS runqueue..."`
  - `"The preempted-vs-never-seen distinction is exactly what YARN's..."`
- No era anti-fabricación — era cobertura del whitelist de `mechanism_terms`
  (cubría sistemas distribuidos + ML, no scheduling / colas / performance /
  política).
- Contradicción prompt↔gate: el prompt pedía *"Avoid exact numeric thresholds"*
  mientras el gate exigía `has_metric` como escape. Los drafts obedecían al
  prompt y caían en la zona muerta.
- `has_framework` se computa (orchestrator.py:1004) pero nunca se usa en el OR
  del gate. Verificado via `git log -S`: sin historial previo (archivo
  entra a git en `705643c`), sin tests que dependan. Decisión: dejar intacto.

**Fix aplicado (commit df0dd10):**
- `mechanism_terms`: +31 términos (scheduling / colas / performance /
  política). `queue, runqueue, preempted, scheduling, starvation, fairness,
  contention, admission, backpressure, priority, weight, budget, carry-over,
  half-life, decay, amortized, overhead, hot path, cold path, critical path,
  worst case, best case, compounding, saturation, workload, policy, layer,
  ratio, trade-off, tradeoff`.
- `has_evidence`: +9 frases de análisis causal natural (`the distinction`,
  `the trade-off`, `the risk`, `at the layer`, `under load`,
  `in the worst case`, `the failure mode`, `the bottleneck`).
- `has_framework` NO se agrega al OR (verificado: no rescata drafts
  observados; introduce riesgo de relajación con vocabulario genérico).

**Verificación:**
- `tests/test_quality_gate_recalibration_20260918.py`: 10 passed, 1 skipped
  (preview truncada, no verificable — se documenta como skip explícito en vez
  de asumir resultado).
- Suite completa: `1459 passed, 1 skipped` (baseline 1449 + 10 nuevos).
- Gates anti-fabricación (`_FABRICATION_PATTERN`) y anti-histórico
  (`text_has_unverifiable_historical_claim`) intactos.
- `ast.parse` OK. Sin cambios en `scoring.py`.

**Métricas a medir en próximo ciclo (post-fix):**
- Gate A rechazos: baseline 107 / esperado < 50.
- Replies publicadas: baseline 3 / esperado > 3.
- Spend: baseline $0.153 / esperado igual o leve subida.
- Errores reales: baseline 1 (Telegram timeout) / esperado igual o menos.

**Deuda detectada, no resuelta:**
- Duplicación de `reasons` en `_score_reply_draft` (block mode + penalties
  v5.2 aplican la misma señal dos veces). Cosmético — telemetría engañosa,
  no bug funcional. Sesión aparte.
- Docstring stale en `_passes_quality_gate`: dice *"all penalties zeroed for
  testing"* (v5.1) pero penalties v5.2 están activos. Sesión aparte.
- `orchestrator.py` acumula 11 backups históricos en `phases/phase_b/`
  (~4 MB, versionados). Candidato a Fase 5c (limpieza de backups).

### H.1 — Reorganización de docs de arquitectura — PARCIAL

**Estado:** movimiento aplicado. Consolidación pendiente.

**Movimientos aplicados (2026-09-18):**
- `ARCHITECTURE.md` (raíz) → `docs/ARCHITECTURE.md`
- `ARCHITECTURE_GUIDELINES.md` (raíz) → `docs/ARCHITECTURE_GUIDELINES.md`
- `DIAGNOSTICO_AUDITORIA_2026-08-22.md` (raíz) → `docs/archive/DIAGNOSTICO_AUDITORIA_2026-08-22.md`
- Refs en `AGENTS.md` actualizadas (2 líneas).

**Raíz quedó con 3 .md:** `README.md`, `AGENTS.md`, `CHANGELOG.md`.

**Consolidación pendiente (citada de data/docs_inventory_20260911.json:264):**
> "ARCHITECTURE.md + ARCHITECTURE_GUIDELINES.md + docs/INFORME_ARQUITECTURA_v4.4.0.md
> + docs/COMET-RIOBAMBA_REFERENCE.md → 1 arquitectura canónica"

4 archivos fragmentados, ~700 líneas combinadas. La consolidación NO se
hizo durante la ventana estratégica del agente — queda para sesión dedicada.

**Fuera de alcance (untracked, no en git):** 12 .md residuales en raíz
(`CONTEXTO_*`, `reporte_analisis_psicologico_*`, `AUDITORIA_*`,
`ACTUALIZACION_*`, `DOCUMENTACION_COMPLETA_*`, `inventario_*`). No aparecen
en GitHub. Limpieza local es decisión separada.

**Mojibake detectado en varios .md** (`DOCUMENTACION_COMPLETA_COMET_RIOBAMBA.md`,
`ACTUALIZACION_KEYS_FREE_TIERS.md`, `AUDITORIA_MODELOS_FREE.md`,
`inventario_procesos_agente.md`): escritos con encoding roto (UTF-8 guardado
como CP850). No bloquea, no se arregla con git mv. Deuda separada.
**Actualización (2026-09-18 15:25):** el problema colateral de tracking en
`data/` quedó resuelto (commit `52aa1ce`): `.gitignore` cambió `data/` →
`data/*`, permitiendo excepciones. Trackeados retroactivamente
`data/editorial_policy.json` y `data/.gitkeep` (excepción que nunca
funcionaba desde su introducción). La consolidación de los 4 archivos de
arquitectura sigue pendiente.

### H.2 — Recalibración del clasificador Phase A + caps — CERRADA

**Contexto (no planificado):** durante la verificación del agente tras el
reinicio de las 10:37, se detectaron dos problemas independientes en Phase A:

1. `rejected_posts.jsonl` acumula 1296 rechazos; 271 por
   `below_min_quality_score`. El clasificador (`dual_scoring`) rechazaba
   ~76% de posts técnicos válidos.
2. Sin cap: el agente publicaba sin límite. `max_posts_per_day=None` y
   `max_posts_per_week=null`. Histórico: 3-7 posts/día (18 posts en 4 días
   vía `post_embeddings`).

**Diagnóstico del clasificador (log 2026-09-17/18):**
- 271 rechazos: 233 como `clarification` (0.3), 38 como
  `metric_proposal` (0.5). Ambos < 0.72 umbral.
- 76% de los rechazados usaban prescription pattern ("the fix is X",
  "the mechanism is Y") con named mechanism (gate, guardrail, event log,
  rolling window, checkpoint).
- 67.5% con prescription + named mechanism.
- Ejemplo rechazado: *"The mechanism is a semantic trip wire: gate on
  output schema drift, not transport..."*

**Fix commit `e34ebbe`:**
- `services/dual_scoring.py`:
  - Paso 2 (empirical): +8 patrones de incidentes reales del agente
    (`in our production`, `we had a production`, `silently became`, etc.)
  - Nuevo paso 3.5 (prescription + named mechanism): FRAMEWORK_PROPOSAL
    si prescription_signal >= 1 AND named_mechanism >= 1 AND len >= 300.
  - Paso 4 (critique + alternative): +11 patrones de lenguaje natural
    (`misunderstands`, `completely misses`, `the mechanism is`, `gate on`).
- `phases/phase_a_content.py`:
  - Import `_count_signals` desde dual_scoring.
  - `_is_substantive_post`: segunda ruta para posts densos sin pregunta
    final. Requiere >= 400 chars, >= 3 oraciones, tech_density >= 2.

**Verificación commit `e34ebbe`:**
- `tests/test_phase_a_quality_recalibration_20260918.py`: 10/10 passed.
- Suite completa: 1469 passed, 1 skipped (baseline 1459 + 10 nuevos).
- In-vitro sobre `rejected_posts.jsonl`: 204/271 = 75.3% reclasificados a
  framework/empirical/critique.

**Fix caps commits `40e94dc` + `52aa1ce`:**
- `.env` (local, no tracked): `AGENT_MAX_POSTS_PER_DAY=2`.
- `data/editorial_policy.json`: `max_posts_per_week: 10` (antes null).
- `.gitignore`: `data/` → `data/*` para permitir excepción. Trackeados:
  `data/editorial_policy.json` y `data/.gitkeep`.

**Hallazgos colaterales:**
- `AGENT_PHASE_A_PUBLISH_ENABLED`: flag huérfano. Se define en
  `config.py:93` y nunca se consulta en código de producción. Solo tests
  lo usan. Publicar NO depende de este flag.
- `editorial_mutator.py` + `save_editorial_policy()`: código muerto.
  Proponen cambios pero nunca escriben. `data/editorial_policy_history/`
  no existe.
- Excepciones `!data/.gitkeep` y `!logs/.gitkeep` en `.gitignore`: nunca
  funcionaron por la regla de "no negar dentro de directorio ignorado con
  trailing slash". El fix `data/*` las desbloquea retroactivamente.
- Outbox de posts reintenta `_retry_outbox()` al arranque sin consultar
  `PHASE_A_PUBLISH_ENABLED`. Solo respeta `max_posts_per_day`.

**Estado tras fix:**
- Agente corriendo con caps activos (PID 15636 desde 15:25).
- Phase A respeta max 2 posts/día y max 10/semana.
- Verificación pendiente: primer ciclo tras reset manual de `posts_today`
  (15:25) para observar Phase A publicar con el clasificador nuevo.

**Deuda pendiente:**
- Eliminar/reutilizar `AGENT_PHASE_A_PUBLISH_ENABLED` huérfano.
- Decidir si conectar `editorial_mutator.py` (auto-tune) o eliminarlo.
- Auditar la regla `.gitignore` para otros archivos con el mismo patrón
  (logs/, exports/, etc.) — potenciales excepciones rotas.
- `run.err` vacío durante la caída del circuit breaker de Moltbook: la
  desconexión no se registró en el log de errores. Investigar si el CB
  se recupera correctamente tras timeout.
### H.3 — Fase 2.4 (phases/) + validación empírica Phase A — CERRADA

**Contexto:** auditoría estructural del paquete `phases/` (16 archivos
activos, ~570 KB de código) + validación de los fixes de Phase A/B en
producción tras reinicio.

**2.4.1 — Cobertura por imports (completado):**
- 13 archivos activos auditados (excluyendo __init__.py y engagement/).
- 8 con import directo desde tests: responder, orchestrator, scoring,
  constants, value_log_utils, deps, phase_a_content, phase_c_analytics.
- 4 sin import directo pero con cobertura indirecta (usados por
  orchestrator.py o phase_a_content.py): classifier, tracker,
  candidate_scorer, engagement.
- **1 sin cobertura alguna: `phase_c_watchlist.py`** (417 líneas) →
  resuelto en 2.4.3.

**2.4.2 — Limpieza de backups (completado):**
- 18 archivos de backup en `phases/` (~3.4 MB total): 11 de
  orchestrator.py, 5 de phase_a_content.py, 2 de scoring.py.
- Todos untracked en git. ZIP preservado en
  `~\backups\comet-riobamba\phase_backups_20260918_154915.zip` (0.83 MB).
- Eliminados localmente. `git status` sin cambios.

**2.4.3 — Test de `phase_c_watchlist.py` (completado):**
- `tests/test_phase_c_watchlist.py`: 20 tests cubriendo 3 métodos
  testeables (`_load_watchlist`, `_score_posts`, `_quality_gate`).
- No cubre `_generate_comment` ni `run()` — requieren mock de LLM/API.
- Suite completa: 1489 passed, 1 skipped (baseline 1469 + 20).

**Hallazgo menor — mojibake en phase_c_watchlist.py:**
- 4 líneas con `¾¾¾` (UTF-8 mal decodificado) en docstrings/comentarios:
  líneas ~355, ~370, ~374, ~390. No bloquea. Deuda separada.

**Validación empírica de fixes previos (2026-09-18):**
- Ciclo 56 (15:25): Phase A publicó post ID b15b6502 (Counter-claim a
  neo_konsi_s2bw sobre admission control). `posts_today` pasó de 0 a 1.
- Ciclo 57 (15:58): Phase A publicó post ID 70e504af. `posts_today=2`
  (cap alcanzado). A partir del ciclo 58, Phase A se salta hasta medianoche.
- Ambos posts usan vocabulario del niche sin rechazos: el clasificador
  recalibrado (commit e34ebbe) funciona en producción.
- Cap acumulativo correcto: `límite diario=2, ya hoy=1, disponibles=1`
  en ciclo 57 → publicó 1 → `posts_today=2` → siguiente ciclo saltará.

**Deuda pendiente (nueva):**
- Mojibake en `phase_c_watchlist.py` (4 líneas).
- `_generate_comment` y `run()` de phase_c_watchlist sin tests (mock LLM).
- 11 backups históricos adicionales en `phases/phase_b/` fueron eliminados
  en esta sesión, pero el patrón de backup manual persiste — considerar
  `.gitignore` para `*.bak*` y `*.backup*` en `phases/`.


### H.4 — Resiliencia completa: NSSM + pausa + bug stop.flag — PARCIAL

**Estado:** NSSM operativo. Bug del stop.flag detectado, no resuelto.

**NSSM instalado (commits ba1fd86, d0af1d0, 423cfa5):**
- Servicio `CometRiobamba` corriendo como SYSTEM, StartType Automatic.
- Auto-arranque al boot, sin login.
- Auto-restart si muere (AppRestartDelay=5000).
- Logs: logs/service_stdout.log + service_stderr.log (rotacion 5 MB).
- tools/nssm.exe instalado (ignorado por .gitignore).
- Script tools/install-nssm-service.ps1 trackeado.

**Bug detectado durante la instalacion:**
- Primer intento de arrancar el servicio fallo con:
  UnicodeEncodeError: 'charmap' codec can't encode character '\u2705' (check emoji)
  en run_agent.py:8 -> cp1252 no soporta el emoji.
- NSSM pauso el servicio tras 3 reintentos fallidos.
- **Fix:** AppEnvironmentExtra="PYTHONIOENCODING=utf-8" inyectado via NSSM.
  Sin tocar codigo fuente. Verificado: servicio Running, sin errores nuevos.

**Anomalia detectada — bug del stop.flag (SIN RESOLVER):**
- Contexto: detener manualmente el PID 4800 (agente corriendo desde
  Start-Process, no como servicio).
- Secuencia:
  1. Script crea data/stop.flag
  2. Espera 120s al shutdown graceful
  3. Timeout -> throw (no detiene la shell interactiva)
  4. Script REMUEVE data/stop.flag (intento de cleanup)
  5. El agente 4800 sigue vivo (nunca proceso el flag)
- Segundo intento: stop.flag recreado, agente respondio en 5s.
- Hipotesis (no confirmada):
  - H1 (probable): el Remove-Item del script borro el flag antes del chequeo.
  - H2 (posible): bug en el loop que no detecta el flag durante el sleep
    largo post-ciclo (1800s). El stop.flag se verifica cada 1s dentro del
    for loop de sleep, asi que no deberia fallar.
- Requiere investigacion en sesion dedicada. No reproducible en frio.

**Verificacion empirica (2026-09-19):**
- Patron pausa funciono: 2026-09-19 10:09 -> AC desconectado -> pausa
  -> agente sobrevivio ~47 min en bateria antes del apagado del SO.
- El sistema no sobrevive al agotamiento total de bateria (esperado).
- Con NSSM, al proximo boot el agente arranca solo.

**Pendientes:**
- Investigar bug del stop.flag (proximo item de resiliencia).
- Documentar runbook de pausa (como verificar estado, como reanudar).
- Verificar que el agente con NSSM arranca tras un reboot real.

### H.5 — Reparación de mojibake en 2 archivos tracked — CERRADA

**Estado:** 2 archivos reparados, 1489 tests passed. Commit `4cfe401`.

**Alcance:**
- `phases/phase_c_watchlist.py` — 7 líneas, familia `BE/FFFD`.
- `scripts/audit_dryrun_quality.py` — 17 líneas, familia `C3xx`.

**Diagnóstico:**
El handoff describía glifos visibles (3/4 x3, A-tilde x) pero el baseline
real se obtuvo con volcado de code points en hex — inmune al render de
PowerShell, que aplicaba un segundo layer de mojibake al mostrar UTF-8
con code page equivocada.

**Familia A — `phase_c_watchlist.py`:**
`BE` (3/4) + `FFFD` insertados entre caracteres acentuados legítimos.
5 patrones, 7 reemplazos:
- `A\xf1\ufffd\xbe\xbeade` -> Añade
- `ret\xf3\xbe\xbe\xbericas` -> retóricas (2x)
- `ret\xf3\xbe\xbe\xberica` -> retórica (2x)
- `Funci\xf1\xbe\xbe\xben` -> Función (cambio semántico ñ->ó)
- `ejecut\xf3\xbe\xbe\xbe` -> ejecutó

**Familia B — `audit_dryrun_quality.py`:**
`C3 xx` (UTF-8 leído como cp1252). 7 patrones, 20 reemplazos:
- `C3 B3` -> ó (7x)
- `C3 A9` -> é (3x)
- `C3 AC` -> í (7x)
- `C3 B1` -> ñ (1x)
- `C3 9A` -> Ú (1x, mayúscula confirmada por bytes)
- `per ED BA BE odo` -> período (1x, patrón mixto)
- `C3 A1` -> á (0x, sin ocurrencias reales)

**Corrección al handoff anterior:**
- `C3 AC -> í` (el handoff decía -> ì, incorrecto).
- `C3 9A -> Ú` mayúscula (el handoff proponía -> ú minúscula).
- Familia A: 7 líneas reales (el handoff decía 4).

**No tocado — deuda nueva:**
Líneas con emojis multi-byte (`F0 A7 AA A6`, `F0 A7 AB A6`, `E2 A7 AA`,
`E2 C2 A7`) — ~10 líneas. Cadena de mojibake distinta, requieren
análisis aparte. NO son `C3xx` ni `BE/FFFD`.

**Metodología:**
- Baseline SHA256: `7C7BE5EA...` (F1), `33BDF57E...` (F2).
- Backup en `~\backups\comet-riobamba\mojibake-20260919-*`.
- Dry-run + `ast.parse` antes de escribir.
- Apply con verificación de pre-hash (assert) + `ast.parse`.
- Verificación post: `Get-FileHash` + volcado `ascii()` de líneas
  modificadas (ground truth, sin ambigüedad de render).
- Hash post: `4D9F78C3...` (F1), `9A6A833C...` (F2).

**Verificación:**
- `ast.parse` OK en ambos.
- Residual `BE/FFFD/C3` = 0.
- `pytest`: 1489 passed, 1 skipped.

**Pendientes:**
- Reparar líneas con emojis (familia distinta).
- Investigar origen: probable `Set-Content -Encoding` sin UTF-8.


### H.6 — Instrumentación del clasificador Phase A — CERRADA

**Estado:** evento `phase_a_classifier_verdict` emitido por cada evaluación. Commit `e4d4a1c`.

**Contexto:**
El handoff anterior (H.4 + §13.3) pedía validar la tasa de aprobación
del clasificador recalibrado contra el 75.3% in-vitro. Al intentarlo en
producción se descubrió que Phase A **no registraba** el verdicto per-draft:
solo se veía el resultado final (`phase_a_publish_success` o `_skip`).
Los `adjudicator_verdicts.jsonl` existentes son de Phase B (replies).

**Cambio:**
En `_looks_low_quality()` (L1247 de `phases/phase_a_content.py`), tras
llamar a `compute_dual_score()` se emite un evento estructurado con 7
campos: `verdict`, `reason`, `content_type`, `research_value_score`,
`min_quality_score`, `override_substantive`, `len_chars`.

Cubre las 3 rutas de decisión:
- `approve / above_min_quality` — score >= umbral (0.72).
- `approve / substantive_override` — bypass estructural (Fix 6) cuando
  el texto es substantivo y cierra con pregunta abierta genuina.
- `reject / below_min_quality` — score < umbral sin override.

**Semántica preservada:**
El flujo de decisión no cambia. Misma tupla (bool, razón) devuelta. Solo
se añade la emisión del evento `logger.info` antes del `return`.

**Verificación:**
- Backup pre-cambio: `~\backups\comet-riobamba\phase_a_content.py.pre-instr-*`.
- Hash pre: `1FA9E0ACADCA7507`. Hash post: `501587EB44E40011`.
- `ast.parse` OK. CRLF preservado (2293, +21 líneas netas).
- `pytest`: 1489 passed, 1 skipped.
- Tests relevantes (`phase_a`, `dual_score`): 106 passed.

**Métrica in-vitro vs in-vivo — aclaración:**
El 75.3% del handoff anterior mide **drafts del clasificador de contenido**
(fase in-vitro, via `audit_dryrun_quality.py`). La métrica in-vivo
equivalente ahora **existe** pero requiere acumular datos. Primer análisis
recomendado: 7 días de eventos `phase_a_classifier_verdict`.

**Deuda:**
- No hay test unitario para el evento `phase_a_classifier_verdict`.
  Requiere mock de logger + captura de llamada. Prioridad media.
- No hay dashboard/reporte que agregue estos eventos. Se puede construir
  un `scripts/phase_a_verdict_report.py` en sesión futura.



### H.7 — Flag huérfano `AGENT_PHASE_A_PUBLISH_ENABLED` eliminado — CERRADA

**Estado:** eliminado de `.env`, `config/config.py`, `README.md`. Commit pendiente (esta sesión).

**Contexto:**
H.4 (2026-09-11) marcó el flag como huérfano pero lo dejó como deuda. Reauditado en 2026-09-19 con verificación explícita de consumidores.

**Verificación de orfandad (evidencia):**
- `config/config.py:93` lo leía del `.env` y lo mapeaba a
  `behavior_cfg["phase_a_publish_enabled"]`.
- Grep recursivo en `*.py` (excluyendo `.git`, `venv`, `tests`): **cero consumidores** en `phases/`, `core/`, `services/`.
- Única lectura real en producción: `phases/phase_a_content.py:_safe_publish_post` (L1570-1582), que **solo** consulta
  `data/phase_a_dry_run.flag` — nunca el env var.
- 9 usos en `tests/*` (fixtures, ninguno en código de producción).

**Riesgo operativo detectado:**
`README.md:63` documentaba `AGENT_PHASE_A_PUBLISH_ENABLED=0   # 0 = borradores; 1 = publica`. Un operador podía poner el flag a 0 creyendo que desactivaba publicación y el agente **publicaría igual**. El kill-switch real es el archivo `data/phase_a_dry_run.flag`.

**Cambio (3 archivos, 3 líneas eliminadas):**
- `.env:72` — `AGENT_PHASE_A_PUBLISH_ENABLED=0`.
- `config/config.py:93` — `"phase_a_publish_enabled": bool(int(os.getenv("AGENT_PHASE_A_PUBLISH_ENABLED", 0)))`.
- `README.md:63` — línea de documentación obsoleta.

**Decisión: eliminar, no reimplementar.** El dry-run flag por archivo es superior: se activa/desactiva en caliente (crear/borrar archivo), no requiere reinicio de NSSM, no depende del reload de `behavior_cfg`. Dos kill-switches para lo mismo es peor que uno.

**SHA256 antes/después:**
- `.env`            `b988ced821933821...` → `fd2101ae69b9e9c5...`
- `config/config.py` `8cb555a4c9f60b5e...` → `53dc76dda74fcfb3...`
- `README.md`        `7c1a76ec969e82ff...` → `6403ae5e31f6bc49...`

**Verificación:**
- Backup pre-cambio: `~\backups\comet-riobamba\phase25-20260919-184141\`.
- `ast.parse` OK. CRLF preservado en los 3 archivos.
- `git diff --stat`: 2 files, 2 deletions (`.env` no tracked).
- `pytest`: 1489 passed, 1 skipped (baseline idéntico a H.6).
- Grep post-fix: cero ocurrencias en `.env`, `config/config.py`, `README.md`.

**Deuda que deja esta entrada:**
- H.4 L1531 (`Deuda pendiente`) menciona el flag como pendiente. Se deja **sin editar** por convención append-only del documento; esta entrada H.7 la resuelve retroactivamente.
- Fase 2.5 continúa: quedan `AGENT_PRO_TIER_ONLY`, `AGENT_QUALITY_BESTOF`, `MODEL_TIER_PRO_*` (4 keys) y `AGENT_PHASE_A_MODE` sin verificar consumidores.



### H.8 — 5 flags huérfanos de tier/Phase A eliminados — CERRADA

**Estado:** eliminados de `.env` y `docs/COMET-RIOBAMBA_REFERENCE.md`. Commit pendiente (esta sesión).

**Contexto:**
Continuación de Fase 2.5 (auditoría `config/`) tras H.7. Barrido de 48 keys en `.env` con grep recursivo sobre `*.py` de producción (excluyendo tests, venv, `scripts/comet_repurposer/`).

**Veredicto por flag (7 candidatos iniciales):**
- `AGENT_PRO_TIER_ONLY`        → VIVO (`services/model_cascade.py:304`).
- `AGENT_QUALITY_BESTOF`      → VIVO (`utils/quality_flags.py:13`, consumido en Phase A L1892 y Phase B L2762).
- `AGENT_PHASE_A_MODE`        → VIVO (`config.py:93` → `behavior_cfg["phase_a_mode"]` → `phase_a_content.py:615`).
- `MODEL_TIER_PRO_TIMEOUT_SECONDS` → VIVO (`model_cascade.py:191`).
- `MODEL_TIER_PRO_ENABLED`    → **HUÉRFANO**.
- `MODEL_TIER_PRO_URL`        → **HUÉRFANO** (duplicado literal de `DEEPSEEK_PRO_URL`, L39 del `.env`).
- `MODEL_TIER_PRO_MODEL`      → **HUÉRFANO** (duplicado literal de `DEEPSEEK_PRO_MODEL`, L40 del `.env`).

**Verificación adicional (2da ronda, familia Phase A):**
- `PHASE_A_GENERATION_TIER`   → VIVO (`phase_a_content.py:1903`).
- `PHASE_A_MODEL_TIER`        → **HUÉRFANO**.
- `PHASE_A_MODEL`             → **HUÉRFANO**.

**Confirmación de orfandad (los 5):**
- Cero matches en `*.py` de producción (grep recursivo).
- Cero matches en `tests/` (sin fixtures que limpiar).
- Cero matches en `docs/CONFIG_TRUTH.md` (fuente de verdad).
- Cero matches en `.py` de `config/` — no llegaban a mapearse a `behavior_cfg`.

**Riesgo operativo:** idéntico patrón a H.7. La construcción real de `tier_pro` en `services/model_cascade.py:181-196` usa:
```
DEEPSEEK_PRO_API_KEY  ← key
DEEPSEEK_PRO_URL      ← URL      (no MODEL_TIER_PRO_URL)
DEEPSEEK_PRO_MODEL    ← modelo   (no MODEL_TIER_PRO_MODEL)
MODEL_TIER_PRO_TIMEOUT_SECONDS ← timeout  (único vivo)
```
Un operador podía cambiar `MODEL_TIER_PRO_MODEL` creyendo cambiar el modelo activo y el agente seguía usando `DEEPSEEK_PRO_MODEL`.

**Documentación colateral corregida:**
`docs/COMET-RIOBAMBA_REFERENCE.md:37-38` documentaba `PHASE_A_MODEL_TIER` y `PHASE_A_MODEL` como si fueran efectivos. 2 filas de tabla eliminadas.

**Cambio (2 archivos, 7 líneas eliminadas):**
- `.env:17` — `PHASE_A_MODEL_TIER=tier_pro`.
- `.env:18` — `PHASE_A_MODEL=deepseek-v4-pro`.
- `.env:27` — `MODEL_TIER_PRO_ENABLED=true`.
- `.env:28` — `MODEL_TIER_PRO_URL=https://api.deepseek.com/v1/chat/completions`.
- `.env:29` — `MODEL_TIER_PRO_MODEL=deepseek-v4-pro`.
- `COMET-RIOBAMBA_REFERENCE.md:37` — fila de tabla de `PHASE_A_MODEL_TIER`.
- `COMET-RIOBAMBA_REFERENCE.md:38` — fila de tabla de `PHASE_A_MODEL`.

**SHA256 antes/después:**
- `.env`                          `fd2101ae69b9e9c5...` → `424f64f5183a9a36...`
- `docs/COMET-RIOBAMBA_REFERENCE.md` `cbdd4f53070b98ac...` → `bf4f24453b7b033e...`

**Verificación:**
- Backup pre-cambio: `~\backups\comet-riobamba\phase25b-20260919-190857\`.
- Script con asserts de unicidad por línea (cada target aparece exactamente 1 vez).
- `git diff --stat`: 1 file, 2 deletions (`.env` no tracked).
- CRLF preservado. Rezagos post-fix: cero ocurrencias en `.env` y `COMET-RIOBAMBA_REFERENCE.md`.
- `pytest`: pendiente (ejecutado tras este append).

**Deuda que deja esta entrada:**
- **Inconsistencias adicionales en `COMET-RIOBAMBA_REFERENCE.md` L30-43** (fuera de scope de H.8):
  - L39: `DEEPSEEK_SPEND_LIMIT_USD=2.00` → real `0.5`.
  - L43: `AGENT_CYCLE_INTERVAL_SECONDS=300` → real `1800`.
  - L32, L40, L42: `AGENT_PHASE_A_ENABLED`, `ANTHROPIC_SPEND_LIMIT_USD`, `PHASE_B_FEED_REPLIES` — verificar si existen en `.env` actual.
  - **Mojibake pre-existente** en líneas de contexto (`mÃĐtricas`, `LÃ­mite`, `generaciÃģn`). Verificar byte-level si es real o artefacto de display antes de tocar.
  Candidato a H.9 (auditoría de documentación técnica).
- Asimetría: `MODEL_TIER_FLASH_TIMEOUT_SECONDS` se lee en `model_cascade.py:209` (default 90) pero no está declarado en `.env`.
- `MODEL_TIER_PRO_TIMEOUT_SECONDS` sigue vivo y declarado en `.env:30` → no tocar. Documentar en CONFIG_TRUTH.md si se formaliza la familia `MODEL_TIER_*`.



### H.9 — Fix test roto por fecha hardcodeada (editorial_self_audit) — CERRADA

**Estado:** fix aplicado. Commit pendiente (esta sesión).

**Contexto:**
Detectado durante verificación de H.8. La suite completa dio `1 failed, 1488 passed, 1 skipped` con:
`tests/test_editorial_self_audit.py::TestAnalyzeVotes::test_calibration_holds_when_higher_score_wins`
→ `KeyError: '<=0.3'`.

**Diagnóstico (no relacionado con H.7/H.8):**
Los dos tests `TestAnalyzeVotes` usaban fechas hardcodeadas `"date": "2026-08-20"` y llamaban `_analyze_votes(votes)` con default `days=30`. El cutoff es dinámico: `today - days`. La comparación interna es estricta (`date > cutoff`).

- 18/09/2026: cutoff = 19/08, `20/08 > 19/08` → True → tests pasan.
- 19/09/2026: cutoff = 20/08, `20/08 > 20/08` → False → **todos los votos excluidos**, buckets vacíos, `KeyError`.

Bug latente: el test se rompe automáticamente al cruzar los 30 días de antigüedad de su fecha hardcodeada. Coincidió con esta sesión por azar, no por causa.

**Verificación empírica:** con `days=30` → keys `['calibrated', 'overall_upvote_rate_pct']` (sin buckets). Con `days=31` → keys completas + valores correctos (10, 75, True).

**Cambio (`tests/test_editorial_self_audit.py`, +7 líneas, 8 modificadas):**
- Import a nivel módulo: `from datetime import datetime, timedelta, timezone`.
- Helper `_recent_date(days_ago: int = 10) -> str` que devuelve una fecha ISO reciente.
- 8 reemplazos: `"date": "2026-08-20"` → `"date": _recent_date()`.
- `"date": "2026-01-01"` (test_old_records_ignored) intacta: el test verifica el comportamiento con registros viejos por diseño.

**SHA256 antes/después:**
`tests/test_editorial_self_audit.py` `b9e69e875aa00237...` → `64107a9ce3694840...`

**Verificación:**
- Backup pre-cambio: `~\backups\comet-riobamba\phase25c-20260919-195745\`.
- `ast.parse` OK. CRLF preservado.
- `pytest tests/test_editorial_self_audit.py -v`: 10/10 PASSED.
- `pytest tests/ -q`: 1489 passed, 1 skipped (baseline restaurado).

**Deuda que deja esta entrada:**
- Otros tests del repo podrían tener el mismo patrón (fechas hardcodeadas + ventanas deslizantes). Candidato a grep: `Select-String -Pattern '\d{4}-\d{2}-\d{2}' tests\*.py`.
- El helper `_post(hours_ago=48)` en el mismo archivo ya usaba fechas dinámicas — el fix alinea los tests de votos con esa convención.

### H.10 — Eliminar campo huérfano deepseek_flash_timeout (credentials.py) — CERRADA

**Estado:** fix aplicado. Commit atómico (esta sesión).

**Contexto:**
Detectado durante verificación de Fase 2.5 (auditoría `config/`), como continuación natural de H.7/H.8.
El handoff 2026-09-19 (tarde) listaba dos items pendientes en la familia TIMEOUT:
1. Asimetría `MODEL_TIER_FLASH_TIMEOUT_SECONDS` (leída con default 90 pero no declarada en `.env`).
2. `AGENT_QUALITY_BESTOF` (verificado VIVO, sin cambios).

**Diagnóstico:**
El grep de consumidores reveló un hallazgo más fuerte que la asimetría: **dos campos del dataclass `Credentials` no tienen ningún consumidor en producción ni en tests**.

| Campo | Declaración | Consumidores prod | Consumidores tests |
|---|---|---|---|
| `deepseek_flash_timeout` | `credentials.py:43` | **0** | **0** |
| `deepseek_timeout` | `credentials.py:31` | **0** | 2 (fixtures de test) |
| `cerebras_timeout` | `credentials.py:48` | 1 (`model_cascade.py:240`) | — |
| `ollama_cloud_timeout` | `credentials.py:51` | 0 | 0 |

Solo `deepseek_flash_timeout` es **100% huérfano** (0 refs en prod + 0 en tests). Mismo patrón exacto de H.7/H.8: env var declarada, mapeada a un campo, pero el consumidor final nunca existe.

**Sobre la asimetría `MODEL_TIER_FLASH_TIMEOUT_SECONDS`:** no se toca en esta entrada. El histórico `data/env_backup_20260822.txt` confirma que la variable fue eliminada deliberadamente el 22/08/2026 (junto con `MODEL_TIER_FLASH_{URL,MODEL,API_KEY}`), en el mismo batch que cambió `ZEN_ENABLED=true → false`. El default 90 en `model_cascade.py:209` es intencional. Documentar formalmente queda como deuda aparte si se decide formalizar la familia `MODEL_TIER_*` en `docs/CONFIG_TRUTH.md`.

**Cambio (`config/credentials.py` −2 líneas; `.env` −1 línea local):**
- `config/credentials.py:43` → eliminado campo `deepseek_flash_timeout: int = 90`.
- `config/credentials.py:78` → eliminado kwarg `deepseek_flash_timeout=int(os.getenv("DEEPSEEK_FLASH_TIMEOUT_SECONDS", "90")),`.
- `.env:30` → eliminada línea `DEEPSEEK_FLASH_TIMEOUT_SECONDS=90` (archivo gitignored; cambio local, no versionado).

**SHA256 antes/después:**
- `config/credentials.py`: `306f1d7b97f4169b...` → `08ff259ac3918d57...`
- `.env`: `424f64f5183a9a36...` → `074206e32a8c6ab2...`

**Verificación:**
- Backup pre-cambio: `~\backups\comet-riobamba\H10-20260919-202211\`.
- Assert de unicidad pre-edición: 2 ocurrencias en `credentials.py`, 1 en `.env`.
- `ast.parse` PRE y POST: OK. CRLF preservado (85→83 en `credentials.py`, 79→78 en `.env`).
- Post-assert: **0 ocurrencias** de `deepseek_flash_timeout` / `DEEPSEEK_FLASH_TIMEOUT_SECONDS` en el repo (excluyendo backups/`.pyc`/`.bak`).
- `git diff` limpio: exactamente 2 líneas eliminadas en `credentials.py`, 0 añadidas, 0 modificadas.
- `pytest tests/ -q`: 1489 passed, 1 skipped (baseline idéntico).

**Deuda que deja esta entrada:**
- `deepseek_timeout` (`credentials.py:31`) sigue presente: 0 consumidores en prod, 2 fixtures de test lo asignan sin verificarlo. Eliminarlo requiere decidir qué hacer con `tests/test_model_cascade.py:591` y `tests/test_zen_deepseek_wiring.py:41`. Candidato a H.11.
- `ollama_cloud_timeout` (`credentials.py:51`): 0 consumidores, pero sin env var asociada (`OLLAMA_CLOUD_TIMEOUT_SECONDS` no existe). Caso distinto; candidato a H.11/H.12.
- `MODEL_TIER_FLASH_TIMEOUT_SECONDS`: documentar en `CONFIG_TRUTH.md` como default implícito intencional (ver arriba).

### H.10b — Verificación COMET-RIOBAMBA_REFERENCE.md L32-43 (no-op) — CERRADA

**Estado:** verificado, sin cambios. No-op documentado.

**Contexto:**
El handoff 2026-09-19 (tarde) listaba dos items a resolver en `docs/COMET-RIOBAMBA_REFERENCE.md`:
1. Inconsistencias de valores L32-43 (`DEEPSEEK_SPEND_LIMIT_USD=2.00`, `AGENT_CYCLE_INTERVAL_SECONDS=300`, etc.).
2. Mojibake pre-existente en líneas de contexto.

**Hallazgo 1 — inconsistencias son intencionales:**
El archivo abre con aviso explícito (L1-6):
> AVISO DE DESACTUALIZACION - 2026-09-11
> Los valores de configuracion en este documento NO reflejan la realidad.
> Fuente de verdad: docs/CONFIG_TRUTH.md + config/config.py + .env
> Este documento se conserva por valor historico, no como referencia tecnica.

Corregir los valores violaría esa decisión. El archivo **debe** mantener su snapshot histórico. Acción: ninguna.

**Hallazgo 2 — mojibake NO existe:**
Verificación byte-level (`Path.read_bytes()` + `Format-Hex`):
- Mojibake real (8 patrones: `â€”`, `Ã©`, `Ã³`, `Ã±`, `Ã¡`, `Ã`, comillas): **0 hits**.
- `decode('utf-8')` strict: **OK**.
- L34 byte-level: `6D C3 A9 74 72 69 63 61 73` = `m é t r i c a s` (UTF-8 válido).
- `mÃ©tricas` visto en consola = artefacto de display PowerShell (CP850/CP1252), no corrupción.

Caracteres UTF-8 válidos presentes: em-dash ×3, á ×8, é ×9, í ×14, ó ×27.

**Acción:** ninguna. Ambos items del handoff eran falsos positivos.

**Nota:** este párrafo contiene literalmente las secuencias mojibake como 
ejemplos pedagógicos (entre backticks). Búsquedas futuras de 
mojibake en este archivo deben excluir la sección H.10b para evitar falsos 
positivos.

**Deuda que deja esta entrada:**
Ninguna. Este no-op cierra el cabo suelto de H.8.
---

## H.12 — Fix run_id por ciclo en generation_attempts (2026-09-20)

Problema: generation_attempts.jsonl mezclaba eventos de distintas ejecuciones. Fix (985cd2f): _RUN_ID global + set_run_id/get_run_id + campo run_id en cada record. core/agent.py lo llama al inicio de cada ciclo con formato cycle-N-<unix_ts>. 4 tests nuevos.

## H.13 — Restaurar allowlist + min=2 en max_comment_replies (2026-09-20)

Problema doble: (1) motor rechazo 582 propuestas con param_not_in_allowlist, 4 params desaparecidos, phase_b_max_replies era ghost. (2) auto-apply aplico max_comment_replies_per_cycle=0, desactivando Phase B. Fixes f265756 + 7dec8cb: 4 params restaurados, min 0->2, phase_b_max_replies -> phase_b_max_own_comments_per_cycle, _save_overlay atomico. Overlay corregido 0->2.

## H.14 — ts/timestamp/run_id en proposal_apply_log (2026-09-20)

Problema: proposal_apply_log.jsonl sin timestamp ISO ni run_id. 592 entries historicas, 0 con trazabilidad. Fix (6717543): _RUN_ID + set_run_id/get_run_id en proposal_applier, _append_apply_log enriquecido (ts + timestamp ISO UTC + run_id), _last_change_time endurecido. 2 tests nuevos. Regla #31 generalizada. Legacy archivado en data/proposal_apply_log.legacy-20260920.jsonl.

## H.15 — Aislar JSONL de Phase A en tests (2026-09-20)

Problema: generation_attempts.jsonl acumulaba 637 bytes por corrida de pytest con ts congelado 2026-07-22T12:00:00. Fix (ae72715): fixture autouse _isolate_phase_a_jsonl_logs en tests/conftest.py redirige 6 paths a tmp_path. Verificacion: 126 tests, delta=0 bytes. Purga: 2413 entries contaminadas removidas.

## H.16 — Reorganizacion docs: NORTH_STAR + archive (2026-09-20)

Problema: 34 docs en docs/ con solapamiento (3 READMEs, 2 objetivos, 2 estrategias). Creados: NORTH_STAR.md, CONTENT_STRATEGY.md, DOC_COHERENCE.md, PENDING.md. Archivados 19 docs a docs/archive/. Borrado LECCIONES_APRENDIDAS_2026-09-03.md (0 bytes). 7 docs stale actualizados.
