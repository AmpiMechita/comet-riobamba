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

