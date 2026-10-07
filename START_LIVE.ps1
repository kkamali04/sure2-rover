param([string]$RoverHost = '192.168.4.1')
Set-Location -LiteralPath $PSScriptRoot
$terminalDirectory = Join-Path $PSScriptRoot 'test_runs\terminals'
New-Item -ItemType Directory -Path $terminalDirectory -Force | Out-Null
$terminalPath = Join-Path $terminalDirectory ((Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.log')
Write-Host 'WAVE ROVER live controller. Join rover Wi-Fi first; keep wheels raised.'
Write-Host "Rover IP: $RoverHost; local page: http://127.0.0.1:8766"
Write-Host "Terminal record: $terminalPath"
Write-Host 'The controller starts disarmed. Keep this window open. Ctrl+C exits.'
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.venv\Scripts\python.exe')) {
    & .\.venv\Scripts\python.exe -u remote_controller.py --live --host $RoverHost --port 8766 --open-browser 2>&1 | Tee-Object -FilePath $terminalPath
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -u remote_controller.py --live --host $RoverHost --port 8766 --open-browser 2>&1 | Tee-Object -FilePath $terminalPath
} else {
    & python -u remote_controller.py --live --host $RoverHost --port 8766 --open-browser 2>&1 | Tee-Object -FilePath $terminalPath
}
Write-Host 'Controller exited. Verify the wheels stopped before switching Wi-Fi.'
