# ══════════════════════════════════════════════════════════════
# COMET-RIOBAMBA — Informe de estado (para operador y asistente)
# Salida en una sola pasada: agente, watchdog, circuitos, saldos,
# errores, alertas recientes y últimos mensajes Telegram enviados.
# ══════════════════════════════════════════════════════════════
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$root = Split-Path -Parent $PSScriptRoot
$now = Get-Date

# ── Agente ─────────────────────────────────────────────────────
$healthFile = Join-Path $root "data\state\health.json"
$agentState = "DESCONOCIDO"
$healthInfo = ""
$agentLockAlive = $false
$lockFileAgent = Join-Path $root ".agent.lock"
if (Test-Path $lockFileAgent) {
    $pidA = (Get-Content $lockFileAgent | Select-Object -First 1).Trim()
    if ($pidA -match "^\d+$" -and (Get-Process -Id ([int]$pidA) -ErrorAction SilentlyContinue)) {
        $agentLockAlive = $true
    }
}
if (Test-Path $healthFile) {
    $freshS = [int]((Get-Date) - (Get-Item $healthFile).LastWriteTime).TotalSeconds
    $h = Get-Content $healthFile -Raw | ConvertFrom-Json
    $cycle = $h.cycle
    # Misma lógica que el watchdog: ciclo reciente (<5min) → vivo;
    # si no, lock vivo + health < 1h → vivo.
    if ($freshS -lt 300) { $agentState = "VIVO" }
    elseif ($agentLockAlive -and $freshS -lt 3600) { $agentState = "VIVO (lock, health lento)" }
    else { $agentState = "SIN LATIDO" }
    $healthInfo = "ciclo $cycle · health hace $freshS s · lock $($agentLockAlive)"
} else {
    $agentState = "SIN health.json"
}

# ── Watchdog ───────────────────────────────────────────────────
$lockFile = Join-Path $root ".watchdog.lock"
$wdState = "DETENIDO"
$wdPid = ""
if (Test-Path $lockFile) {
    $wdPid = (Get-Content $lockFile | Select-Object -First 1).Trim()
    if ($wdPid -match "^\d+$" -and (Get-Process -Id ([int]$wdPid) -ErrorAction SilentlyContinue)) {
        $wdState = "VIVO"
    }
}
$stateFile = Join-Path $PSScriptRoot "watchdog-state.json"
$wdInfo = ""
if (Test-Path $stateFile) {
    $st = Get-Content $stateFile -Raw | ConvertFrom-Json
    $wdInfo = "tick $($st.ts)"
}

# ── Circuitos / errores / degradado ────────────────────────────
$circuits = ""
$errors1h = 0
if (Test-Path (Join-Path $root "data\cascade_telemetry.jsonl")) {
    $cutoff = (Get-Date).AddMinutes(-10)
    $fails = @{}
    foreach ($line in (Get-Content (Join-Path $root "data\cascade_telemetry.jsonl") -Tail 400)) {
        try {
            $ev = $line | ConvertFrom-Json
            $ts = [DateTime]::Parse($ev.ts)
            if ($ts -lt $cutoff) { continue }
            $ok = $ev.success -eq $true -or $ev.success -eq "ok"
            if (-not $ok) {
                $name = if ($ev.provider) { $ev.provider } else { $ev.tier }
                if (-not $fails.ContainsKey($name)) { $fails[$name] = 0 }
                $fails[$name]++
            }
        } catch { }
    }
    $open = @($fails.GetEnumerator() | Where-Object { $_.Value -ge 3 })
    if ($open.Count -gt 0) {
        $circuits = ($open | ForEach-Object { "$($_.Key) ($($_.Value) fallos)" }) -join ", "
    } else {
        $circuits = "ninguno"
    }
}
$agentLog = Join-Path $root "logs\agent.log"
if (Test-Path $agentLog) {
    $cutoff = (Get-Date).AddHours(-1)
    foreach ($line in (Get-Content $agentLog -Tail 2000)) {
        if ($line -match " ERROR | CRITICAL " -and $line.Length -ge 19) {
            try {
                if ([DateTime]::ParseExact($line.Substring(0, 19), "yyyy-MM-dd HH:mm:ss", $null) -gt $cutoff) { $errors1h++ }
            } catch { }
        }
    }
}
$degraded = "no"
$degFile = Join-Path $root "data\degraded_mode_state.json"
if (Test-Path $degFile) {
    try { if ((Get-Content $degFile -Raw | ConvertFrom-Json).is_degraded) { $degraded = "SI" } } catch { }
}

# ── Saldos (último chequeo del watchdog) ───────────────────────
$saldo = "sin dato"
if (Test-Path $stateFile) {
    $st = Get-Content $stateFile -Raw | ConvertFrom-Json
    if ($st.balances) {
        $parts = @()
        if ($null -ne $st.balances.deepseek) { $parts += "DeepSeek `$$([math]::Round($st.balances.deepseek, 2))" }
        if ($null -ne $st.balances.openrouter) { $parts += "OpenRouter `$$([math]::Round($st.balances.openrouter, 2))" }
        if ($parts.Count -gt 0) { $saldo = $parts -join " | " }
    }
}

# ── Alertas recientes (24h) ────────────────────────────────────
$alerts = @()
$alertsFile = Join-Path $PSScriptRoot "alerts.jsonl"
if (Test-Path $alertsFile) {
    $alerts = @(Get-Content $alertsFile | ForEach-Object {
        try { $_ | ConvertFrom-Json } catch { $null }
    } | Where-Object { $_ -and $_.ts -gt $now.AddDays(-1).ToString("o") } | Select-Object -Last 8)
}

# ── Últimos mensajes enviados al móvil ─────────────────────────
$tgSent = @()
$tgFile = Join-Path $PSScriptRoot "telegram-sent.log"
if (Test-Path $tgFile) {
    $tgSent = @(Get-Content $tgFile -Tail 4)
}

# ── Salida ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "COMET-RIOBAMBA — ESTADO ($($now.ToString('yyyy-MM-dd HH:mm')))" -ForegroundColor Cyan
Write-Host ("=" * 46) -ForegroundColor Cyan
$agColor = if ($agentState -eq "VIVO") { "Green" } else { "Red" }
Write-Host ("Agente:     {0} · {1}" -f $agentState, $healthInfo) -ForegroundColor $agColor
$wdColor = if ($wdState -eq "VIVO") { "Green" } else { "Red" }
Write-Host ("Watchdog:   {0} (PID {1}) {2}" -f $wdState, $wdPid, $wdInfo) -ForegroundColor $wdColor
Write-Host ("Circuitos:  {0}" -f $circuits)
Write-Host ("Errores 1h: {0}" -f $errors1h)
Write-Host ("Saldos:     {0}" -f $saldo)
Write-Host ("Degradado:  {0}" -f $degraded)
Write-Host ""
Write-Host "ALERTAS RECIENTES (24h):" -ForegroundColor Yellow
if ($alerts.Count -gt 0) {
    foreach ($a in $alerts) {
        $sevColor = if ($a.severity -eq "critical") { "Red" } elseif ($a.severity -eq "warning") { "Yellow" } else { "Gray" }
        $aTs = if ($a.ts -is [datetime]) { $a.ts.ToString("yyyy-MM-dd HH:mm") } else { "$($a.ts)".Substring(0, [Math]::Min(16, "$($a.ts)".Length)) }
        Write-Host ("  [{0}] {1} {2}" -f $aTs, $a.type, $a.summary) -ForegroundColor $sevColor
    }
} else {
    Write-Host "  (sin alertas)"
}
Write-Host ""
Write-Host "ÚLTIMOS MENSAJES AL MÓVIL:" -ForegroundColor Yellow
foreach ($t in $tgSent) { Write-Host ("  " + $t.Substring(0, [Math]::Min($t.Length, 110))) }
Write-Host ""