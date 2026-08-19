# ══════════════════════════════════════════════════════════════
# COMET-RIOBAMBA — Watchdog Launcher (single instance)
# Vigilante en tiempo real (monitoring/watchdog.py): agente,
# proveedores LLM, saldos, errores y Telegram.
# ══════════════════════════════════════════════════════════════
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$proc = Start-Process $python -ArgumentList "-u", "monitoring\watchdog.py" -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2
if ($proc.HasExited) {
    Write-Host "ERROR: watchdog salió inmediatamente (código $($proc.ExitCode)). Revisa logs\watchdog.log." -ForegroundColor Red
    exit 1
}
Write-Host "Watchdog COMET iniciado (PID $($proc.Id)). Log: logs\watchdog.log" -ForegroundColor Green