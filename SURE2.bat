@echo off
setlocal
cd /d "%~dp0"
set "sureMode=%~1"
if "%sureMode%"=="" set "sureMode=Menu"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_and_run.ps1" -Mode "%sureMode%"
set "sureExit=%errorlevel%"
if "%~1"=="" pause
exit /b %sureExit%
