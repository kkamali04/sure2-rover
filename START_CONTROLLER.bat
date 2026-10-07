@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_LIVE.ps1"
echo.
echo Controller closed. Verify that the rover has stopped.
pause
