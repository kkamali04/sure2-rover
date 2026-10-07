@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish_github.ps1"
set "sureExit=%errorlevel%"
pause
exit /b %sureExit%
