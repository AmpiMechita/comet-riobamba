<#
.SYNOPSIS
  Registra el saldo de la cuenta DeepSeek y calcula el consumo real del dia.

.DESCRIPTION
  Consulta el endpoint oficial GET https://api.deepseek.com/user/balance con la
  API key y guarda un snapshot con marca de tiempo en un CSV (ledger, UTF-8).
  Con -ResumenHoy calcula saldo de inicio, saldo actual y consumo del dia a
  partir de los snapshots registrados.

  Uso recomendado con el agente COMET:
    1. Antes de lanzar el lote de produccion:  .\saldo_deepseek.ps1 -Etiqueta "pre-produccion"
    2. Al terminar el lote:                    .\saldo_deepseek.ps1 -Etiqueta "post-produccion"
    3. Para ver el resumen:                    .\saldo_deepseek.ps1 -ResumenHoy
  Asi el consumo de produccion queda aislado de cualquier llamada de prueba.

.REQUISITOS
  - Variable de entorno DEEPSEEK_API_KEY (o pasar -ApiKey).
  - PowerShell 5.1 o superior.

.NOTAS
  - DeepSeek descuenta primero del granted balance y luego del topped-up;
    el script registra ambos ademas del total.
  - La moneda depende de la cuenta (USD o CNY); se guarda en cada fila.
  - El ledger es incremental: un snapshot por llamada, nunca sobrescribe.
#>

param(
    [string]$ApiKey = $env:DEEPSEEK_API_KEY,
    [string]$LedgerPath = (Join-Path $PSScriptRoot "ledger_saldo_deepseek.csv"),
    [string]$Etiqueta = "manual",
    [switch]$ResumenHoy
)

$ErrorActionPreference = "Stop"

function Get-SaldoDeepSeek {
    param([string]$Key)
    if ([string]::IsNullOrWhiteSpace($Key)) {
        throw "Falta la API key. Defina `$env:DEEPSEEK_API_KEY o use el parametro -ApiKey."
    }
    $headers = @{ "Authorization" = "Bearer $Key"; "Accept" = "application/json" }
    Invoke-RestMethod -Uri "https://api.deepseek.com/user/balance" -Headers $headers -Method Get -TimeoutSec 30
}

if ($ResumenHoy) {
    if (-not (Test-Path -LiteralPath $LedgerPath)) {
        throw "No existe el ledger todavia: $LedgerPath. Registre al menos un snapshot hoy."
    }
    $hoy   = (Get-Date).ToString("yyyy-MM-dd")
    $filas = @(Import-Csv -LiteralPath $LedgerPath -Encoding UTF8 | Where-Object { $_.fecha -eq $hoy })
    if ($filas.Count -eq 0) {
        Write-Output "Sin snapshots registrados hoy ($hoy)."
        return
    }

    $inicio = [decimal]$filas[0].saldo_total
    $actual = [decimal]$filas[$filas.Count - 1].saldo_total
    $moneda = $filas[0].moneda

    Write-Output ("Fecha                : {0}" -f $hoy)
    Write-Output ("Saldo inicio de hoy  : {0} {1}  (snapshot {2})" -f $inicio, $moneda, $filas[0].hora)
    Write-Output ("Saldo actual         : {0} {1}  (snapshot {2})" -f $actual, $moneda, $filas[$filas.Count - 1].hora)
    Write-Output ("Consumo total de hoy : {0} {1}" -f ($inicio - $actual), $moneda)

    $pre  = $filas | Where-Object { $_.etiqueta -eq "pre-produccion" }  | Select-Object -First 1
    $post = $filas | Where-Object { $_.etiqueta -eq "post-produccion" } | Select-Object -Last 1
    if ($pre -and $post) {
        $consProd = [decimal]$pre.saldo_total - [decimal]$post.saldo_total
        Write-Output ("Consumo PRODUCCION   : {0} {1}  (pre {2} -> post {3})" -f $consProd, $moneda, $pre.hora, $post.hora)
    }
    else {
        Write-Output "Consumo PRODUCCION   : no disponible (faltan snapshots pre/post-produccion)."
    }
    return
}

$resp = Get-SaldoDeepSeek -Key $ApiKey
if (-not $resp.is_available) {
    Write-Warning "DeepSeek reporta is_available = false: saldo insuficiente para seguir haciendo llamadas."
}

$info = @($resp.balance_infos)[0]
if (-not $info) { throw "La respuesta no trajo balance_infos." }

$snapshot = [PSCustomObject]@{
    fecha           = (Get-Date).ToString("yyyy-MM-dd")
    hora            = (Get-Date).ToString("HH:mm:ss")
    moneda          = $info.currency
    saldo_total     = $info.total_balance
    saldo_granted   = $info.granted_balance
    saldo_topped_up = $info.topped_up_balance
    disponible      = $resp.is_available
    etiqueta        = $Etiqueta
}

if (Test-Path -LiteralPath $LedgerPath) {
    $snapshot | Export-Csv -LiteralPath $LedgerPath -Append -NoTypeInformation -Encoding UTF8
}
else {
    $snapshot | Export-Csv -LiteralPath $LedgerPath -NoTypeInformation -Encoding UTF8
}

Write-Output ("Snapshot guardado: {0} {1} | granted {2} | topped-up {3} | etiqueta '{4}'" -f `
    $snapshot.saldo_total, $snapshot.moneda, $snapshot.saldo_granted, $snapshot.saldo_topped_up, $snapshot.etiqueta)
