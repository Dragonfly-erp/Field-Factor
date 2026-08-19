@echo off
rem ---------------------------------------------------------------------
rem  ONLY ASCII IS ALLOWED INSIDE THIS FILE.
rem  cmd.exe reads a .bat in the console OEM codepage, not UTF-8. Cyrillic
rem  bytes break the parser: an "if ( ... )" block falls apart and the lines
rem  inside it run as commands. Ukrainian text lives in app\no_runtime.txt
rem  and is printed with "type" after chcp 65001.
rem ---------------------------------------------------------------------
chcp 65001 >nul
title FieldFactor
cd /d "%~dp0"

if not exist "runtime\python.exe" goto no_runtime

"runtime\python.exe" -X utf8 "start.py"
if errorlevel 1 pause
exit /b 0

:no_runtime
echo.
type "app\no_runtime.txt"
echo.
pause
exit /b 1
