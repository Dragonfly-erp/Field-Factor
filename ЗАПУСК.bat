@echo off
chcp 65001 >nul
title FieldFactor
cd /d "%~dp0"

if not exist "runtime\python.exe" (
  echo.
  echo   Робоче середовище ще не зібране.
  echo   Запустіть спочатку ВСТАНОВИТИ.bat — один раз, потрібен інтернет.
  echo.
  pause
  exit /b 1
)

"runtime\python.exe" -X utf8 "start.py"
if errorlevel 1 pause
