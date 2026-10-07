param(
    [ValidateSet('Menu','Preview','Setup','Simulate','Live','USB','Check','Test')]
    [string]$Mode = 'Menu',
    [ValidateRange(0,65535)][int]$Port = 0,
    [switch]$NoBrowser,
    [switch]$NoPythonInstall,
    [string]$EnvironmentDirectory = '.venv'
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$rootDirectory = [IO.Path]::GetFullPath($PSScriptRoot)
$environmentPath = [IO.Path]::GetFullPath((Join-Path $rootDirectory $EnvironmentDirectory))
if (-not $environmentPath.StartsWith($rootDirectory + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The Python environment must be inside this project.'
}
$environmentPython = Join-Path $environmentPath 'Scripts\python.exe'

function Find-CompatiblePython {
    $candidates = @()
    if (Test-Path -LiteralPath $environmentPython) { $candidates += @{ File=$environmentPython; Prefix=@() } }
    foreach ($name in @('python.exe','py.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) { $candidates += @{ File=$command.Source; Prefix=$(if ($name -eq 'py.exe') { @('-3') } else { @() }) } }
    }
    foreach ($candidate in $candidates) {
        try {
            $prefix = @($candidate.Prefix)
            & $candidate.File @prefix -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch { }
    }
    return $null
}

function Ensure-PythonEnvironment {
    $python = Find-CompatiblePython
    if (-not $python) {
        Write-Host 'Python 3.10+ is needed only for the local controller. Offline preview needs no Python.'
        if ($NoPythonInstall) { throw 'No compatible Python found. Install Python 3.10+ from python.org, then rerun SURE2.bat.' }
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $winget) { throw 'Install Python 3.10+ from https://www.python.org/downloads/windows/ and rerun SURE2.bat.' }
        if ((Read-Host 'Install Python 3.13 for this Windows user now? Type YES') -cne 'YES') { throw 'Python installation declined. Choose Preview for the offline HTML.' }
        & $winget.Source install --id Python.Python.3.13 --exact --scope user --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw 'Python installation failed. See the installer output above.' }
        # Installation may update PATH only for newly opened shells.
        $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
        $python = Find-CompatiblePython
        if (-not $python) { throw 'Python installed but is not visible yet. Close this window and rerun SURE2.bat.' }
    }
    if ($python.File -ne $environmentPython) {
        $prefix = @($python.Prefix)
        & $python.File @prefix -m venv $environmentPath
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the project Python environment.' }
    }
    & $environmentPython -c 'import sys, remote_controller, rover_test; print(sys.version)'
    if ($LASTEXITCODE -ne 0) { throw 'Project import check failed. Extract the full ZIP before running the launcher.' }
    Write-Host 'HTTP controller ready (standard library only).'
    # Wi-Fi HTTP and simulator need no pip packages. USB serial is an explicit option.
}

function Open-SurePage([string]$Location) {
    Write-Host "Open: $Location"
    if (-not $NoBrowser) {
        try { Start-Process -FilePath $Location -WindowStyle Hidden | Out-Null }
        catch { Write-Host 'Browser did not open automatically; use the location printed above.' }
    }
}

function Get-LocalServer([int]$LocalPort) {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$LocalPort/api/status" -TimeoutSec 2
    } catch { return $null }
}

function Start-SureController([bool]$Live) {
    $localPort = $Port
    if ($localPort -eq 0) { $localPort = $(if ($Live) { 8766 } else { 8765 }) }
    if ($localPort -lt 1024) { throw 'Controller port must be 1024..65535.' }
    # Never open or start live transport before the operator's explicit confirmation.
    $roverAddress = '192.168.4.1'
    if ($Live) {
        Write-Host 'LIVE ROVER: connect its Wi-Fi, raise the wheels, and close other rover-control clients.'
        Write-Host 'Starts disarmed. Only you operate movement. Network/firmware settings are not changed.'
        if ((Read-Host 'Type LIVE to confirm the rover is physically ready') -cne 'LIVE') { Write-Host 'Live startup cancelled.'; return }
        $entered = Read-Host 'Rover IP [192.168.4.1]'
        if ($entered) { $roverAddress = $entered }
        $parsedAddress = $null
        if (-not [Net.IPAddress]::TryParse($roverAddress, [ref]$parsedAddress)) { throw 'Enter an IP address, not a URL.' }
    }
    $existing = Get-LocalServer $localPort
    if ($existing) {
        if ($existing.live -isnot [bool] -or $existing.live -ne $Live) {
            throw "Port $localPort is used by a different server/mode. Close it yourself or choose another port."
        }
        Write-Host 'Existing controller detected; no second process started. Opening its page does not arm it.'
        $suffix = $(if ($Live) { '/debug' } else { '/' })
        Open-SurePage "http://127.0.0.1:$localPort$suffix"
        return
    }
    $probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$localPort)
    try { $probe.Start() } catch { throw "Port $localPort is occupied. No controller started." } finally { $probe.Stop() }
    Ensure-PythonEnvironment
    $arguments = @('-u','remote_controller.py','--port',"$localPort")
    if ($Live) { $arguments += @('--live','--host',$roverAddress) } else { $arguments += '--simulate' }
    if (-not $NoBrowser) { $arguments += '--open-browser' }
    Write-Host 'Keep this window open. Ctrl+C exits the controller.'
    & $environmentPython @arguments
    if ($LASTEXITCODE -ne 0) { throw "Controller exited with code $LASTEXITCODE. Review the terminal output and controller_log.jsonl." }
}

try {
    if ($Mode -eq 'Menu') {
        Write-Host "`nsure2 - planner and WAVE ROVER"
        Write-Host '1  Open offline 2D/3D preview (no installation)'
        Write-Host '2  Set up and run local simulator / debugging'
        Write-Host '3  Live rover controller (operator confirmation required)'
        Write-Host '4  Install optional USB serial dependency'
        Write-Host '5  Check/setup Python and local files'
        Write-Host '6  Run software tests (no rover)'
        Write-Host '0  Exit'
        $choice = Read-Host 'Choose [1]'
        if (-not $choice) { $choice = '1' }
        $options = @{ '1'='Preview'; '2'='Simulate'; '3'='Live'; '4'='USB'; '5'='Check'; '6'='Test' }
        if ($choice -eq '0') { exit 0 }
        if (-not $options.ContainsKey($choice)) { throw 'Choose a number from 0 to 6.' }
        $Mode = $options[$choice]
    }
    switch ($Mode) {
        'Preview' {
            $file = Join-Path $rootDirectory 'SURE2_Planner.html'
            if (-not (Test-Path -LiteralPath $file)) { throw 'SURE2_Planner.html is missing. Extract the complete download.' }
            Open-SurePage $file
        }
        'Simulate' { Start-SureController $false }
        'Live' { Start-SureController $true }
        'USB' {
            Ensure-PythonEnvironment
            & $environmentPython -m pip install -r requirements.txt
            if ($LASTEXITCODE -ne 0) { throw 'USB dependency installation failed. Internet is needed for the first installation.' }
            & $environmentPython -m pip check
            if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
        }
        { $_ -in 'Setup','Check' } { Ensure-PythonEnvironment; Write-Host 'Setup check passed. No controller or hardware connection opened.' }
        'Test' {
            Ensure-PythonEnvironment
            & $environmentPython -m unittest discover -s tests -v
            if ($LASTEXITCODE -ne 0) { throw 'Software tests failed. Review the output above.' }
        }
    }
} catch { Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red; exit 1 }
