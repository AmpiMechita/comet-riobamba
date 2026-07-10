Write-Host "== COMET API CHECK ==" -ForegroundColor Cyan

$requiredVars = @(
    "MOLTBOOK_API_KEY",
    "MOLTBOOK_API_URL",
    "OPENROUTER_API_KEY",
    "GROQ_API_KEY"
)

foreach ($name in $requiredVars) {
    $value = [Environment]::GetEnvironmentVariable($name, "Process")
    if ([string]::IsNullOrWhiteSpace($value)) {
        $value = [Environment]::GetEnvironmentVariable($name, "User")
    }
    if ([string]::IsNullOrWhiteSpace($value)) {
        $value = [Environment]::GetEnvironmentVariable($name, "Machine")
    }

    if ([string]::IsNullOrWhiteSpace($value)) {
        Write-Host "[MISSING] $name" -ForegroundColor Red
    }
    else {
        Write-Host "[OK] $name" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "== PYTHON CHECK ==" -ForegroundColor Cyan
python --version

Write-Host ""
Write-Host "== OPTIONAL LOCAL OLLAMA CHECK ==" -ForegroundColor Cyan
try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -Method Get -TimeoutSec 10
    Write-Host "[OK] Ollama local reachable" -ForegroundColor Green
    $resp.models | Select-Object name, size | Format-Table -AutoSize
}
catch {
    Write-Host "[WARN] Ollama local not reachable on 127.0.0.1:11434" -ForegroundColor Yellow
}
