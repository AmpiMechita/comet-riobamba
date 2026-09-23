# ADR-002: Procedimiento de rotación de MOLTBOOK_API_KEY

## Status

Aceptado (2026-09-22, aprobado 2026-09-23). Implementado por `scripts/rotate_key.py`
(P-049). Reemplaza el procedimiento manual original.

## Context

El 2026-09-21, MOLTBOOK_API_KEY quedó expuesta accidentalmente durante una sesión.
Registrada como P-047. La key se migró de .env a DPAPI machine-scoped y se rotó
el 22/9 20:18.

El análisis original (2026-09-22) reveló dos hechos:

1. Existían tres wrappers de lectura de key con lógicas distintas. Cerrado por
   P-048 (commit 99bda68): los tres delegan ahora en
   `config.credentials._get_secret()` (DPAPI -> keyring -> env).

2. La key está almacenada en DPAPI y keyring con el mismo valor. La rotación
   debe actualizar ambos, nunca uno solo.

## Decision

Procedimiento automatizado por `scripts/rotate_key.py`. Secuencia operativa:

### Paso 0 — Preparar

- Escribir la nueva key en `data\.secrets_backup\new_key.tmp`
- Parar el servicio: `.\tools\nssm.exe stop CometRiobamba`
- Verificar con `Get-Service CometRiobamba` que reporta `Stopped`

### Paso 1 — Ejecutar el script

    python scripts\rotate_key.py

El script ejecuta en este orden:

  a) Validación HTTP contra `GET /api/v1/feed` (aborta si falla; NO borra temp)
  b) Backup del blob DPAPI a `data\.secrets_backup\moltbook_api_key.<ts>.enc`
  c) Guarda el valor actual del keyring en memoria (para rollback)
  d) `set_secret()` (DPAPI) + `keyring.set_password()`
  e) Verifica lectura desde ambos
  f) Si (e) falla: ROLLBACK automático (restaura blob DPAPI + keyring)
  g) Si todo OK: borra `new_key.tmp`

Modo `--dry-run`: solo valida; no escribe, no borra temp.

### Paso 2 — Reiniciar servicio y verificar

    .\tools\nssm.exe start CometRiobamba
    Start-Sleep -Seconds 15
    Get-Content .\logs\agent.log -Tail 30

Verificar que el agente arranca sin errores de autenticación.

### Paso 3 — Documentar

- Actualizar `docs/PENDING.md`
- Añadir entrada a `CHANGELOG.md`
- Anotar en `docs/AUDITORIA_ENTORNO.md`

## Invariants

- INV1: la nueva key nunca aparece en logs, archivos de texto, ni argumentos de comandos.
- INV2: existe un backup cifrado de la key vieja antes de cualquier sobrescritura.
- INV3: la validación de la nueva key ocurre antes de sobrescribir DPAPI/keyring.
- INV4: DPAPI y keyring se actualizan en la misma sesión, nunca uno solo.
- INV5: el servicio se detiene antes de la rotación y se reinicia después de la validación.
  (Responsabilidad del operador; el script no toca el servicio.)
- INV6: la rotación queda registrada con timestamp, operador, motivo y backup.
- INV7: si la verificación post-escritura falla, el script restaura DPAPI y keyring
  al estado previo (rollback automático).

## Consequences

### Positivas

- Ambos wrappers ven la misma key nueva.
- Backup automático + rollback automático ante fallo de escritura.
- Validación previa evita dejar el servicio con key inválida.
- Un solo comando: `python scripts\rotate_key.py`.
- Modo `--dry-run` permite validar sin escribir.

### Negativas / riesgos

- Requiere ventana sin ciclos del agente (~5 minutos).
- El script NO para/inicia el servicio (INV5 es manual): el operador debe hacerlo.
- Si el operador pega la key equivocada, el script aborta antes de escribir.

## Referencias

- P-047, P-049 en `docs/PENDING.md`
- `scripts/rotate_key.py`
- `services/secret_store.py`
- `config/credentials.py`
- `docs/DIRECTRICES.md` (reglas 8, 33)
- `docs/adr/ADR-001-system-invariants.md`

---

*Generado 2026-09-22. Actualizado 2026-09-23 (P-062): status Aceptado,
Paso 3 alineado con `rotate_key.py`, P-048 cerrado.*
