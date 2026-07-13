param(
    [string]$InputPath = ".\data\community_interactions.jsonl",
    [string]$OutputPath = ".\logs\D1_DAILY_SUMMARY.md"
)

$lines = Get-Content $InputPath -ErrorAction Stop | Where-Object { $_.Trim() -ne "" }
$events = $lines | ForEach-Object { $_ | ConvertFrom-Json }

$total = $events.Count
$positive = @($events | Where-Object { $_.sentiment_label -eq "positive" }).Count
$neutral  = @($events | Where-Object { $_.sentiment_label -eq "neutral" }).Count
$negative = @($events | Where-Object { $_.sentiment_label -eq "negative" }).Count

$byType = $events | Group-Object event_type | Sort-Object Name
$typeLines = if ($byType.Count -gt 0) {
    ($byType | ForEach-Object { "- $($_.Name): $($_.Count)" }) -join "`r`n"
} else {
    "- sin eventos"
}

$now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$report = @"
# D1 DAILY SUMMARY

**Generated:** $now

## Metrics
- Total events: $total
- Positive: $positive
- Neutral: $neutral
- Negative: $negative

## Event Types
$typeLines
"@

Set-Content -Path $OutputPath -Value $report -Encoding UTF8
Write-Host "OK: $OutputPath creado"
