@echo off
rem ---------------------------------------------------------------------
rem  ONLY ASCII IS ALLOWED INSIDE THIS FILE. See the note in ZAPUSK.bat.
rem  All Ukrainian output comes from the PowerShell script, which is saved
rem  as UTF-8 with BOM so Windows PowerShell 5.1 reads it correctly.
rem ---------------------------------------------------------------------
chcp 65001 >nul
title FieldFactor - setup
cd /d "%~dp0"

if not exist "setup\build_runtime.ps1" goto no_script

powershell -NoProfile -ExecutionPolicy Bypass -File "setup\build_runtime.ps1"
echo.
pause
exit /b 0

:no_script
echo.
echo   setup\build_runtime.ps1 not found - the folder is incomplete.
echo   Download FieldFactor again.
echo.
pause
exit /b 1
