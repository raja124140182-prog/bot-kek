param([switch]$PeriksaSaja)

# Satu klik = jalankan bila belum ada, atau hentikan bila sedang berjalan.
$pola = 'hermes-agent\.py|lanjut-modul\.py|jalankan-modul\.py|transkrip_audio\.py'
$proses = @(Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq 'python.exe' -or $_.Name -eq 'py.exe') -and
    $_.CommandLine -match $pola
})

if ($PeriksaSaja) {
    "DITEMUKAN=$($proses.Count)"
    $proses | ForEach-Object { "PID=$($_.ProcessId) CMD=$($_.CommandLine)" }
    exit 0
}

if ($proses.Count -gt 0) {
    Write-Host "Bot sedang berjalan. Menghentikan proses beserta turunannya..."
    foreach ($p in $proses) {
        Write-Host ("  PID " + $p.ProcessId)
        & taskkill /PID $p.ProcessId /T /F > $null 2>&1
    }
    Start-Sleep -Seconds 2

    # Bersihkan kunci profil Chromium yang bisa tertinggal setelah mati paksa.
    $prof = Join-Path $PSScriptRoot 'BrowserProfile'
    Get-ChildItem -LiteralPath $prof -Filter 'Singleton*' -Force -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue

    Write-Host "Bot sudah dihentikan."
    exit 0
}

Write-Host "Bot tidak berjalan. Menjalankan semua modul..."
$skrip = Join-Path $PSScriptRoot 'jalankan-modul.py'
& py -3.15 -u $skrip
if ($LASTEXITCODE -ne 0) {
    Write-Host "Bot berhenti karena error (kode $LASTEXITCODE)."
}
exit $LASTEXITCODE
