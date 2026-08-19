param(
    [switch]$VerboseRun
)

# COMET-RIOBAMBA health-check rapido (cada 10 min via Task Scheduler)
# Mide: proceso vivo, frescura del ciclo, stall de feed, errores en log,
# circuitos de tier abiertos, intervenciones de auto-diagnostico, y
# trafico de publicacion. Emite monitoring/latest.json y monitorea
# telegrafo las alertas criticas (sin spam: cooldown 1h por tipo).

$ErrorActionPreference = "Stop"
$script:root = Split-Path -Parent $PSScriptRoot
if (-not $VerboseRun) {
    $script:rootLog = Join-Path $PSScriptRoot "health-check.log"
    Start-Transcript -Path $script:rootLog -Append -NoClobber | Out-Null
}

function Get-TelegramEnv {
    $envFile = Join-Path $script:root ".env"
    $result = @{ enabled = $false; token = ""; chat = "" }
    if (-not (Test-Path $envFile)) { return $result }
    $lines = Get-Content $envFile | Where-Object { $_ -match "^\s*[^#].*=" }
    $vars = @{}
    foreach ($l in $lines) {
        $kv = $l.Split("=", 2)
        $vars[$kv[0].Trim()] = $kv[1].Trim()
    }
    if ($vars.ContainsKey("TELEGRAM_ALERTS_ENABLED") -and $vars["TELEGRAM_ALERTS_ENABLED"] -eq "1") {
        $result.enabled = $true
    }
    if ($vars.ContainsKey("TELEGRAM_BOT_TOKEN")) { $result.token = $vars["TELEGRAM_BOT_TOKEN"] }
    if ($vars.ContainsKey("TELEGRAM_CHAT_ID")) { $result.chat = $vars["TELEGRAM_CHAT_ID"] }
    return $result
}

function Send-TelegramAlert {
    param([string]$Message, [hashtable]$Tg)
    if (-not $Tg.enabled -or -not $Tg.token -or -not $Tg.chat) { return }
    try {
        $uri = "https://api.telegram.org/bot$($Tg.token)/sendMessage"
        $body = @{ chat_id = $Tg.chat; text = $Message; disable_notification = $false }
        Invoke-RestMethod -Uri $uri -Method Post -Body $body -TimeoutSec 20 | Out-Null
        Add-Content -Path (Join-Path $PSScriptRoot "telegram-sent.log") -Encoding utf8 -Value "$([DateTime]::UtcNow.ToString('o')) | $Message"
    } catch {
        Add-Content -Path (Join-Path $PSScriptRoot "health-check.log") -Encoding utf8 -Value "TELEGRAM-FAIL: $($_.Exception.Message)"
    }
}

function Test-AlertCooldown {
    param([string]$Type, [int]$Minutes = 60)
    $alertsFile = Join-Path $PSScriptRoot "alerts.jsonl"
    if (Test-Path $alertsFile) {
        $last = Get-Content $alertsFile -Tail 50 | ForEach-Object {
            try { $_ | ConvertFrom-Json } catch { $null }
        } | Where-Object { $_.type -eq $Type } | Select-Object -Last 1
if ($last) {
            # ConvertFrom-Json ya convierte ts ISO en [datetime]; NO re-parsear
            # (Parse([datetime]) lo serializa en formato local y explota).
            $lastT = if ($last.ts -is [datetime]) { $last.ts } else { [DateTime]::Parse($last.ts) }
            if (((Get-Date) - $lastT).TotalMinutes -lt $Minutes) { return $false }
        }
    }
    return $true
}

function Write-Alert {
    param([string]$Type, [string]$Severity, [string]$Summary, [hashtable]$Tg, [string]$TgMessage = "")
    $entry = [ordered]@{
        ts         = (Get-Date).ToString("o")
        type       = $Type
        severity   = $Severity
        summary    = $Summary
    }
    Add-Content -Path (Join-Path $PSScriptRoot "alerts.jsonl") -Encoding utf8 -Value (($entry | ConvertTo-Json -Compress))
    if ($TgMessage -and (Test-AlertCooldown $Type)) {
        Send-TelegramAlert -Message "[ALERTA COMET] $TgMessage" -Tg $Tg
    }
}

$report = [ordered]@{
    ts          = (Get-Date).ToString("o")
    agent_up    = $false
    cycle_no    = $null
    cycle_age_s = $null
    stall       = $null
    errors_1h   = 0
    circuits    = @()
    diagnosis   = $null
    karma       = $null
    summary     = "TBD"
    severity    = "ok"
    checks      = [ordered]@{}
}

# ── 1. Proceso vivo ────────────────────────────────────────────────────
$healthFile = Join-Path $script:root "data\state\health.json"
$healthFreshS = 999999
if (Test-Path $healthFile) { $healthFreshS = [int]((Get-Date) - (Get-Item $healthFile).LastWriteTime).TotalSeconds }

$agentProcs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "run_agent\.py" })
$lockFile = Join-Path $script:root ".agent.lock"
$lockPid = $null
if (Test-Path $lockFile) {
    $lockContent = (Get-Content $lockFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($lockContent -match "^\d+$") { $lockPid = [int]$lockContent }
}

$agentUp = $false
# El lock es la autoridad: si su PID vive, el agente esta corriendo.
# (Fix 18/08/2026: CIM no ve procesos de otra sesion/privilegios y los
# ciclos del agente toman ~7 min, por lo que health.json puede tener hasta
# ~7 min de edad; el fallback de 300s generaba falsos "Agente NO corre".)
if ($lockPid -and (Get-Process -Id $lockPid -ErrorAction SilentlyContinue)) {
    $agentUp = $true
} elseif ($agentProcs.Count -gt 0) {
    $agentUp = $true
} elseif ($healthFreshS -lt 900) {
    $agentUp = $true
}
$report.agent_up = $agentUp
$report.checks["process"] = [ordered]@{
    run_agent_procs = $agentProcs.Count
    lock_pid        = $lockPid
    health_fresh_s  = $healthFreshS
}

# ── 2. Frescura del ciclo ──────────────────────────────────────────────
$healthFile = Join-Path $script:root "data\state\health.json"
$cycleAgeS = $null
if (Test-Path $healthFile) {
    try {
        $health = Get-Content $healthFile -Raw | ConvertFrom-Json
        $report.cycle_no = $health.cycle
        $cycleAgeS = [int]((Get-Date) - (Get-Item $healthFile).LastWriteTime).TotalSeconds
        $report.cycle_age_s = $cycleAgeS
        $report.checks["cycle"] = [ordered]@{
            updated               = (Get-Item $healthFile).LastWriteTime.ToString("o")
            duration_avg_s        = $health.duration_seconds
            posts_today           = $health.posts_today
            last_error            = $health.last_error
        }
    } catch {
        $report.checks["cycle"] = [ordered]@{ error = "unparseable health.json: $($_.Exception.Message)" }
    }
} else {
    $report.checks["cycle"] = [ordered]@{ error = "health.json missing" }
}

# ── 3. Stall del feed ──────────────────────────────────────────────────
try {
    $stallFile = Join-Path $script:root "data\phase_b_feed_stall.json"
    if (Test-Path $stallFile) {
        $stall = (Get-Content $stallFile -Raw | ConvertFrom-Json)
        $report.stall = $stall.consecutive_empty_cycles
        $report.checks["stall"] = $stall
    }
} catch {
    $report.checks["stall"] = [ordered]@{ error = $_.Exception.Message }
}

# ── 4. Errores en agent.log (ventana 1h) ───────────────────────────────
foreach ($logName in @("logs\agent.log", "logs\agent.log.1")) {
    $logPath = Join-Path $script:root $logName
    if (Test-Path $logPath) {
        $cutoff = (Get-Date).AddHours(-1)
        $errCount = 0
        $lastLine = Get-Content $logPath -Tail 2000 -ErrorAction SilentlyContinue
        foreach ($line in $lastLine) {
            if ($line -match " ERROR | CRITICAL ") {
                $isRecent = $false
                if ($line.Length -ge 20) {
                    try {
                        $dt = [DateTime]::ParseExact($line.Substring(0, 19), "yyyy-MM-dd HH:mm:ss", $null)
                        if ($dt -gt $cutoff) { $isRecent = $true }
                    } catch { $isRecent = $true }
                }
                if ($isRecent) { $errCount++ }
            }
        }
        if ($errCount -gt 0) {
            $report.errors_1h += $errCount
        }
        break
    }
}
$rateLimitHits = 0
$logPath = Join-Path $script:root "logs\agent.log"
if (Test-Path $logPath) {
    $cutoff = (Get-Date).AddHours(-1)
    foreach ($line in (Get-Content $logPath -Tail 4000 -ErrorAction SilentlyContinue)) {
        # Contar SOLO errores de rate-limit EXTERNOS reales:
        # - HTTP 429 desde un proveedor LLM
        # - FreeUsageLimitError de proveedor cloud
        # - statusCode":429 de Moltbook
        # NO contar: token bucket local ("Rate limiter: ... bloqueado") ni
        # CircuitBreaker reseteandose a CLOSED (ruido normal de recuperacion).
        if ($line -match "HTTP 429|FreeUsageLimitError|statusCode"":429") {
            # Excluir lineas del token bucket local
            if ($line -match "Rate limiter: \S+ bloqueado por") { continue }
            $isRecent = $false
            if ($line.Length -ge 20) {
                try {
                    $dt = [DateTime]::ParseExact($line.Substring(0, 19), "yyyy-MM-dd HH:mm:ss", $null)
                    if ($dt -gt $cutoff) { $isRecent = $true }
                } catch { $isRecent = $true }
            }
            if ($isRecent) { $rateLimitHits++ }
        }
    }
}
$report.checks["log"] = [ordered]@{ errors_1h = $report.errors_1h; rate_limit_hits_1h = $rateLimitHits }

# ── 5. Circuitos de tier (cascade_telemetry) ───────────────────────────
# Regla (18/08/2026): un tier cuenta como abierto solo si tiene >=3 fallos
# en 10 min Y ningun proveedor tuvo exito en la ventana (cascada caida
# del todo). Fallos aislados con fallback openrouter OK = ruido esperado.
$circuits = @()
$cascadeFile = Join-Path $script:root "data\cascade_telemetry.jsonl"
if (Test-Path $cascadeFile) {
    $cutoff10 = (Get-Date).AddMinutes(-10)
    $tierFails = @{}
    $successAny = $false
    foreach ($line in (Get-Content $cascadeFile -Tail 400 -ErrorAction SilentlyContinue)) {
        try {
            $ev = $line | ConvertFrom-Json
            if (-not $ev.PSObject.Properties['tier']) { continue }
            $evTs = if ($ev.ts -is [datetime]) { $ev.ts } else { [DateTime]::Parse($ev.ts) }
            if ($evTs -lt $cutoff10) { continue }
            $isFail = $false
            if ($ev.PSObject.Properties['success'] -and $ev.success -eq $true) {
                $successAny = $true
            } elseif ($ev.PSObject.Properties['success'] -and $ev.success -eq $false) {
                $isFail = $true
                $tier = [string]$ev.tier
                if (-not $tierFails.ContainsKey($tier)) { $tierFails[$tier] = 0 }
                $tierFails[$tier]++
            }
            $circuits += [ordered]@{
                ts      = $ev.ts
                tier    = $ev.tier
                success = if ($isFail) { "fail" } else { "ok" }
                error   = if ($isFail -and $ev.PSObject.Properties['error']) { $ev.error } else { $null }
            }
        } catch { }
    }
}
$report.circuits = $circuits
$openCircuit = @()
if (-not $successAny) {
    foreach ($tier in ($tierFails.Keys | Sort-Object)) {
        if ($tierFails[$tier] -ge 3) {
            $openCircuit += [ordered]@{ tier = $tier; fails_10min = $tierFails[$tier] }
        }
    }
}

# ── 6. Auto-diagnostico ────────────────────────────────────────────────
try {
    $diagFile = Join-Path $script:root "data\self_diagnosis.jsonl"
    if (Test-Path $diagFile) {
        $lastDiag = Get-Content $diagFile -Tail 3 | ForEach-Object {
            try { $_ | ConvertFrom-Json } catch { $null }
        } | Where-Object { $_ } | Select-Object -Last 1
        if ($lastDiag) {
            $report.diagnosis = [ordered]@{
                ts                    = $lastDiag.timestamp
                intervention_required = $lastDiag.intervention_required
                interventions         = $lastDiag.interventions
            }
        }
    }
} catch { }

# ── 7. Karma (estado social) ───────────────────────────────────────────
try {
    $tgStateFile = Join-Path $script:root "data\telegram_alert_state.json"
    if (Test-Path $tgStateFile) {
        $tgState = Get-Content $tgStateFile -Raw | ConvertFrom-Json
        $report.karma = $tgState.last_karma
    }
} catch { }

# ── 8. Clasificacion ──────────────────────────────────────────────────
$problems = [System.Collections.Generic.List[string]]::new()
$records = [System.Collections.Generic.List[string]]::new()
$severity = "ok"
$tg = Get-TelegramEnv

if (-not $agentUp) {
    $severity = "critical"
    $problems.Add("Agente NO esta corriendo (sin proceso run_agent.py)")
    $records.Add("🚨 *Agente caido*: no se encontro proceso run_agent.py. Revisa run-prod.ps1.")
} else {
    $records.Add("✅ Agente corriendo. Ciclo $($report.cycle_no), edad $cycleAgeS s.")
    if ($null -ne $cycleAgeS -and $cycleAgeS -gt 3600) {
        if ($severity -ne "critical") { $severity = "critical" }
        $problems.Add("Ciclo congelado: health.json sin actualizar hace $([math]::Round($cycleAgeS/60)) min")
        $records.Add("🚨 *Ciclo congelado*: health.json sin actualizar hace $([math]::Round($cycleAgeS/60)) min.")
    } elseif ($null -ne $cycleAgeS -and $cycleAgeS -gt 900) {
        if ($severity -eq "ok") { $severity = "warning" }
        $problems.Add("Ciclo lento: health.json con edad $([math]::Round($cycleAgeS/60)) min (>15)")
        $records.Add("⚠️ *Ciclo lento*: health.json con $([math]::Round($cycleAgeS/60)) min sin actualizar.")
    }
}

if ($null -ne $report.stall) {
    if ($report.stall -ge 60) {
        if ($severity -eq "ok") { $severity = "warning" }
        $problems.Add("Stall alto: $($report.stall) ciclos vacios consecutivos")
        $records.Add("⚠️ *Stall*: $($report.stall) ciclos vacios consecutivos.")
    }
}

if ($report.errors_1h -gt 10) {
    if ($severity -eq "ok") { $severity = "warning" }
    $problems.Add("$($report.errors_1h) errores/CRITICAL en el log (ultima hora)")
    $records.Add("⚠️ *Errores*: $($report.errors_1h) errores en la ultima hora.")
}

# Los hits 429 aislados NO alertan: el circuito abierto de un tier
# (rate limit conocido, ej. tier_flash) genera cientos de 429/hora y es
# ruido; el estado del circuito lo cubre el bloque de abajo.

if ($openCircuit) {
    if ($severity -eq "ok") { $severity = "warning" }
    $circuitSummary = ($openCircuit | ForEach-Object { "$($_.tier): $($_.fails_10min) fallos/10min" }) -join "; "
    $problems.Add("Circuitos con fallo reciente: $circuitSummary")
    $records.Add("⚠️ *Tier*: circuito fallo reciente ($circuitSummary).")
}

if ($report.diagnosis -and $report.diagnosis.intervention_required) {
    if ($severity -eq "ok") { $severity = "warning" }
    $problems.Add("Auto-diagnostico pide intervencion (intervention_required=true)")
    $records.Add("⚠️ *Auto-diagnostico*: intervention_required=true. Revisa data/self_diagnosis.jsonl.")
}

$report.summary = if ($problems.Count -gt 0) { $problems -join " | " } else { "Todo OK" }
$report.severity = $severity
$report.checks["problems"] = $problems

# ── 9. Persistencia ───────────────────────────────────────────────────
$latestFile = Join-Path $PSScriptRoot "latest.json"
$report | ConvertTo-Json -Depth 6 | Set-Content -Path $latestFile -Encoding utf8
$snapshot = $report | ConvertTo-Json -Compress -Depth 6
Add-Content -Path (Join-Path $PSScriptRoot "snapshots.jsonl") -Encoding utf8 -Value $snapshot

# ── 10. Alertas ───────────────────────────────────────────────────────
if ($severity -ne "ok") {
    Write-Alert -Type "health-severity-$severity" -Severity $severity -Summary $report.summary -Tg $tg
if ($severity -eq "critical") {
        $msg = ($records | Where-Object { $_ -match "🚨" }) -join "`n"
        # Cooldown 60 min por severidad. El marcador se registra para que
        # el siguiente run lo respete (fix 18/08/2026).
        if ($msg -and (Test-AlertCooldown "alert-critical" 60)) {
            Send-TelegramAlert -Message $msg -Tg $tg
            Write-Alert -Type "alert-critical" -Severity "critical" -Summary "Enviado: $msg"
        }
    }
    if ($severity -eq "warning" -and $records.Count -gt 0) {
        $msg = ($records | Where-Object { $_ -match "⚠️" }) -join "`n"
        if ($msg -and (Test-AlertCooldown "alert-warning" 60)) {
            Send-TelegramAlert -Message $msg -Tg $tg
            Write-Alert -Type "alert-warning" -Severity "warning" -Summary "Enviado: $msg"
        }
    }
} else {
    # Latido silencioso cada hora para saber que el monitor vive
    $heartbeatFile = Join-Path $PSScriptRoot "heartbeat.json"
    @{ last_ok = (Get-Date).ToString("o"); cycle = $report.cycle_no } | ConvertTo-Json | Set-Content $heartbeatFile -Encoding utf8
}

if ($VerboseRun) {
    $report | ConvertTo-Json -Depth 6
} else {
    Stop-Transcript | Out-Null
}
exit 0


