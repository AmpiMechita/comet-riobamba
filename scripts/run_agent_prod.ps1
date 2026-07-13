# scripts/run_agent_prod.ps1
 $ErrorActionPreference = "Stop"
Set-Location C:\comet-riobamba-v31

# FORZAR codificación UTF-8 en la consola para evitar caracteres raros y bloqueos
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

Write-Host "=== COMET-RIOBAMBA: Iniciando ciclo Fases A/B ===" -ForegroundColor Cyan

# Pre-flight check: Variables de entorno criticas
 $envFile = ".\.env"
if (-not (Test-Path $envFile)) { Write-Warning "No se encuentra el archivo .env"; exit 1 }
 $requiredKeys = @("DASHSCOPE_API_KEY") 
foreach ($key in $requiredKeys) {
    $keyFound = Select-String -Path $envFile -Pattern "$key=" -Quiet
    if (-not $keyFound) { Write-Host "[PRE-FLIGHT] FALLO: Falta la variable $key en el archivo .env" -ForegroundColor Red; exit 1 }
    else { Write-Host "[PRE-FLIGHT] Variable $key : PRESENTE" -ForegroundColor Green }
}

# Pre-flight check: Ollama
 $ollamaProcess = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ollamaProcess) {
    Write-Host "[PRE-FLIGHT] Ollama no detectado. Iniciando servicio..." -ForegroundColor Yellow
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

# Ejecucion del agente principal (Sin buffer, forzando UTF-8)
Write-Host "[EJECUCION] Lanzando core.agent..." -ForegroundColor Cyan
 $env:PYTHONIOENCODING="utf-8"
try {
    python -u -m core.agent
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) { throw "core.agent termino con codigo de salida: $exitCode" }
    Write-Host "=== CICLO A/B COMPLETADO EXITOSAMENTE ===" -ForegroundColor Green
} catch {
    Write-Error "FALLO CRITICO EN CORE.AGENT: $_"
    exit 1
}
