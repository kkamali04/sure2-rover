@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe remote_controller.py --simulate --open-browser
  pause
  exit /b
)
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 remote_controller.py --simulate --open-browser
) else (
  python remote_controller.py --simulate --open-browser
)
pause
