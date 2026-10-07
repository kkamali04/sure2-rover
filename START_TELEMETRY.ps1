param([string]$RoverHost = '192.168.4.1')
Set-Location -LiteralPath $PSScriptRoot
Write-Host 'Read-only telemetry: close the live controller first. No motor commands are sent.'
$terminalDirectory = Join-Path $PSScriptRoot 'test_runs\terminals'
New-Item -ItemType Directory -Path $terminalDirectory -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $terminalDirectory ('telemetry-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.log'))
try {
    & .\.venv\Scripts\python.exe -u telemetry_capture.py --host $RoverHost --capture
} finally { Stop-Transcript }
