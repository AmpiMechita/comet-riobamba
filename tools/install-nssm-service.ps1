# -*- coding: utf-8 -*-
# Instala Comet Riobamba como servicio de Windows via NSSM.
# REQUIERE: ejecutar en PowerShell como Administrador.

$ErrorActionPreference = 'Stop'

# ── Check elevation ──
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: Este script requiere permisos de Administrador." -ForegroundColor Red
    Write-Host "Abri PowerShell como Administrador y volve a ejecutar." -ForegroundColor Yellow
    exit 1
}

$NSSM = 'C:\comet-riobamba-v31\tools\nssm.exe'
$APPDIR = 'C:\comet-riobamba-v31'
$SERVICE_NAME = 'CometRiobamba'

if (-not (Test-Path $NSSM)) {
    Write-Host "ERROR: No se encuentra $NSSM" -ForegroundColor Red
    exit 1
}

$PYTHON = (Get-Command python).Source
Write-Host "Python: $PYTHON"
Write-Host "NSSM:   $NSSM"
Write-Host "AppDir: $APPDIR"
Write-Host "Service: $SERVICE_NAME"
Write-Host ""

# ── Remove existing service if present ──
$existing = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Servicio $SERVICE_NAME ya existe. Deteniendo y eliminando..." -ForegroundColor Yellow
    & $NSSM stop $SERVICE_NAME 2>&1 | Out-Null
    Start-Sleep -Seconds 3
    & $NSSM remove $SERVICE_NAME confirm 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    Write-Host "Servicio viejo eliminado."
    Write-Host ""
}

# ── Install ──
Write-Host "=== Instalando servicio ===" -ForegroundColor Cyan
& $NSSM install $SERVICE_NAME $PYTHON run_agent.py
if ($LASTEXITCODE -ne 0) { throw "nssm install falló (exit $LASTEXITCODE)" }

Write-Host "=== Configurando ===" -ForegroundColor Cyan
& $NSSM set $SERVICE_NAME AppDirectory $APPDIR
& $NSSM set $SERVICE_NAME Start SERVICE_AUTO_START
& $NSSM set $SERVICE_NAME AppStdout "$APPDIR\logs\service_stdout.log"
& $NSSM set $SERVICE_NAME AppStderr "$APPDIR\logs\service_stderr.log"
& $NSSM set $SERVICE_NAME AppRotateFiles 1
& $NSSM set $SERVICE_NAME AppRotateBytes 5242880
& $NSSM set $SERVICE_NAME AppExit Default Restart
& $NSSM set $SERVICE_NAME AppRestartDelay 5000
# Force UTF-8 in stdout/stderr (Python por defecto usa cp1252 en Windows,
# lo que rompe print() con emojis cuando el servicio corre sin consola)
& $NSSM set $SERVICE_NAME AppEnvironmentExtra "PYTHONIOENCODING=utf-8"
& $NSSM set $SERVICE_NAME Description "COMET-RIOBAMBA autonomous agent"

# ── Start ──
Write-Host "=== Arrancando servicio ===" -ForegroundColor Cyan
& $NSSM start $SERVICE_NAME

Start-Sleep -Seconds 8

# ── Verify ──
Write-Host ""
Write-Host "=== Verificacion ===" -ForegroundColor Cyan
Get-Service $SERVICE_NAME | Format-Table Name, Status, StartType -AutoSize

Write-Host ""
Write-Host "=== Proceso ===" -ForegroundColor Cyan
Get-Process -Name python -ErrorAction SilentlyContinue |
    Select-Object Id, StartTime, @{N='CPU_s';E={[math]::Round($_.CPU,1)}},
        @{N='WS_MB';E={[math]::Round($_.WorkingSet/1MB,1)}} | Format-Table -AutoSize

Write-Host ""
Write-Host "=== Primeras lineas del log del servicio ===" -ForegroundColor Cyan
Start-Sleep -Seconds 5
if (Test-Path "$APPDIR\logs\service_stdout.log") {
    Get-Content "$APPDIR\logs\service_stdout.log" -Tail 20
} else {
    Write-Host "(service_stdout.log aun no existe)"
}

Write-Host ""
Write-Host "=== Comandos utiles ===" -ForegroundColor Green
Write-Host "  nssm status CometRiobamba    # estado"
Write-Host "  nssm stop CometRiobamba      # detener"
Write-Host "  nssm start CometRiobamba     # arrancar"
Write-Host "  nssm restart CometRiobamba   # reiniciar"
Write-Host "  nssm remove CometRiobamba confirm  # desinstalar"
Write-Host ""
Write-Host "Listo. El agente arrancara automaticamente al bootear Windows." -ForegroundColor Green