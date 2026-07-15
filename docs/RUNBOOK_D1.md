# RUNBOOK_D1 - COMET-RIOBAMBA

## Propósito
Este runbook describe cómo operar la fase D1 (Community Intelligence) de COMET-RIOBAMBA usando comandos seguros y endurecidos.
Está pensado para operadores humanos sin necesidad de conocer todos los detalles internos del sistema.

---

## 1) Registrar un evento real de comunidad

Usar cuando haya una interacción visible nueva (comentario, reacción, respuesta, etc.).

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

- Cambiar post-000X, @usuario_real y 	exto real observado según el caso.
- SentimentLabel solo admite: positive, 
eutral, 
egative.

---

## 2) Ejecutar el ciclo completo de D1 (resumen + validación)

Usar para recalcular métricas y validar el estado de D1 después de registrar eventos.

`powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_d1_cycle.ps1
`

- Este script está endurecido.
- Solo escribe **PASS** si el resumen diario y la validación se completan correctamente.
- Si algo falla, deja D1_PIPELINE_STATUS.md en **FAIL** con un mensaje de error.

---

## 3) Consultar el estado actual del pipeline D1

Usar para verificar si el último ciclo terminó en PASS o FAIL.

`powershell
Get-Content .\logs\D1_PIPELINE_STATUS.md
`

- Buscar la línea:
  - **Status:** PASS → D1 operativo según protocolo actual.
  - **Status:** FAIL → revisar la sección ## Error en el mismo archivo.

---

## 4) Ver detalle de validación de D1

Usar cuando D1_PIPELINE_STATUS.md marque FAIL o cuando se quiera un diagnóstico más fino.

`powershell
Get-Content .\logs\D1_VALIDATION.md
`

- Revisar:
  - **Status:** PASS o FAIL.
  - La lista de errores bajo ## Errors.
- Cualquier cambio en la estructura del JSONL o en las métricas debe respetar este validador.

---

## 5) Abrir el agente de mantenimiento de código (Claude Code local)

Usar para editar scripts y lógica de COMET-RIOBAMBA de forma asistida, sin depender de modelos de pago.

`powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_claude_local.ps1
`

- Abre Claude Code sobre C:\comet-riobamba-v31 usando el modelo local qwen2.5:3b servido por Ollama.
- Dentro de Claude Code se recomienda:
  - Ejecutar /init si existe CLAUDE.md en el repo.
  - Limitar cambios a parches mínimos que mantengan D1 en estado estable.

---

## Notas operativas

- No repetir el ciclo D1 si no existen eventos nuevos; evita inflar las métricas con corridas vacías.
- Cualquier modificación a scripts de producción debe reflejarse en MIGRATION_REPORT.md y pasar por al menos un ciclo de validación (un_d1_cycle.ps1).
- Este runbook no sustituye el protocolo de evaluación (docs\EVAL_PROTOCOL.md), sino que lo operacionaliza en 5 comandos concretos.
