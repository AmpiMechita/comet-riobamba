# ══════════════════════════════════════════════════════════════
# COMET-RIOBAMBA — Production Launcher (single instance)
# ══════════════════════════════════════════════════════════════
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot
# ══════════════════════════════════════════════════════════════
# Mutex global para evitar race condition en singleton (10/09/2026)
# ══════════════════════════════════════════════════════════════
$mutexName = "Global\COMET-RIOBAMBA-SINGLETON"
$mutex = $null
$hasMutex = $false

try {
    $mutex = New-Object System.Threading.Mutex($false, $mutexName)
    if (-not $mutex.WaitOne(0)) {
        Write-Host "=== OTRA INSTANCIA DE run-prod.ps1 YA ESTÁ EJECUTÁNDOSE ===" -ForegroundColor Red
        Write-Host "Esperando a que la otra instancia termine..." -ForegroundColor Yellow
        exit 1
    }
    $hasMutex = $true
    Write-Host "Mutex adquirido correctamente" -ForegroundColor Green
} catch {
    Write-Host "ERROR al adquirir mutex: $(# ══════════════════════════════════════════════════════════════
# COMET-RIOBAMBA — Production Launcher (single instance)
# ══════════════════════════════════════════════════════════════
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

# ── Hold de mantenimiento: si data/maintenance.flag existe, no arrancar. ──
if (Test-Path "data\maintenance.flag") {
    Write-Host "maintenance.flag presente - agente NO se arranca (hold de mantenimiento)." -ForegroundColor Yellow
    Write-Host "Quitar data/maintenance.flag para reanudar." -ForegroundColor Yellow
    exit 0
}

# ── Singleton check: evita agente duplicado (27/08/2026) ──
# Además del .agent.lock, chequea procesos reales con run_agent en CommandLine
# (evita carrera donde dos run-prod arrancan simultáneo antes de escribir lock)
try {
    $existingAgents = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*run_agent.py*' }
    if ($existingAgents) {
        $pids = ($existingAgents | ForEach-Object { $_.ProcessId }) -join ', '
        Write-Host "=== AGENTE YA ESTÁ CORRIENDO ===" -ForegroundColor Yellow
        Write-Host "PID(s): $pids" -ForegroundColor Yellow
        Write-Host "No se lanza otro agente." -ForegroundColor Yellow
        exit 0
    }
} catch {
    # Si CIM falla, deja que el lock file haga el guard
}
# ── Fin singleton check ──

# ── Python del proyecto (venv local) ───────────────────────────
# Preferir .venv del proyecto; fallback a 'python' del PATH por si
# el venv no existe (setup mínimo).
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
Write-Host "Usando Python: $python" -ForegroundColor Cyan

# ── Prevent duplicate instances ──────────────────────────────
$lockFile = Join-Path $PSScriptRoot ".agent.lock"
if (Test-Path $lockFile) {
    $existingPid = (Get-Content $lockFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        Write-Host "ERROR: Agente ya corriendo (PID $existingPid)." -ForegroundColor Red
        Write-Host "  Para detener: Stop-Process -Id $existingPid -Force" -ForegroundColor Yellow
        exit 1
    } else {
        Write-Host "WARN: Lock file huerfano. Limpiando..." -ForegroundColor Yellow
        Remove-Item $lockFile -Force
    }
}

# ── Load .env ────────────────────────────────────────────────
if (Test-Path ".env") {
    Write-Host "Cargando .env..." -ForegroundColor Cyan
    Get-Content ".env" | Where-Object { $_ -match "^\s*[^#].*=" } | ForEach-Object {
        $parts = $_.Split("=", 2)
        $name = $parts[0].Trim()
        $value = $parts[1].Trim()
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
    Write-Host "Variables cargadas." -ForegroundColor Green
}

# ── Syntax check ─────────────────────────────────────────────
Write-Host "Validando sintaxis..." -ForegroundColor Cyan
& $python -m py_compile .\core\agent.py .\phases\phase_a_content.py .\services\moltbook_api_client.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error de sintaxis. Abortando." -ForegroundColor Red
    exit 1
}

# ── Write lock and start ─────────────────────────────────────
$agentProcess = Start-Process $python -ArgumentList "run_agent.py" -PassThru -NoNewWindow
$agentProcess.Id | Out-File $lockFile -Force
Write-Host "Iniciando COMET-RIOBAMBA (PID $($agentProcess.Id))..." -ForegroundColor Green

try {
    $agentProcess | Wait-Process
} finally {
    if (Test-Path $lockFile) { Remove-Item $lockFile -Force }
    Write-Host "Agente detenido. Lock limpiado." -ForegroundColor Yellow
}
.Exception.Message)" -ForegroundColor Red
    exit 1
}

# ── Hold de mantenimiento: si data/maintenance.flag existe, no arrancar. ──
if (Test-Path "data\maintenance.flag") {
    Write-Host "maintenance.flag presente - agente NO se arranca (hold de mantenimiento)." -ForegroundColor Yellow
    Write-Host "Quitar data/maintenance.flag para reanudar." -ForegroundColor Yellow
    exit 0
}

# ── Singleton check: evita agente duplicado (27/08/2026) ──
# Además del .agent.lock, chequea procesos reales con run_agent en CommandLine
# (evita carrera donde dos run-prod arrancan simultáneo antes de escribir lock)
try {
    $existingAgents = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*run_agent.py*' }
    if ($existingAgents) {
        $pids = ($existingAgents | ForEach-Object { $_.ProcessId }) -join ', '
        Write-Host "=== AGENTE YA ESTÁ CORRIENDO ===" -ForegroundColor Yellow
        Write-Host "PID(s): $pids" -ForegroundColor Yellow
        Write-Host "No se lanza otro agente." -ForegroundColor Yellow
        exit 0
    }
} catch {
    # Si CIM falla, deja que el lock file haga el guard
}
# ── Fin singleton check ──

# ── Python del proyecto (venv local) ───────────────────────────
# Preferir .venv del proyecto; fallback a 'python' del PATH por si
# el venv no existe (setup mínimo).
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
Write-Host "Usando Python: $python" -ForegroundColor Cyan

# ── Prevent duplicate instances ──────────────────────────────
$lockFile = Join-Path $PSScriptRoot ".agent.lock"
if (Test-Path $lockFile) {
    $existingPid = (Get-Content $lockFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        Write-Host "ERROR: Agente ya corriendo (PID $existingPid)." -ForegroundColor Red
        Write-Host "  Para detener: Stop-Process -Id $existingPid -Force" -ForegroundColor Yellow
        exit 1
    } else {
        Write-Host "WARN: Lock file huerfano. Limpiando..." -ForegroundColor Yellow
        Remove-Item $lockFile -Force
    }
}

# ── Load .env ────────────────────────────────────────────────
if (Test-Path ".env") {
    Write-Host "Cargando .env..." -ForegroundColor Cyan
    Get-Content ".env" | Where-Object { $_ -match "^\s*[^#].*=" } | ForEach-Object {
        $parts = $_.Split("=", 2)
        $name = $parts[0].Trim()
        $value = $parts[1].Trim()
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
    Write-Host "Variables cargadas." -ForegroundColor Green
}

# ── Syntax check ─────────────────────────────────────────────
Write-Host "Validando sintaxis..." -ForegroundColor Cyan
& $python -m py_compile .\core\agent.py .\phases\phase_a_content.py .\services\moltbook_api_client.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error de sintaxis. Abortando." -ForegroundColor Red
    exit 1
}

# ── Write lock and start ─────────────────────────────────────
$agentProcess = Start-Process $python -ArgumentList "run_agent.py" -PassThru -NoNewWindow
$agentProcess.Id | Out-File $lockFile -Force
Write-Host "Iniciando COMET-RIOBAMBA (PID $($agentProcess.Id))..." -ForegroundColor Green

try {
    $agentProcess | Wait-Process
} finally {
    if (Test-Path $lockFile) { Remove-Item $lockFile -Force }
    Write-Host "Agente detenido. Lock limpiado." -ForegroundColor Yellow
}

