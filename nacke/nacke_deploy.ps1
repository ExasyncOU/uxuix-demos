# nacke_deploy.ps1 - Nacke NackeScript Deployment + Testlauf
# Laedt alle Scripts von GitHub, mappt K: falls noetig, erstellt Ordnerstruktur
# und startet test_export_picklist.py

$BASE     = 'C:\NackeScript'
$RawBase  = 'https://raw.githubusercontent.com/ExasyncOU/uxuix-demos/main/nacke'
$ts       = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

Write-Host "=== Nacke Deployment ===" -ForegroundColor Cyan
Write-Host "VM: $($env:COMPUTERNAME) | User: $(whoami) | Timestamp: $ts"

# ------------------------------------------------------------------
# 1. K: Laufwerk mappen (subst falls kein echtes K:)
# ------------------------------------------------------------------
if (-not (Test-Path 'K:\')) {
    Write-Host "K: nicht vorhanden - erstelle via subst K: C:\" -ForegroundColor Yellow
    subst K: C:\ 2>&1 | Out-Null
    if (Test-Path 'K:\') {
        Write-Host "K: erfolgreich gemappt (K: -> C:\)" -ForegroundColor Green
    } else {
        Write-Host "WARNUNG: subst K: fehlgeschlagen" -ForegroundColor Red
    }
} else {
    Write-Host "K: bereits vorhanden: $(Get-Item K:\)" -ForegroundColor Green
}

# ------------------------------------------------------------------
# 2. Ordnerstruktur erstellen
# ------------------------------------------------------------------
$folders = @(
    'K:\Raussuchlisten',
    'K:\Raussuchlisten\Export',
    'K:\Raussuchlisten\2026',
    "$BASE\logs",
    "$BASE\state",
    "$BASE\data"
)
foreach ($f in $folders) {
    if (-not (Test-Path $f)) {
        New-Item -ItemType Directory -Path $f -Force | Out-Null
        Write-Host "  Erstellt: $f" -ForegroundColor Green
    } else {
        Write-Host "  OK: $f"
    }
}

# ------------------------------------------------------------------
# 3. Python-Dateien von GitHub herunterladen (mit Cache-Busting)
# ------------------------------------------------------------------
Write-Host "`n=== Download Scripts ===" -ForegroundColor Cyan
$files = @(
    'idis_browser.py',
    'picklist_generator.py',
    'master_data.py',
    'test_export_picklist.py',
    'config.json'
)
foreach ($f in $files) {
    $url  = "$RawBase/$f`?v=$ts"
    $dest = "$BASE\$f"
    Write-Host "  $f ..." -NoNewline
    try {
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
        $sz = [math]::Round((Get-Item $dest).Length / 1KB, 1)
        Write-Host " OK ($sz KB)" -ForegroundColor Green
    } catch {
        Write-Host " FEHLER: $_" -ForegroundColor Red
    }
}

# ------------------------------------------------------------------
# 4. Testlauf starten
# ------------------------------------------------------------------
Write-Host "`n=== Starte Testlauf ===" -ForegroundColor Yellow
Write-Host "Export-Ordner:     K:\Raussuchlisten\Export"
Write-Host "Picklisten-Ordner: K:\Raussuchlisten\2026"

Push-Location $BASE
try {
    python test_export_picklist.py
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

# ------------------------------------------------------------------
# 5. Ergebnis pruefen
# ------------------------------------------------------------------
if ($exitCode -eq 0) {
    Write-Host "`n=== TEST ERFOLGREICH ===" -ForegroundColor Green

    # Exports pruefen
    $exports = Get-ChildItem 'K:\Raussuchlisten\Export' -Filter 'IDIS_EXPORT_*' -ErrorAction SilentlyContinue |
               Sort-Object LastWriteTime -Descending | Select-Object -First 3
    if ($exports) {
        Write-Host "IDIS Exports in K:\Raussuchlisten\Export:"
        $exports | ForEach-Object { Write-Host "  $($_.Name) ($([math]::Round($_.Length/1KB,1)) KB)" }
    }

    # Picklisten pruefen
    $picklists = Get-ChildItem 'K:\Raussuchlisten\2026' -Filter 'KI_UXUIX-*' -ErrorAction SilentlyContinue |
                 Sort-Object LastWriteTime -Descending | Select-Object -First 5
    if ($picklists) {
        Write-Host "Picklisten in K:\Raussuchlisten\2026:"
        $picklists | ForEach-Object { Write-Host "  $($_.Name)" -ForegroundColor Cyan }
    }
} else {
    Write-Host "`n=== TEST FEHLGESCHLAGEN (Exit: $exitCode) ===" -ForegroundColor Red
    exit $exitCode
}
