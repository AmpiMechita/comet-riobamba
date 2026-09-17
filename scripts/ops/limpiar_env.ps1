
# ==============================================================================
# LIMPIAR .ENV - ELIMINAR CONFIGURACIONES OBSOLETAS
# ==============================================================================

Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host "LIMPIAR .ENV - SOLO GROQ, OPENROUTER, DEEPSEEK" -ForegroundColor Cyan
Write-Host "====================================================================" -ForegroundColor Cyan

# Leer .env
$envPath = ".\.env"
Write-Host "`nLeyendo $envPath..." -ForegroundColor Yellow

if (Test-Path $envPath) {
    $lines = Get-Content $envPath -Encoding UTF8
    $originalCount = $lines.Count

    # Variables a MANTENER
    $keepPatterns = @(
        "^GROQ_",
        "^OPENROUTER_",
        "^DEEPSEEK_",
        "^MODEL_CASCADE_",
        "^AGENT_",
        "^PHASE_",
        "^TELEGRAM_",
        "^MOLTBOOK_",
        "^DATA_DIR",
        "^LOG_LEVEL"
    )

    # Variables a ELIMINAR
    $removePatterns = @(
        "^HUGGINGFACE_",
        "^CLOUDFLARE_",
        "^CEREBRAS_",
        "^ORCAROUTER_",
        "^GEMINI_",
        "^ANTHROPIC_",
        "^QUALITY_MODEL",
        "^MODEL_TIER_FLASH",
        "^MODEL_TIER_ZEN",
        "^LOCALLLM_",
        "^OLLAMA_"
    )

    # Filtrar líneas
    $keptLines = @()
    $removedLines = @()

    foreach ($line in $lines) {
        # Saltar líneas vacias o comentarios
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#")) {
            $keptLines += $line
            continue
        }

        # Verificar si es una variable a eliminar
        $shouldRemove = $false
        foreach ($pattern in $removePatterns) {
            if ($line -match $pattern) {
                $shouldRemove = $true
                $removedLines += $line
                break
            }
        }

        # Si no se elimina, mantener
        if (-not $shouldRemove) {
            $keptLines += $line
        }
    }

    # Mostrar resumen
    Write-Host "`n====================================================================" -ForegroundColor Cyan
    Write-Host "RESUMEN" -ForegroundColor Cyan
    Write-Host "====================================================================" -ForegroundColor Cyan
    Write-Host "Lí¬¬neas originales: $originalCount" -ForegroundColor White
    Write-Host "Lí¬¬neas mantenidas: $($keptLines.Count)" -ForegroundColor Green
    Write-Host "Lí¬¬neas eliminadas: $($removedLines.Count)" -ForegroundColor Red

    if ($removedLines.Count -gt 0) {
        Write-Host "`nVariables eliminadas:" -ForegroundColor Yellow
        foreach ($line in $removedLines) {
            Write-Host "  - $line" -ForegroundColor Gray
        }
    }

    # Backup
    $backupPath = "$envPath.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Write-Host "`nCreando backup: $backupPath" -ForegroundColor Yellow
    Copy-Item $envPath $backupPath

    # Guardar .env limpio
    Write-Host "Guardando $envPath limpio..." -ForegroundColor Yellow
    $keptLines | Set-Content $envPath -Encoding UTF8 -NoNewline

    Write-Host "`nâ¬¤ .env limpiado exitosamente" -ForegroundColor Green
    Write-Host "Backup guardado en: $backupPath" -ForegroundColor Green

} else {
    Write-Host "ERROR: No se encontró $envPath" -ForegroundColor Red
}

# Verificar resultado
Write-Host "`n====================================================================" -ForegroundColor Cyan
Write-Host "VERIFICACIÃ³N FINAL" -ForegroundColor Cyan
Write-Host "====================================================================" -ForegroundColor Cyan

Write-Host "`nVariables de modelos en .env:" -ForegroundColor Yellow
Get-Content $envPath | Select-String "GROQ_|OPENROUTER_|DEEPSEEK_" | ForEach-Object {
    Write-Host "  â˜ $_" -ForegroundColor Green
}
