@echo off
chcp 65001 >nul
title Hermes Bot Plus - Asisten Kuliah AI Lokal
cls
python "%~dp0hermes-agent.py"
if errorlevel 1 pause
