# Verificar encoding y legibilidad del script de analisis psicologico

$scriptPath = ".\analisis_psicologico_heuristico.py"

Write-Host "[*] Verificando encoding del script..." -ForegroundColor Cyan

# Leer el archivo como bytes
$bytes = [System.IO.File]::ReadAllBytes($scriptPath)

# Detectar BOM
if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    Write-Host "[!] BOM UTF-8 detectado (puede causar problemas en algunos entornos)" -ForegroundColor Yellow
} else {
    Write-Host "[+] Sin BOM (OK)" -ForegroundColor Green
}

# Leer como texto con diferentes encodings
$encodings = @('UTF-8', 'UTF-8-BOM', 'ASCII', 'ISO-8859-1', 'Windows-1252')

foreach ($enc in $encodings) {
    try {
        $content = Get-Content -Path $scriptPath -Encoding $enc -Raw -ErrorAction Stop
        
        # Buscar caracteres ilegibles o secuencias extraÃ±as
        $caracteresExtra = [regex]::Matches($content, '[^\x20-\x7E\x09\x0A\x0D]')
        
        if ($caracteresExtra.Count -gt 0) {
            Write-Host "[!] Encoding $enc: $($caracteresExtra.Count) caracteres no ASCII encontrados" -ForegroundColor Yellow
            
            # Mostrar primeros 10 caracteres problematicos
            $primeros10 = $caracteresExtra | Select-Object -First 10
            foreach ($match in $primeros10) {
                $char = $match.Value
                $code = [int][char]$char
                Write-Host "    - Caracter: '$char' (U+$code)" -ForegroundColor DarkYellow
            }
        } else {
            Write-Host "[+] Encoding $enc: Sin caracteres problematicos" -ForegroundColor Green
        }
    } catch {
        Write-Host "[!] Encoding $enc: Error al leer - $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host "`n[*] Verificando sintaxis de Python..." -ForegroundColor Cyan

# Intentar compilar el script con Python
try {
    $pythonCheck = python -m py_compile $scriptPath 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[+] Sintaxis de Python: OK" -ForegroundColor Green
    } else {
        Write-Host "[!] Sintaxis de Python: ERROR" -ForegroundColor Red
        Write-Host $pythonCheck
    }
} catch {
    Write-Host "[!] No se pudo verificar la sintaxis: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n[*] Verificando caracteres comunes en strings..." -ForegroundColor Cyan

$content = Get-Content -Path $scriptPath -Encoding UTF8 -Raw

# Verificar acentos y caracteres latinos en strings
$patrones = @(
    @{Nombre="Acentos agudos"; Patron="['"][^'""\n]*[Ã¡Ã©Ã¬Ã³ÃºÃ±][^'""\n]*['"]},
    @{Nombre="Caracteres especiales"; Patron="['"][^'""\n]*[Ã§ÃµÃ¶Ã¼][^'""\n]*['"]},
    @{Nombre="Signos de puntuacion"; Patron="['"][^'""\n]*[Â¿Â¡][^'""\n]*['"]}
)

foreach ($p in $patrones) {
    $matches = [regex]::Matches($content, $p.Patron)
    if ($matches.Count -gt 0) {
        Write-Host "[+] {$p.Nombre}: $($matches.Count) ocurrencias encontradas" -ForegroundColor Green
    } else {
        Write-Host "[-] {$p.Nombre}: Sin ocurrencias" -ForegroundColor DarkGray
    }
}

Write-Host "`n[*] Verificacion completada." -ForegroundColor Cyan