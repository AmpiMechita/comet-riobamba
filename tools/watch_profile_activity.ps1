param(
    [string]$RepoRoot = "C:\comet-riobamba-v31",
    [int]$PollSeconds = 60,
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Continue"
Set-Location $RepoRoot

$snapshotDir = Join-Path $RepoRoot "data"
$snapshotPath = Join-Path $snapshotDir "profile_activity_snapshot.json"
$logPath = Join-Path $snapshotDir "profile_activity_events.jsonl"
if (-not (Test-Path $snapshotDir)) { New-Item -ItemType Directory -Path $snapshotDir | Out-Null }

function Write-EventLine($obj) {
    ($obj | ConvertTo-Json -Compress -Depth 8) | Add-Content -Path $logPath -Encoding UTF8
}

function Get-ProfileSnapshot {
    return [ordered]@{
        checked_at = (Get-Date).ToString("o")
        note = "Implementar aquí llamada real a profile_posts y extracción de ids, comment_count y latest_activity"
        posts = @()
    }
}

function Test-ProfileChanged($oldSnap, $newSnap) {
    if ($null -eq $oldSnap) { return $true }
    $oldJson = $oldSnap | ConvertTo-Json -Depth 8 -Compress
    $newJson = $newSnap | ConvertTo-Json -Depth 8 -Compress
    return $oldJson -ne $newJson
}

while ($true) {
    try {
        $newSnap = Get-ProfileSnapshot
        $oldSnap = $null
        if (Test-Path $snapshotPath) {
            $oldSnap = Get-Content $snapshotPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 8
        }

        if (Test-ProfileChanged $oldSnap $newSnap) {
            $newSnap | ConvertTo-Json -Depth 8 | Set-Content -Path $snapshotPath -Encoding UTF8
            Write-Host "Cambio detectado en perfil. Lanzando agente..." -ForegroundColor Yellow
            Write-EventLine ([ordered]@{
                event_type = "profile_activity_detected"
                timestamp_utc = (Get-Date).ToUniversalTime().ToString("o")
                source = "powershell_profile_watcher"
            })
            & $PythonExe -m core.agent
        }
        else {
            Write-Host "Sin cambios en perfil" -ForegroundColor DarkGray
        }
    }
    catch {
        Write-Host "Watcher error: $($_.Exception.Message)" -ForegroundColor Red
    }

    Start-Sleep -Seconds $PollSeconds
}
