# Operaciones COMET-RIOBAMBA

## 🚀 Inicio del Agente

### ⚠️ IMPORTANTE: Nunca ejecutar directamente

```powershell
❌ python run_agent.py  # Sin .agent.lock → watchdog no funciona
```

### ✅ Método recomendado (con watchdog)

```powershell
cd C:\comet-riobamba-v31
.\.venv\Scripts\Activate.ps1
.\run-prod.ps1
```

**Esto asegura que:**
- `.agent.lock` se cree correctamente con el PID del proceso
- El watchdog pueda detectar caÃ­das y reiniciar automáticamente
- El singleton check prevenga múltiples instancias

### 🔧 Método alternativo (solo debugging)

```powershell
cd C:\comet-riobamba-v31
.\.venv\Scripts\Activate.ps1
python run_agent.py

# IMPORTANTE: Crear .agent.lock manualmente
$agentPid = (Get-Process python | Where-Object { $_.CommandLine -like '*run_agent.py*' } | Select-Object -First 1).Id
$agentPid | Out-File -FilePath ".agent.lock" -Encoding utf8 -NoNewline
```

---

## 🔍 Verificación de Estado

### Checklist rápido

```powershell
# 1. Verificar lock file
Get-Content .agent.lock

# 2. Verificar si el PID está corriendo
$lockPid = Get-Content .agent.lock
Get-Process -Id $lockPid -ErrorAction SilentlyContinue

# 3. Verificar health.json
Get-Content data\state\health.json | ConvertFrom-Json | Select-Object ts, cycle_no

# 4. Verificar watchdog ticks
Get-Content logs\watchdog.log -Tail 10

# 5. Verificar logs del agente
Get-Content logs\agent.log -Tail 30
```

### Estado esperado

| Check | Resultado Esperado |
|-------|-------------------|
| **`.agent.lock`** | PID numérico (ej: 9284) |
| **Proceso PID** | Existe en `Get-Process` |
| **`health.json`** | `cycle_no` progresando, `ts` reciente (< 2 min) |
| **Watchdog** | `agente=True` en últimos ticks |
| **Logs agente** | Sin ERROR/Traceback recientes |

---

## 🚨 Recuperación de Caída

### Diagnóstico

```powershell
# Verificar si el agente está caído
Get-Content logs\watchdog.log -Tail 5

# Si muestra "agente=False" por más de 2 minutos → agente caído

# Verificar si .agent.lock existe
if (-not (Test-Path .agent.lock)) {
    Write-Host "❌ .agent.lock NO existe - este es el problema" -ForegroundColor Red
}
```

### Procedimiento de Recuperación

```powershell
cd C:\comet-riobamba-v31

# 1. Matar procesos python existentes
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Host "✓ Procesos detenidos" -ForegroundColor Yellow

# 2. Activar entorno
.\.venv\Scripts\Activate.ps1

# 3. Iniciar con run-prod.ps1 (recomendado)
.\run-prod.ps1

# O iniciar directamente y crear lock manualmente
Start-Process python -ArgumentList "run_agent.py" -NoNewWindow -PassThru
Start-Sleep -Seconds 5
$agentPid = (Get-Process python | Where-Object { $_.CommandLine -like '*run_agent.py*' } | Select-Object -First 1).Id
$agentPid | Out-File -FilePath ".agent.lock" -Encoding utf8 -NoNewline

# 4. Verificar recuperación
Start-Sleep -Seconds 60
Get-Content logs\watchdog.log -Tail 5
# Debería mostrar "agente=True"
```

### Verificación Post-Reinicio

```powershell
# Monitorear 10 minutos
Get-Content logs\watchdog.log -Tail 5 -Wait
Get-Content logs\agent.log -Tail 20 -Wait | Select-String "ERROR|Traceback|Phase A|Phase B"
```

---

## 🛠️ Comandos Útiles

### Ver procesos Python

```powershell
Get-Process python | Select-Object Id, CPU, WorkingSet, StartTime, CommandLine
```

### Ver estado del watchdog

```powershell
Get-Content monitoring\watchdog-state.json | ConvertFrom-Json | Select-Object restarts_1h, last_restart_ts, circuits_open
```

### Ver circuit breakers

```powershell
Get-Content data\state\global_circuit_state.json | ConvertFrom-Json
```

### Ver saldos de APIs

```powershell
# DeepSeek
Get-Content data\deepseek_spend_tracker.json

# OpenRouter
Get-Content data\openrouter_tracker.json
```

### Reiniciar watchdog

```powershell
# Matar watchdog actual
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# Iniciar watchdog
Start-Process python -ArgumentList "monitoring\watchdog.py" -NoNewWindow
```

---

## 📊 Métricas y Monitoreo

### Watchdog State

```powershell
Get-Content monitoring\watchdog-state.json | ConvertFrom-Json
```

**Campos importantes:**
- `restarts_1h`: Reinicios en la última hora (máx 2)
- `last_restart_ts`: Timestamp del último reinicio
- `circuits_open`: Lista de circuit breakers abiertos

### Cascade Telemetry

```powershell
Get-Content data\cascade_telemetry.jsonl -Tail 50 | ConvertFrom-Json
```

**Métricas:**
- `provider`: groq, openrouter, deepseek_fallback, etc.
- `success`: true/false
- `tier`: flash, classify, etc.

### Health Check

```powershell
Get-Content data\state\health.json | ConvertFrom-Json
```

**Campos importantes:**
- `cycle`: Número de ciclo actual
- `ts`: Timestamp de última actualización
- `last_error`: Último error registrado (si existe)

---

## 📝 Referencias

### Archivos Clave

| Archivo | Propósito |
|--------|----------|
| `run_agent.py` | Punto de entrada principal del agente |
| `run-prod.ps1` | Script de producción (crea .agent.lock) |
| `monitoring/watchdog.py` | Monitor de salud y reinicio automático |
| `.agent.lock` | PID del proceso del agente |
| `data/state/health.json` | Heartbeat del agente |
| `logs/agent.log` | Logs del agente |
| `logs/watchdog.log` | Logs del watchdog |

### Comandos de PowerShell

| Comando | Propósito |
|--------|----------|
| `Get-Process python` | Listar procesos Python |
| `Stop-Process -Id <PID> -Force` | Matar proceso por PID |
| `Get-Content <archivo> -Tail 20` | Ver últimas 20 líneas |
| `Select-String "pattern"` | Buscar patrón en texto |
| `ConvertFrom-Json` | Parsear JSON |

---

## 🎯 Checklist de Incidentes

### Diagnóstico Rápido (5 minutos)

- [ ] Verificar si `.agent.lock` existe
- [ ] Verificar si el PID del lock está corriendo
- [ ] Verificar `data/state/health.json` (cycle_no, ts)
- [ ] Verificar watchdog ticks (`agente=True/False`)
- [ ] Verificar logs del agente (ERROR, Traceback)

### Recuperación (10 minutos)

- [ ] Matar procesos python existentes
- [ ] Reiniciar con `run-prod.ps1` o crear lock manualmente
- [ ] Verificar que watchdog detecta `agente=True`
- [ ] Monitorear 10 minutos para confirmar estabilidad
- [ ] Documentar incidente en `docs/LECCIONES_APRENDIDAS_*.md`

---

**Última actualización**: 2026-09-01  
**Versión**: 1.0  
**Estado**: ✅ Activo