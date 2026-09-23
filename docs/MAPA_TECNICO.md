# MAPA TÉCNICO — COMET-RIOBAMBA

**Fecha:** 2026-09-22
**Propósito:** mapa de servicios, componentes, wrappers y endpoints

## 1. Servicios Windows

| Nombre | Estado | Start | Cuenta |
|---|---|---|---|
| CometRiobamba | Running | Auto | LocalSystem |
| CometElevationService | Stopped | - | - |
| CometUpdaterInternalService151.0.7922.249 | Stopped | - | - |
| CometUpdaterService151.0.7922.249 | Stopped | - | - |

## 2. Entorno

| Item | Valor |
|---|---|
| Ruta proyecto | C:\comet-riobamba-v31 |
| Python | C:\Python314\python.exe (3.14.7) |
| NSSM | C:\comet-riobamba-v31\tools\nssm.exe |
| Working dir | C:\comet-riobamba-v31 |
| Entry point | run_agent.py |
| Ciclo | ~250s ejecución + 1800s espera |

## 3. Módulos clave

| Módulo | Rol | Ruta |
|---|---|---|
| Agente principal | Orquesta ciclos A-B-C | core/agent.py |
| Cliente Moltbook | HTTP + circuit breaker | services/moltbook_api_client.py |
| Credenciales | Carga API keys | config/credentials.py |
| Secret store | Cifrado DPAPI | services/secret_store.py |
| Resiliencia | Circuit breakers | utils/resilience.py |
| Pausa | Control de pausa | services/pause_controller.py |
| Batería | Monitor batería | services/battery_monitor.py |
| Balance | Guard saldo DeepSeek | services/balance_guard.py |

## 4. Lectura de key (unificada 22/9, P-048)

| # | Archivo | Mecanismo |
|---|---|---|
| 1 | config/credentials.py::_get_secret() | Canonico: DPAPI -> keyring -> env |
| 2 | services/top_agents_tracker.py::_get_moltbook_api_key() | Delega en _get_secret |
| 3 | services/editorial_self_audit.py::main() | Delega en _get_secret |

Wrapper canonico unico: config.credentials._get_secret() (respeta COMET_DISABLE_KEYRING=1 en tests). Unificado 22/9 (P-048, commit 99bda68); verificado sin otros lectores (P-060). scripts/_rotate_key.py es escritor, no lector.

## 5. Endpoints de Moltbook

| Método | Endpoint | Usado por |
|---|---|---|
| GET | /api/v1/feed | client.get_feed(limit=N) |
| GET | /api/v1/users/top?limit=N | top_agents_tracker.py |
| GET | /api/v1/users/{user_id} | top_agents_tracker.py |

**Endpoint NO válido:** GET /api/v1/users/me -> HTTP 404 (verificado 2026-09-22)

## 6. Gestión de secretos

| Mecanismo | Ubicación | Estado |
|---|---|---|
| DPAPI | data\.secrets\moltbook_api_key.enc | Presente |
| Keyring | comet_riobamba / moltbook_api_key | Presente |
| .env | C:\comet-riobamba-v31\.env | Ausente |

DPAPI y keyring contienen la misma key (sha256[:16]=ae58656c69374d65).

## 7. Documentación existente

- docs/ contiene 27 documentos top-level
- docs/adr/ contiene ADR-001-system-invariants.md
- CHANGELOG.md en raíz (última entrada 5.11.x, 2026-08-29)
- docs/PENDING.md formato ID|Estado|Creado|Descripción|Origen
- docs/DIRECTRICES.md con sección "Principios (Rafael)"

## 8. Puntos de fallo conocidos

| Punto | Mitigación actual |
|---|---|
| Corrupción SQLite | WAL (a verificar) |
| Key expuesta | DPAPI + keyring |
| Circuit breaker tripped | utils/resilience.py |
| Balance DeepSeek bajo | services/balance_guard.py |
| Batería baja | services/battery_monitor.py |
| Pausa manual | services/pause_controller.py |

## 9. Referencias

- docs/AUDITORIA_ENTORNO.md
- docs/PENDING.md (P-047 rotación key)
- docs/adr/ADR-001-system-invariants.md
- docs/DIRECTRICES.md

---

*Generado 2026-09-22.*
