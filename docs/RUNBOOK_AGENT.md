# RUNBOOK_AGENT - COMET-RIOBAMBA

## Propósito
Este runbook describe cómo operar el agente completo de COMET-RIOBAMBA en producción:
- Fase A: generación y publicación de contenido.
- Fase B: respuestas a la comunidad.
- Fase D1: observabilidad y evaluación de comunidad.

Se centra en comandos mínimos y seguros para operadores humanos.

---

## 1) Arrancar el agente principal (ciclos A/B en producción)

Usar para iniciar el agente que ejecuta ciclos (Fase A y Fase B) con monitoreo Telegram y publicación en Moltbook.

`powershell
# Desde el directorio raíz del proyecto
Set-Location C:\comet-riobamba-v31

# Arranque del agente principal (ejemplo típico en logs)
python -m core.agent
`

Notas:
- Verificar que el entorno Python y las variables necesarias (tokens, API keys) estén configuradas según la documentación interna.
- En los logs deberías ver mensajes del tipo:
  - CICLO #N INICIADO
  - FASE A: ...
  - FASE B: ...
  - CICLO #N FINALIZADO

---

## 2) Forzar un ciclo manual del agente (A/B)

Usar cuando se desee ejecutar un ciclo manual bajo supervisión directa (por ejemplo, en ventana de mantenimiento).

`powershell
Set-Location C:\comet-riobamba-v31

# Ejemplo de ejecución de un solo ciclo, si existe un comando o flag específico
python -m core.agent --once
`

Si no existe el flag --once en la implementación actual:
- Ejecutar python -m core.agent y supervisar manualmente el primer ciclo en los logs.
- Interrumpir con Ctrl + C después de la finalización del ciclo deseado.

---

## 3) Operar la fase D1 (evaluación de comunidad)

Usar tras uno o varios ciclos para registrar interacciones y evaluar la respuesta de la comunidad.

### 3.1 Registrar evento real

`powershell
powershell -ExecutionPolicy Bypass -File .\scripts\add_community_event.ps1 
  -Source "telegram" 
  -PostId "post-000X" 
  -EventType "comment" 
  -ActorHandle "@usuario_real" 
  -RawText "texto real observado" 
  -SentimentLabel "neutral" 
  -ActionTaken "logged" 
  -OperatorReview "pending"
`

### 3.2 Ejecutar ciclo de D1 (resumen + validación endurecida)

`powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_d1_cycle.ps1
`

### 3.3 Consultar estado de D1

`powershell
Get-Content .\logs\D1_PIPELINE_STATUS.md
`

- **Status:** PASS → D1 estable según el protocolo actual.
- **Status:** FAIL → revisar ## Error en el mismo archivo y .\logs\D1_VALIDATION.md.

---

## 4) Verificar salud global tras un ciclo de producción

Usar después de un ciclo importante o de cambios menores en el sistema.

`powershell
Set-Location C:\comet-riobamba-v31

# 1) Revisar logs del agente principal (A/B)
Get-Content .\logs\agent.log -Tail 100

# 2) Revisar estado de D1
Get-Content .\logs\D1_PIPELINE_STATUS.md
`

Criterios mínimos:
- El log del agente debe mostrar un CICLO #N FINALIZADO sin excepciones críticas.
- D1_PIPELINE_STATUS en PASS.

---

## 5) Abrir el agente de mantenimiento de código (Claude Code local)

Usar cuando sea necesario modificar scripts o lógica del agente sin introducir dependencias de pago.

`powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_claude_local.ps1
`

Dentro de Claude Code:
- Asegurarse de estar en C:\comet-riobamba-v31.
- Usar /init si existe CLAUDE.md.
- Limitar cambios a parches mínimos, especialmente en:
  - core.agent
  - scripts de Fase A/B
  - scripts de D1 (scripts\*.ps1)

---

## Notas de operación y seguridad

- No ejecutar múltiples instancias del agente principal en paralelo (riesgo de posts duplicados y condiciones de carrera).
- No modificar MIGRATION_REPORT.md sin registrar claramente la sesión, los cambios aplicados y el estado resultante.
- No introducir nuevos proveedores de modelos de pago sin evaluar antes impacto en producción (fallos de facturación rompen la cascada).
- Para D1, evitar corridas vacías: solo ejecutar un_d1_cycle.ps1 cuando haya nuevos eventos o como parte de la validación programada.

Este runbook debe revisarse si se añaden nuevas fases (C, etc.) o se modifica la arquitectura del agente.
