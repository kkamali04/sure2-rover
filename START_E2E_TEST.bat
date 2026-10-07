@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe run_e2e.py
) else (
  py -3 run_e2e.py
)
echo.
echo This test uses simulation only. Reports are in e2e_results.
pause
