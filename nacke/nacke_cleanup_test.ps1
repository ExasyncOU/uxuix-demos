$BASE = 'C:\NackeScript'
$ts = Get-Date -f yyyyMMddHHmmss
$REPO = 'ExasyncOU/uxuix-demos'
$BRANCH = 'main'

foreach ($fname in @('idis_browser.py', 'test_export_picklist.py')) {
    $url = "https://raw.githubusercontent.com/$REPO/$BRANCH/nacke/$fname`?v=$ts"
    $dest = Join-Path $BASE $fname
    Write-Host "Download: $fname"
    (New-Object Net.WebClient).DownloadFile($url, $dest)
    $sz = (Get-Item $dest).Length
    Write-Host "  -> $dest ($sz bytes)"
}

Write-Host "`nStarte test_export_picklist.py (CWD=$BASE)..."
$logfile = Join-Path $BASE "exports\test_run_cleanup_$ts.log"
Push-Location $BASE
try {
    & python test_export_picklist.py 2>&1 | Tee-Object -FilePath $logfile
} finally {
    Pop-Location
}
Write-Host "`n=== LETZTEN 20 ZEILEN ==="
Get-Content $logfile | Select-Object -Last 20
