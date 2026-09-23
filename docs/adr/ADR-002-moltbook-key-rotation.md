# ADR-002: Procedimiento de rotación de MOLTBOOK_API_KEY

## Status

Propuesto (2026-09-22). Pendiente de aprobación por el operador.

## Context

El 2026-09-21, MOLTBOOK_API_KEY quedó expuesta accidentalmente durante una sesión. Registrada como P-047. La key se migró de .env a DPAPI machine-scoped, pero la key en sí no fue rotada — solo cambió el mecanismo de almacenamiento.

El análisis del 2026-09-22 reveló dos hechos:

1. Existen tres wrappers de lectura de key con lógicas distintas:
   - config/credentials.py::_get_secret() — DPAPI -> keyring -> env
   - services/top_agents_tracker.py::_get_moltbook_api_key() — keyring -> env
   - services/editorial_self_audit.py — keyring directo

2. La key actual está almacenada en ambos (DPAPI y keyring) con el mismo valor.

Una rotación que solo actualice DPAPI dejaría dos wrappers leyendo la key vieja. Una rotación que solo actualice keyring dejaría el wrapper primario leyendo la key vieja.

## Decision

Se adopta el siguiente procedimiento, ejecutado con PowerShell como Administrador, desde C:\comet-riobamba-v31:

### Paso 1 — Backup preventivo

- Crear data\.secrets_backup\ con .gitignore
- Copiar data\.secrets\moltbook_api_key.enc a data\.secrets_backup\moltbook_api_key.YYYYMMDD_HHMMSS.enc
- Registrar el nombre del backup

### Paso 2 — Detener servicio

    & .\tools\nssm.exe stop CometRiobamba
    Start-Sleep -Seconds 5

Verificar que Get-Service CometRiobamba reporta Stopped antes de continuar.

### Paso 3 — Leer nueva key

Usar Read-Host -AsSecureString. Nunca como argumento de línea de comandos ni como variable de entorno persistente.

### Paso 4 — Validar nueva key ANTES de sobrescribir

Hacer llamada de prueba a GET /api/v1/feed con la nueva key (sin persistirla).

Si falla: abortar, no sobrescribir, reiniciar servicio con key vieja.

### Paso 5 — Sobrescribir DPAPI y keyring

Solo si la validación previa pasa:

    from services.secret_store import set_secret
    import keyring
    set_secret('moltbook_api_key', nueva_key)
    keyring.set_password('comet_riobamba', 'moltbook_api_key', nueva_key)

### Paso 6 — Validar persistencia

    from services.secret_store import get_secret
    import keyring
    assert get_secret('moltbook_api_key') == nueva_key
    assert keyring.get_password('comet_riobamba', 'moltbook_api_key') == nueva_key

### Paso 7 — Iniciar servicio y verificar

    & .\tools\nssm.exe start CometRiobamba
    Start-Sleep -Seconds 15
    Get-Content .\logs\agent.log -Tail 30

Verificar que el agente arranca sin errores de autenticación.

### Paso 8 — Documentar

- Actualizar docs/PENDING.md: P-047 como DONE con fecha y referencia al backup
- Añadir entrada a CHANGELOG.md
- Anotar en docs/AUDITORIA_ENTORNO.md

## Invariants

- INV1: la nueva key nunca aparece en logs, archivos de texto, ni argumentos de comandos.
- INV2: existe un backup cifrado de la key vieja antes de cualquier sobrescritura.
- INV3: la validación de la nueva key ocurre antes de sobrescribir DPAPI/keyring.
- INV4: DPAPI y keyring se actualizan en la misma sesión, nunca uno solo.
- INV5: el servicio se detiene antes de la rotación y se reinicia después de la validación.
- INV6: la rotación queda registrada con timestamp, operador, motivo y backup.

## Consequences

### Positivas

- Ambos wrappers ven la misma key nueva.
- Backup permite rollback si algo falla.
- Validación previa evita dejar el servicio con key inválida.
- Procedimiento documentado para futuras rotaciones.

### Negativas / riesgos

- Requiere ventana sin ciclos del agente (~5 minutos).
- Si el operador pega la key equivocada, el procedimiento aborta y reinicia con la vieja.
- P-048 (unificar wrappers) sigue pendiente y debe hacerse para simplificar futuras rotaciones.

## Referencias

- P-047 en docs/PENDING.md
- ADR-001 en docs/adr/ADR-001-system-invariants.md
- docs/AUDITORIA_ENTORNO.md
- docs/DIRECTRICES.md
- services/secret_store.py
- config/credentials.py

---

*Generado 2026-09-22. Pendiente de aprobación antes de ejecutar.*
