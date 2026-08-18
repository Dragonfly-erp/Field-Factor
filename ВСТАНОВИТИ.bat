@echo off
chcp 65001 >nul
title FieldFactor - vstanovlennya
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "_збірка\build_runtime.ps1"
echo.
pause
