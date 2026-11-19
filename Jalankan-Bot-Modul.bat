@echo off
chcp 65001 >nul
title Hermes Bot - Klik untuk Jalankan / Hentikan
cd /d "%~dp0"

echo ============================================
echo   HERMES BOT - KLIK LAGI UNTUK MENGHENTIKAN
echo ============================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0toggle-bot.ps1"
if errorlevel 1 (
  echo.
  echo Terjadi error. Tekan tombol untuk menutup jendela.
  pause
)
