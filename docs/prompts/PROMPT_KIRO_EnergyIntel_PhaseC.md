# Prompt para KIRO — Integrar Energy Intel en Phase C del Ciclo del Agente

> **Instrucciones para KIRO**: Estás en `C:\comet-riobamba-v31`. Tareas concretas, no preguntes. Código en inglés.

---

## CONTEXTO

Ya creaste `services/energy_intel_telegram.py` con `run_energy_intel_with_alerts(telegram_client)`. El problema es que nadie lo llama. El usuario quiere que el agente **automáticamente** notifique por Telegram cada vez que `energy_intel_node.py` genere tecnología de vanguardia.

`energy_intel_node.py` es un módulo standalone con FastAPI + scrapers que produce claims (papers, patentes, press releases). Tu hook `run_energy_intel_with_alerts()` ya filtra solo "frontier technologies" y envía máx 3 alertas por ejecución.

## TAREA ÚNICA: Integrar en Phase C

1. **Lee `phases/phase_c_analytics.py`** completo para entender la estructura actual.

2. **Agrega la llamada a `run_energy_intel_with_alerts()` dentro de Phase C**, con estas condiciones:
   - Se ejecute **solo una vez por hora** (no en cada ciclo de 5 min — el scraper es pesado y no hay suficientes papers nuevos cada 5 min).
   - Usa un mecanismo de throttling: guarda timestamp de última ejecución en `data/last_energy_intel_run.txt` o en `comet_state.db` (como prefieras, pero sé consistente con el patrón ya usado para `last_balance_check.txt`).
   - Solo ejecute si `TELEGRAM_ALERTS_ENABLED=1` en `.env` (verifica cómo se lee este flag en `core/agent.py` — probablemente ya existe un `self.telegram_client` o similar inyectado).

3. **Manejo de errores**: Si `energy_intel_node.py` falla (timeout del scraper, error de API, import error), log WARNING y continúa el ciclo. No debe romper Phase C ni el ciclo del agente.

4. **Pasaje de dependencias**: `run_energy_intel_with_alerts` recibe `telegram_client` como parámetro. Asegúrate de que Phase C tenga acceso al `telegram_client` (verifica cómo se inyecta en `deps.py` o `core/agent.py`).

5. **Logging**: Agrega estos logs:
   - `INFO` al inicio: `"Energy Intel: ejecutando ingest (última ejecución: X min atrás)"`
   - `INFO` si no hay nuevas claims: `"Energy Intel: sin nuevas tecnologías de frontera"`
   - `INFO` con resumen: `"Energy Intel: N alerta(s) enviada(s) por Telegram"`
   - `WARNING` si falla: `"Energy Intel: error en ejecución — {error}"`

6. **Tests**: Agrega 2-3 tests en `tests/test_telegram_integration.py`:
   - `test_energy_intel_throttle` — no ejecuta si pasó menos de 1 hora
   - `test_energy_intel_runs_after_1_hour` — ejecuta si pasó más de 1 hora
   - `test_energy_intel_error_doesnt_crash_phase_c` — si falla, Phase C continúa

7. **Ejecuta `pytest`** completo para verificar que nada se rompe.

---

## REGLAS

- No rompas los 208+ tests existentes
- El throttling de 1 hora es mandatorio — no ejecutes en cada ciclo
- Si `energy_intel_node.py` no puede importarse (missing deps, etc.), no rompas el agente. Haz un try/except de import y log WARNING una sola vez.
- Commit granular: 1 commit con todo junto está bien ya que es una tarea única.

Empieza leyendo `phases/phase_c_analytics.py` y `services/energy_intel_telegram.py`.