param(
    [switch]$VerboseRun
)

# COMET-RIOBAMBA informe diario de salud (06:00 via Task Scheduler)
# Resumen del dia anterior (metrics/*.json), tendencia 7 dias,
# errores/stall/circuitos recopilados por health-check, y envio
# a Telegram si TELEGRAM_DAILY_REPORT=1. Salida: monitoring/daily-YYYY-MM-DD.md

$ErrorActionPreference = "Stop"
$script:root = Split-Path -Parent $PSScriptRoot
$today = Get-Date
$targetDate = $today.AddDays(-1).ToString("yyyy-MM-dd")

# ── Registrar el trend de karma del dia (persistente en karma_trend.jsonl) ──
try {
    $py = Join-Path $script:root ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) { $py = "python" }
    & $py -m scripts.karma_roi_report --record --date $targetDate 2>$null | Out-Null
} catch {
    # no romper el reporte si falla el registro del trend
}

function Get-TelegramEnv {
    $envFile = Join-Path $script:root ".env"
    $result = @{ enabled = $false; token = ""; chat = "" }
    if (-not (Test-Path $envFile)) { return $result }
    $vars = @{}
    foreach ($l in (Get-Content $envFile | Where-Object { $_ -match "^\s*[^#].*=" })) {
        $kv = $l.Split("=", 2)
        $vars[$kv[0].Trim()] = $kv[1].Trim()
    }
    if ($vars.ContainsKey("TELEGRAM_DAILY_REPORT") -and $vars["TELEGRAM_DAILY_REPORT"] -eq "1") { $result.enabled = $true }
    if ($vars.ContainsKey("TELEGRAM_BOT_TOKEN")) { $result.token = $vars["TELEGRAM_BOT_TOKEN"] }
    if ($vars.ContainsKey("TELEGRAM_CHAT_ID")) { $result.chat = $vars["TELEGRAM_CHAT_ID"] }
    return $result
}

function Send-Telegram {
    param([string]$Message, [hashtable]$Tg)
    if (-not $Tg.enabled -or -not $Tg.token -or -not $Tg.chat) { return }
    try {
        $uri = "https://api.telegram.org/bot$($Tg.token)/sendMessage"
        $body = @{ chat_id = $Tg.chat; text = $Message; disable_notification = $false }
        Invoke-RestMethod -Uri $uri -Method Post -Body $body -TimeoutSec 20 | Out-Null
    } catch {
        Add-Content -Path (Join-Path $PSScriptRoot "health-check.log") -Value "TELEGRAM-FAIL: $($_.Exception.Message)"
    }
}

$md = [System.Text.StringBuilder]::new()
[void]$md.AppendLine("# Informe de salud COMET-RIOBAMBA - $targetDate")
[void]$md.AppendLine("Generado: $($today.ToString('yyyy-MM-dd HH:mm'))")
[void]$md.AppendLine("")

# ── 1. Metricas del dia objetivo ──────────────────────────────────────
$dayMetrics = Join-Path $script:root "data\metrics\$targetDate.json"
if (Test-Path $dayMetrics) {
    try {
        $m = Get-Content $dayMetrics -Raw | ConvertFrom-Json
        [void]$md.AppendLine("## Resumen del dia")
        [void]$md.AppendLine("- Ciclos ejecutados: **$($m.cycle_count)**")
        [void]$md.AppendLine("- Posts publicados: **$($m.posts_published)** (skipped por limite diario: $($m.posts_skipped_daily_limit))")
        [void]$md.AppendLine("- Comments publicados: **$($m.comments_published)** (skipped: low_relevance=$($m.comments_skipped_low_relevance), near_dup=$($m.comments_near_duplicate_skipped), outbox_retried=$($m.comment_outbox_retried))")
        [void]$md.AppendLine("- Phase C runs: $($m.phase_c_runs) | Outbox posts retried: $($m.outbox_posts_retried)")
        [void]$md.AppendLine("- Errores totales: **$($m.errors_total)** | fallos consecutivos: $($m.consecutive_failures)")
        $avgS = if ($m.last_cycle_duration_count -gt 0) { [math]::Round($m.last_cycle_duration_avg_s) } else { 0 }
        [void]$md.AppendLine("- Duracion media de ciclo: $avgS s")
        
        # Inbound Watchlist del dia
        $inboundFile = Join-Path $script:root "data\watchlist_inbound_today.json"
        if (Test-Path $inboundFile) {
            try {
                $inbound = Get-Content $inboundFile -Raw | ConvertFrom-Json
                if ($inbound.date -eq $targetDate -and $inbound.counts) {
                    $authors = @($inbound.counts.PSObject.Properties | ForEach-Object { "$($_.Name) ($($_.Value))" })
                    if ($authors.Count -gt 0) {
                        [void]$md.AppendLine("- Watchlist Inbound: $($authors -join ', ')")
                    }
                }
            } catch { }
        }
        [void]$md.AppendLine("")
    } catch {
        [void]$md.AppendLine("> Error leyendo metricas del dia: $($_.Exception.Message)")
    }
} else {
    [void]$md.AppendLine("## Resumen del dia")
    [void]$md.AppendLine("> No hay metricas para $targetDate (posible dia sin actividad o reinicio).")
}
[void]$md.AppendLine("")

# ── 2. Tendencia 7 dias ───────────────────────────────────────────────
[void]$md.AppendLine("## Tendencia 7 dias")
[void]$md.AppendLine("| Fecha | Ciclos | Posts | Comments | Errores | Dur.media(s) |")
[void]$md.AppendLine("|---|---|---|---|---|---|")
$d = $today.AddDays(-7)
while ($d -lt $today) {
    $dateStr = $d.ToString("yyyy-MM-dd")
    $f = Join-Path $script:root "data\metrics\$dateStr.json"
    if (Test-Path $f) {
        try {
            $mm = Get-Content $f -Raw | ConvertFrom-Json
            $avg = if ($mm.last_cycle_duration_count -gt 0) { [math]::Round($mm.last_cycle_duration_avg_s) } else { 0 }
            [void]$md.AppendLine("| $dateStr | $($mm.cycle_count) | $($mm.posts_published) | $($mm.comments_published) | $($mm.errors_total) | $avg |")
        } catch {
            [void]$md.AppendLine("| $dateStr | (error leyendo) | | | | |")
        }
    } else {
        [void]$md.AppendLine("| $dateStr | sin datos | | | | |")
    }
    $d = $d.AddDays(1)
}
[void]$md.AppendLine("")

# ── 2b. Retorno de karma (tendencia) ─────────────────────────────────
$karmaTrend = Join-Path $script:root "monitoring\karma_trend.jsonl"
[void]$md.AppendLine("## Karma (retorno)")
if (Test-Path $karmaTrend) {
    try {
        $krows = @(Get-Content $karmaTrend | ForEach-Object {
            try { $_ | ConvertFrom-Json } catch { $null }
        } | Where-Object { $_ })
        if ($krows.Count -gt 0) {
            foreach ($kr in ($krows | Sort-Object date -Descending | Select-Object -First 5)) {
                $kd = if ($null -ne $kr.karma_delta) { $kr.karma_delta } else { "-" }
                $upc = if ($null -ne $kr.roi_upvotes_per_comment) { $kr.roi_upvotes_per_comment } else { "-" }
                [void]$md.AppendLine("- $($kr.date): karma $kd | posts $($kr.posts) | upv/com $upc | inbound $($kr.inbound_watchlist)")
            }
        } else {
            [void]$md.AppendLine("- Sin datos de tendencia de karma todavia.")
        }
    } catch {
        [void]$md.AppendLine("- Error leyendo tendencia de karma: $($_.Exception.Message)")
    }
} else {
    [void]$md.AppendLine("- Sin tendencia de karma registrada (corre `python -m scripts.karma_roi_report --record`).")
}
[void]$md.AppendLine("")

# ── 3. Incidentes del dia (alerts.jsonl) ──────────────────────────────
$alertsFile = Join-Path $PSScriptRoot "alerts.jsonl"
$dayAlerts = @()
if (Test-Path $alertsFile) {
    $dayAlerts = @(Get-Content $alertsFile | ForEach-Object {
        try { $_ | ConvertFrom-Json } catch { $null }
    } | Where-Object { $_ -and $_.ts -like "$targetDate*" })
}
[void]$md.AppendLine("## Incidentes del dia (alertas del health-check)")
if ($dayAlerts.Count -gt 0) {
    foreach ($a in $dayAlerts) {
        [void]$md.AppendLine("- **$($a.severity.ToUpper())** [$($a.type)] $($a.summary) ($($a.ts))")
    }
} else {
    [void]$md.AppendLine("- Ninguna alerta registrada.")
}
[void]$md.AppendLine("")

# ── 4. Stop events (del log) ──────────────────────────────────────────
$stopEvents = @()
$agentLog = Join-Path $script:root "logs\agent.log"
if (Test-Path $agentLog) {
    $stopEvents = @(Get-Content $agentLog -Tail 4000 -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "shutdown|graceful stop|stop.flag|AGENT DETENIDO|Started|Iniciando" -and $_ -like "*$targetDate*" })
}
[void]$md.AppendLine("## Eventos de vida")
if ($stopEvents.Count -gt 0) {
    foreach ($e in $stopEvents | Select-Object -First 15) {
        [void]$md.AppendLine('- `$e`')
    }
} else {
    [void]$md.AppendLine("- Sin eventos de inicio/parada detectados en el log principal.")
}
[void]$md.AppendLine("")

# ── 5. Evaluacion general ─────────────────────────────────────────────
$errors = 0
$stallMax = 0
if (Test-Path (Join-Path $script:root "data\metrics\$targetDate.json")) {
    $em = Get-Content (Join-Path $script:root "data\metrics\$targetDate.json") -Raw | ConvertFrom-Json
    $errors = $em.errors_total
    $snap = Join-Path $PSScriptRoot "snapshots.jsonl"
    if (Test-Path $snap) {
        $stallMax = @(Get-Content $snap | ForEach-Object {
            try { $_ | ConvertFrom-Json } catch { $null }
        } | Where-Object { $_ -and $_.ts -like "$targetDate*" -and $null -ne $_.stall } |
            Measure-Object -Property stall -Maximum).Maximum
    }
}

$verdict = "SALUDABLE"
$verdictColor = "verde"
if ($errors -gt 10 -or $stallMax -ge 60 -or $dayAlerts.Count -ge 3) {
    $verdict = "ATENCION"
    $verdictColor = "amarillo"
}
if ($errors -gt 50) {
    $verdict = "REVISION"
    $verdictColor = "rojo"
}
if (-not (Test-Path $dayMetrics)) {
    $verdict = "SIN ACTIVIDAD (sin metricas del dia)"
    $verdictColor = "amarillo"
}
[void]$md.AppendLine("## Veredicto: $verdict")
[void]$md.AppendLine("- Errores del dia: $errors | Stall max observado: $stallMax ciclos | Alertas health: $($dayAlerts.Count)")

# ── 6. Retencion (purga > 14 dias) ────────────────────────────────────
$cutoff14 = (Get-Date).AddDays(-14).ToString("o")
foreach ($f in @("snapshots.jsonl", "alerts.jsonl")) {
    $p = Join-Path $PSScriptRoot $f
    if (Test-Path $p) {
        $kept = @(Get-Content $p | ForEach-Object {
            try {
                $e = $_ | ConvertFrom-Json
                if ($e.ts -and $e.ts -ge $cutoff14) { $_ } else { $null }
            } catch { $null }
        })
        $kept | Set-Content -Path $p -Encoding utf8
    }
}

# ── 7. Persistencia ───────────────────────────────────────────────────
$reportFile = Join-Path $PSScriptRoot "daily-$targetDate.md"
$md.ToString() | Set-Content -Path $reportFile -Encoding utf8

# ── 7. Envio Telegram ─────────────────────────────────────────────────
$tg = Get-TelegramEnv
if ($tg.enabled) {
    $msg = "[Informe COMET $targetDate]`n`n" + (($md.ToString() -split "`n" | Where-Object {
        $_ -and -not $_.StartsWith("#") -and -not $_.StartsWith("|") -and -not $_.StartsWith('- `') -and -not $_.StartsWith("---")
    }) -join "`n")
    Send-Telegram -Message $msg -Tg $tg
}

if ($VerboseRun) { $md.ToString() } else { "Informe guardado en $reportFile" }

