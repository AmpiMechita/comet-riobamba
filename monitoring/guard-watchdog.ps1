# ══════════════════════════════════════════════════════════════
# COMET-RIOBAMBA — Guard del watchdog (Task Scheduler, cada 5 min)
# Si el watchdog no está corriendo, lo relanza. Sin acción si vive.
# ══════════════════════════════════════════════════════════════
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$lockFile = Join-Path $root ".watchdog.lock"

function Test-WatchdogRunning {
    # Señal fuerte: el lock pid del watchdog. Get-Process ve procesos en
    # cualquier sesión (no CIM CommandLine), así que basta con esto.
    # Un lock con pid muerto = watchdog caído (el .lock se borra solo en
    # salidas limpias; si quedó, el pid está muerto → relanzar).
    if (Test-Path $lockFile) {
        $pidStr = (Get-Content $lockFile | Select-Object -First 1).Trim()
        if ($pidStr -match "^\d+$" -and (Get-Process -Id ([int]$pidStr) -ErrorAction SilentlyContinue)) {
            return $true
        }
    }
    return $false
}

if (Test-WatchdogRunning) { exit 0 }

# Watchdog caído → relanzar
try {
    $proc = Start-Process $python -ArgumentList "-u", "monitoring\watchdog.py" -WorkingDirectory $root -PassThru -WindowStyle Hidden
    Add-Content -Path (Join-Path $PSScriptRoot "health-check.log") -Encoding utf8 `
        -Value "$([DateTime]::Now.ToString('o')) | WATCHDOG-GUARD: relanzado PID $($proc.Id)"
} catch {
    Add-Content -Path (Join-Path $PSScriptRoot "health-check.log") -Encoding utf8 `
        -Value "$([DateTime]::Now.ToString('o')) | WATCHDOG-GUARD-FAIL: $($_.Exception.Message)"
}