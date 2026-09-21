# Lecciones Aprendidas - 2026-09-01

## 🔴 Incidente: Agente caí¬¡do por 13 minutos sin reinicio automÃ¡tico

### Resumen

El agente COMET-RIOBAMBA se cayÃ³ entre 20:20 y 20:29 del 2026-09-01 y permaneciÃ³ caÃ¬do por ~13 minutos porque el watchdog no pudo ejecutar el reinicio automÃ¡tico.

**Causa raÃ¬z**: El archivo `.agent.lock` no existÃ¬a, impidiendo que el watchdog verificara si el proceso del agente estaba vivo.

---

## 🐛 Root Cause Analysis

### Secuencia del Bug

```
1. Usuario ejecuta: python run_agent.py (directamente, sin run-prod.ps1)
   ↓
2. run-prod.ps1 NO se ejecuta → .agent.lock NO se crea
   ↓
3. Agente corre pero sin lock file (solo crea data/state/health.json)
   ↓
4. Watchdog verifica .agent.lock → no existe → lock_alive=False
   ↓
5. Agente se cae silenciosamente entre 20:20-20:29
   ↓
6. Watchdog detecta agente=False pero lock_alive=False
   ↓
7. decide_restart() retorna False (no puede verificar PID)
   ↓
8. Agente permanece caÃ¬do por 13 minutos hasta reinicio manual
```

### CÃ³digo Relevante

**watchdog.py - agent_status()**:
```python
def agent_status(lock_file: Path, health_file: Path, ...):
    lock_pid = None
    if lock_file.exists():
        # Lee PID del lock file
        lock_pid = int(pid_s[0])
    
    lock_alive = pid_alive(lock_pid)  # ← False si lock_file no existe
    
    # DecisiÃ³n de reinicio
    if lock_alive:
        # Agente corriendo: reiniciar solo si estÃ¡ congelado 2h+
        return fresh is not None and fresh > HEALTH_STUCK_RESTART_S
    
    # Si lock_alive=False, no puede determinar si debe reiniciar
```

**run-prod.ps1 - CreaciÃ³n del lock**:
```powershell
# ── Write lock and start ─────────────────────────────────────
$agentProcess = Start-Process $python -ArgumentList "run_agent.py" -PassThru -NoNewWindow
$agentProcess.Id | Out-File $lockFile -Force  # ← .agent.lock se crea aquÃ¬
Write-Host "Iniciando COMET-RIOBAMBA (PID $($agentProcess.Id))..." -ForegroundColor Green
```

---

## ✅ SoluciÃ³n Aplicada

### 1. Crear mÃ³dulo `patches` faltante

```powershell
# Copiar desde backup
Copy-Item "_cleanup_backup\patch_phase_b_pre_generation_gate.py" "patches\patch_phase_b_pre_generation_gate.py" -Force
```

### 2. Reiniciar agente manualmente

```powershell
# Matar procesos existentes
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# Iniciar agente directamente
Start-Process python -ArgumentList "run_agent.py" -NoNewWindow -PassThru
```

### 3. Crear `.agent.lock` manualmente

```powershell
# Obtener PID del agente
$agentPid = (Get-Process python | Where-Object { $_.WorkingSet -gt 10MB } | Sort-Object WorkingSet -Descending | Select-Object -First 1).Id

# Crear lock file
$agentPid | Out-File -FilePath ".agent.lock" -Encoding utf8 -NoNewline
```

### 4. Verificar watchdog

```powershell
# Esperar tick del watchdog
Start-Sleep -Seconds 60
Get-Content logs\watchdog.log -Tail 5
```

**Resultado esperado**:
```
2026-09-01 20:40:09,808 INFO watchdog tick OK: agente=True ciclos=5974 circuitos=openrouter
2026-09-01 20:41:10,348 INFO watchdog tick OK: agente=True ciclos=5974 circuitos=openrouter
2026-09-01 20:42:11,384 INFO watchdog tick OK: agente=True ciclos=5975 circuitos=openrouter
```

---

## 📋 Procedimientos Operativos

### ✅ CÃ³mo Iniciar el Agente Correctamente

**MÃ©todo recomendado (con watchdog)**:
```powershell
cd C:\comet-riobamba-v31
.\.venv\Scripts\Activate.ps1
.\run-prod.ps1
```

**MÃ©todo alternativo (sin watchdog, solo debugging)**:
```powershell
cd C:\comet-riobamba-v31
.\.venv\Scripts\Activate.ps1
python run_agent.py

# IMPORTANTE: Crear .agent.lock manualmente
$agentPid = (Get-Process python | Where-Object { $_.CommandLine -like '*run_agent.py*' } | Select-Object -First 1).Id
$agentPid | Out-File -FilePath ".agent.lock" -Encoding utf8 -NoNewline
```

### 🔍 CÃ³mo Verificar Estado del Agente

```powershell
# 1. Verificar lock file
Get-Content .agent.lock

# 2. Verificar si el PID estÃ¡ corriendo
$lockPid = Get-Content .agent.lock
Get-Process -Id $lockPid -ErrorAction SilentlyContinue

# 3. Verificar health.json
Get-Content data\state\health.json | ConvertFrom-Json | Select-Object ts, cycle_no

# 4. Verificar watchdog ticks
Get-Content logs\watchdog.log -Tail 10

# 5. Verificar logs del agente
Get-Content logs\agent.log -Tail 30
```

### 🚨 CÃ³mo Recuperar de CaÃ¬da sin Reinicio AutomÃ¡tico

```powershell
cd C:\comet-riobamba-v31

# 1. Verificar si el agente estÃ¡ caÃ¬do
Get-Content logs\watchdog.log -Tail 5
# Si muestra "agente=False" por mÃ¡s de 2 minutos → agente caÃ¬do

# 2. Verificar si .agent.lock existe
if (-not (Test-Path .agent.lock)) {
    Write-Host "❌ .agent.lock NO existe - este es el problema" -ForegroundColor Red
}

# 3. Matar procesos python existentes
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# 4. Iniciar con run-prod.ps1 (recomendado)
.\run-prod.ps1

# O iniciar directamente y crear lock manualmente
Start-Process python -ArgumentList "run_agent.py" -NoNewWindow -PassThru
Start-Sleep -Seconds 5
$agentPid = (Get-Process python | Where-Object { $_.CommandLine -like '*run_agent.py*' } | Select-Object -First 1).Id
$agentPid | Out-File -FilePath ".agent.lock" -Encoding utf8 -NoNewline

# 5. Verificar recuperaciÃ³n
Start-Sleep -Seconds 60
Get-Content logs\watchdog.log -Tail 5
# DeberÃ¬a mostrar "agente=True"
```

---

## 🛠️ Fixes Permanentes Recomendados

### 1. Documentar en README.md

Agregar secciÃ³n **"Inicio del Agente"**:

```markdown
## ðŸš€ Inicio del Agente

**Nunca ejecutar directamente**: `python run_agent.py`

**Siempre usar**: `.\run-prod.ps1`

Esto asegura que:
- `.agent.lock` se cree correctamente
- El watchdog pueda detectar caÃ¬das y reiniciar automÃ¡ticamente
- El singleton check prevenga mÃºltiples instancias
```

### 2. Agregar validaciÃ³n en run_agent.py

```python
# Al inicio de run_agent.py
from pathlib import Path

lock_file = Path(".agent.lock")
if not lock_file.exists():
    import os
    lock_file.write_text(str(os.getpid()))
    print(f"⚠️  .agent.lock no existÃ¬a - creado con PID {os.getpid()}")
```

### 3. Agregar health-check en watchdog

```python
# En run_checks() del watchdog
if not AGENT_LOCK_FILE.exists():
    logger.warning("watchdog: .agent.lock no existe - creando con PID del agente si estÃ¡ corriendo")
    # Intentar detectar PID del agente y crear lock
```

---

## 📊 MÃ©tricas del Incidente

| MÃ©trica | Valor |
|--------|-------|
| **Tiempo caÃ¬do** | ~13 minutos (20:20 - 20:33) |
| **Ú³ltimo log antes de caÃ¬da** | 20:20:29 (Phase B processing) |
| **Primer tick detectando caÃ¬da** | 20:29:13 (agente=False) |
| **Reinicios disponibles** | 1 (de 2 mÃ¡x/hora) |
| **Causa** | `.agent.lock` no existÃ¬a |
| **SoluciÃ³n** | Crear `.agent.lock` manualmente con PID 9284 |

---

## ✅ Estado Final

| Componente | Estado | Notas |
|-----------|--------|-------|
| **Agente** | ✅ Corriendo | PID 9284, 46MB RAM |
| **Watchdog** | ✅ Detectando | `agente=True` en todos los ticks |
| **`.agent.lock`** | ✅ Existe | PID 9284 |
| **`health.json`** | ✅ Existe | `data/state/health.json` |
| **Phase A** | ✅ Activa | GeneraciÃ³n de contenido |
| **Phase B** | ✅ Activa | Replies en feed |
| **ModelCascade** | ⚠️ Degradado | Usando DeepSeek (fallback) |
| **Circuit Breakers** | ⚠️ OpenRouter | Circuit breaker abierto |

---

## 📝 Referencias

- **Archivo principal**: `run_agent.py` (no `main.py`)
- **Script de producciÃ³n**: `run-prod.ps1`
- **Watchdog**: `monitoring/watchdog.py`
- **Lock file**: `.agent.lock` (raÃ¬z del proyecto)
- **Health file**: `data/state/health.json`
- **Logs del agente**: `logs/agent.log`
- **Logs del watchdog**: `logs/watchdog.log`

---

## 🎯 Checklist para Futuros Incidentes

- [ ] Verificar si `.agent.lock` existe
- [ ] Verificar si el PID del lock estÃ¡ corriendo
- [ ] Verificar `data/state/health.json` (cycle_no, ts)
- [ ] Verificar watchdog ticks (`agente=True/False`)
- [ ] Verificar logs del agente (ERROR, Traceback)
- [ ] Si el agente estÃ¡ caÃ¬do, reiniciar con `run-prod.ps1`
- [ ] Si se inicia directamente, crear `.agent.lock` manualmente
- [ ] Monitorear 10 minutos post-reinicio para confirmar estabilidad

---

**Fecha**: 2026-09-01  
**Autor**: COMET-RIOBAMBA Team  
**VersiÃ³n**: 1.0  
**Estado**: ✅ Resuelto