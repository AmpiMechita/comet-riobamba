param(
    [string]$InputPath = ".\data\community_interactions.jsonl",
    [string]$SummaryPath = ".\logs\D1_DAILY_SUMMARY.md",
    [string]$OutputPath = ".\logs\D1_VALIDATION.md"
)

$requiredFields = @(
    "timestamp","source","post_id","event_type","actor_handle",
    "raw_text","sentiment_label","action_taken","operator_review"
)

$allowedSentiments = @("positive","neutral","negative")
$errors = New-Object System.Collections.Generic.List[string]

if (-not (Test-Path $InputPath)) { $errors.Add("Falta $InputPath") }
if (-not (Test-Path $SummaryPath)) { $errors.Add("Falta $SummaryPath") }

$events = @()
if ($errors.Count -eq 0) {
    $lines = Get-Content $InputPath | Where-Object { $_.Trim() -ne "" }

    foreach ($line in $lines) {
        try {
            $obj = $line | ConvertFrom-Json
            foreach ($field in $requiredFields) {
                if ($null -eq $obj.$field -or [string]::IsNullOrWhiteSpace([string]$obj.$field)) {
                    $errors.Add("Campo ausente o vacio: $field")
                }
            }
            if ($allowedSentiments -notcontains $obj.sentiment_label) {
                $errors.Add("sentiment_label invalido: $($obj.sentiment_label)")
            }
            $events += $obj
        }
        catch {
            $errors.Add("Linea JSON invalida: $line")
        }
    }

    $total = $events.Count
    $positive = @($events | Where-Object { $_.sentiment_label -eq "positive" }).Count
    $neutral  = @($events | Where-Object { $_.sentiment_label -eq "neutral" }).Count
    $negative = @($events | Where-Object { $_.sentiment_label -eq "negative" }).Count

    $summary = Get-Content $SummaryPath -Raw

    if ($summary -notmatch "Total events:\s*$total")   { $errors.Add("Resumen inconsistente: Total events") }
    if ($summary -notmatch "Positive:\s*$positive")    { $errors.Add("Resumen inconsistente: Positive") }
    if ($summary -notmatch "Neutral:\s*$neutral")      { $errors.Add("Resumen inconsistente: Neutral") }
    if ($summary -notmatch "Negative:\s*$negative")    { $errors.Add("Resumen inconsistente: Negative") }
}

$status = if ($errors.Count -eq 0) { "PASS" } else { "FAIL" }
$generated = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

$errorBlock = if ($errors.Count -eq 0) {
    "- none"
} else {
    ($errors | ForEach-Object { "- $_" }) -join "`r`n"
}

$report = @"
# D1 VALIDATION

**Generated:** $generated
**Status:** $status

## Checks
- JSONL exists
- Summary exists
- Required fields present
- Sentiment labels valid
- Summary counts consistent with JSONL

## Errors
$errorBlock
"@

Set-Content -Path $OutputPath -Value $report -Encoding UTF8
Write-Host "OK: $OutputPath creado con estado $status"
