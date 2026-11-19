@echo off
title Hermes Bot - AI Lokal Gratis
cls
echo ============================================
echo    HERMES BOT - Asisten AI Lokal Anda
echo    Berjalan offline di laptop - GRATIS
echo    Ketik pertanyaan apa saja, /bye untuk keluar
echo ============================================
echo.
"%LOCALAPPDATA%\Programs\Ollama\ollama.exe" run hermes-bot
