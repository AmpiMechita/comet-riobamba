$ErrorActionPreference = "Stop"

$summaryScript = ".\scripts\build_d1_daily_summary.ps1"
$validationScript = ".\scripts\validate_d1.ps1"
$outputPath = ".\logs\D1_PIPELINE_STATUS.md"

function Fail-And-Log {
    param(
        [string]$Message
    )
    $generated = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $report = @"
# D1 PIPELINE STATUS

**Generated:** $generated
**Status:** FAIL

## Executed
- build_d1_daily_summary.ps1 (may have failed)
- validate_d1.ps1 (may have failed)

## Error
- $Message
"@
    Set-Content -Path $outputPath -Value $report -Encoding UTF8
    Write-Error $Message
}

try {
    if (-not (Test-Path $summaryScript)) { Fail-And-Log "Falta $summaryScript" }
    if (-not (Test-Path $validationScript)) { Fail-And-Log "Falta $validationScript" }

    powershell -ExecutionPolicy Bypass -File $summaryScript | Out-Null
    powershell -ExecutionPolicy Bypass -File $validationScript | Out-Null

    if (-not (Test-Path ".\logs\D1_VALIDATION.md")) {
        Fail-And-Log "Falta .\logs\D1_VALIDATION.md despues de validar"
    }

    $validation = Get-Content ".\logs\D1_VALIDATION.md" -Raw

    if ($validation -notmatch "\*\*Status:\*\*\s*PASS") {
        Fail-And-Log "D1_VALIDATION.md no esta en PASS"
    }

    $generated = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    $report = @"
# D1 PIPELINE STATUS

**Generated:** $generated
**Status:** PASS

## Executed
- build_d1_daily_summary.ps1
- validate_d1.ps1
"@

    Set-Content -Path $outputPath -Value $report -Encoding UTF8
    Write-Host "OK: $outputPath creado con estado PASS"
}
catch {
    Fail-And-Log ("Excepcion no controlada en run_d1_cycle.ps1: " + $_.Exception.Message)
}
