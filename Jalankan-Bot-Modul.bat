@echo off
chcp 65001 >nul
title Hermes Bot - Jalankan Modul Otomatis
cd /d "%~dp0"

echo ============================================
echo   HERMES BOT - MENJALANKAN SEMUA MODUL
echo ============================================
echo.

rem Jangan jalankan dua proses sekaligus (satu profil browser = satu proses).
powershell -NoProfile -Command "if (Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'hermes-agent.py|lanjut-modul.py|jalankan-modul.py' }) { exit 1 }"
if errorlevel 1 (
  echo Bot masih berjalan di proses lain. Tutup dulu sebelum menekan shortcut ini.
  echo.
  pause
  exit /b 1
)

py -3.15 -u "%~dp0jalankan-modul.py"
if errorlevel 1 (
  echo.
  echo Bot berhenti karena error. Rincian ada di layar ini dan di log-modul.txt.
  pause
)
