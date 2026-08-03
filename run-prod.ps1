# ══════════════════════════════════════════════════════════════
# COMET-RIOBAMBA — Production Launcher (single instance)
# ══════════════════════════════════════════════════════════════
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

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
