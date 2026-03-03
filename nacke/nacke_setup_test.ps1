$ScriptDir = "C:\NackeScript"
$GistBase = "https://gist.githubusercontent.com/ExasyncOU/1765952815a7f89598db2ef1e5447609/raw"
$ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

Write-Host "=== Nacke Setup + Testlauf ===" -ForegroundColor Cyan
Write-Host "Zielordner: $ScriptDir"
Write-Host "Zeitstempel: $ts"

# Python-Dateien herunterladen
$files = @("idis_browser.py", "picklist_generator.py", "master_data.py", "test_export_picklist.py", "config.json")
foreach ($f in $files) {
    $url = "$GistBase/$f`?v=$ts"
    $dest = "$ScriptDir\$f"
    Write-Host "  Downloading $f ..." -NoNewline
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    Write-Host " OK ($([math]::Round((Get-Item $dest).Length / 1KB, 1)) KB)"
}

# Ausgabeordner anlegen
$outputDir = "K:\Raussuchlisten\2026"
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    Write-Host "Ordner erstellt: $outputDir" -ForegroundColor Green
} else {
    Write-Host "Ordner vorhanden: $outputDir"
}

# Testlauf starten
Write-Host ""
Write-Host "=== Starte Testlauf ===" -ForegroundColor Yellow
Push-Location $ScriptDir
python test_export_picklist.py
$exitCode = $LASTEXITCODE
Pop-Location

if ($exitCode -eq 0) {
    Write-Host ""
    Write-Host "TEST ERFOLGREICH" -ForegroundColor Green
    $files_created = Get-ChildItem $outputDir -Filter "KI_UXUIX-*" | Sort-Object LastWriteTime -Descending | Select-Object -First 5
    if ($files_created) {
        Write-Host "Erstellt in $outputDir`:"
        $files_created | ForEach-Object { Write-Host "  $($_.Name)" }
    }
} else {
    Write-Host "TEST FEHLGESCHLAGEN (Exit: $exitCode)" -ForegroundColor Red
    exit $exitCode
}
