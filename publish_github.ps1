# Run from the clean release package. Publishes this package, never the parent course repo.
[CmdletBinding()]
param([ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$RepositoryName = 'sure2-rover')
$ErrorActionPreference = 'Stop'
function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed (exit $LASTEXITCODE). Publishing stopped; no force push is used." }
}
function Invoke-GhProbe {
    param([string[]]$Arguments)
    # Windows PowerShell 5.1 turns redirected native stderr into ErrorRecords.
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = & gh @Arguments 2>&1
        $code = $LASTEXITCODE
        return [pscustomobject]@{ Code = $code; Text = ($output | Out-String) }
    } finally { $ErrorActionPreference = $savedPreference }
}
try {
    $publishRoot = $PSScriptRoot
    if (!(Test-Path -LiteralPath (Join-Path $publishRoot 'PACKAGE_MANIFEST.json'))) {
        $publishRoot = Join-Path $PSScriptRoot 'release\sure2'
    }
    if (!(Test-Path -LiteralPath (Join-Path $publishRoot 'PACKAGE_MANIFEST.json'))) { throw 'Build or extract the clean release package first.' }
    Set-Location -LiteralPath $publishRoot
    $publishRoot = (Get-Location).Path
    foreach ($command in @('git','gh')) { if (!(Get-Command $command -ErrorAction SilentlyContinue)) { throw "Install $command first, then rerun this launcher." } }
    Write-Host 'Publishing the prepared sure2 package publicly. No rover connection is opened.'
    $account = (Invoke-Checked gh @('api','user','--jq','.login')).Trim()
    if ($account -notmatch '^[A-Za-z0-9-]+$') { throw 'Could not identify the GitHub account.' }
    $repository = "$account/$RepositoryName"
    if (!(Test-Path -LiteralPath '.git')) { Invoke-Checked git @('init','-b','main') }
    $gitRoot = (Invoke-Checked git @('rev-parse','--show-toplevel')).Trim()
    if ([IO.Path]::GetFullPath($gitRoot) -ne $publishRoot) { throw 'Refusing to publish a parent repository.' }
    Invoke-Checked git @('config','core.hooksPath','.githooks')
    Invoke-Checked git @('config','pull.ff','only')
    Invoke-Checked git @('config','pull.rebase','false')
    $remotes = @(Invoke-Checked git @('remote'))
    if ($remotes -contains 'origin') {
        $origin = (Invoke-Checked git @('remote','get-url','origin')).Trim()
        if ($origin -ne "https://github.com/$repository.git" -and $origin -ne "https://github.com/$repository" -and $origin -ne "git@github.com:$repository.git") { throw "Unexpected origin: $origin" }
        $remoteBranch = @(Invoke-Checked git @('ls-remote','origin','refs/heads/main'))
        if ($remoteBranch.Count -gt 0) { Invoke-Checked git @('pull','--ff-only','origin','main') }
    }
    if ((Invoke-Checked git @('branch','--show-current')).Trim() -ne 'main') { throw 'Switch this package repository to main before publishing.' }
    # Validate after a pull so newly fetched content is checked too.
    $manifest = Get-Content -LiteralPath 'PACKAGE_MANIFEST.json' -Raw | ConvertFrom-Json
    foreach ($item in $manifest.files) {
        $full = [IO.Path]::GetFullPath((Join-Path $publishRoot $item.path))
        if (!$full.StartsWith($publishRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Manifest path escapes the package.' }
        if (!(Test-Path -LiteralPath $full)) { throw "Missing package file: $($item.path)" }
        if ((Get-Item -LiteralPath $full).Length -ge 100000000) { throw "File exceeds 100 MB: $($item.path)" }
        if ((Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash -ne $item.sha256) { throw "Package changed since validation: $($item.path). Rebuild the release before publishing." }
    }
    # Stage only the audited allowlist, never logs, credentials or extra downloads.
    $allowed = @($manifest.files | ForEach-Object { $_.path }) + @('PACKAGE_MANIFEST.json')
    foreach ($name in @(Invoke-Checked git @('ls-files'))) { if ($name -notin $allowed) { throw "Unexpected tracked file: $name" } }
    $alreadyStaged = @(Invoke-Checked git @('diff','--cached','--name-only'))
    foreach ($name in $alreadyStaged) { if ($name -notin $allowed) { throw "Unexpected staged file: $name" } }
    foreach ($name in $allowed) { Invoke-Checked git @('add','--',$name) }
    $staged = @(Invoke-Checked git @('diff','--cached','--name-only'))
    if ($staged.Count -gt 0) { Invoke-Checked git @('commit','-m','Publish sure2 planner, 3D preview and local controller') }
    if ($remotes -notcontains 'origin') {
        Invoke-Checked gh @('repo','create',$repository,'--public','--source','.','--remote','origin','--description','sure2 rover station planner, 3D preview and local manual controller')
    }
    $visibility = (Invoke-Checked gh @('repo','view',$repository,'--json','visibility','--jq','.visibility')).Trim()
    if ($visibility -ne 'PUBLIC') { throw 'Repository is not public. Visibility was not changed automatically.' }
    Invoke-Checked git @('push','-u','origin','main')
    $localHead = (Invoke-Checked git @('rev-parse','HEAD')).Trim()
    $remoteHead = ((Invoke-Checked git @('ls-remote','origin','refs/heads/main')) -split '\s+')[0]
    if ($localHead -ne $remoteHead) { throw 'Remote branch does not match the tested local commit.' }
    $pagesEndpoint = "repos/$repository/pages"
    $existingPages = Invoke-GhProbe @('api',$pagesEndpoint,'--silent')
    if ($existingPages.Code -ne 0 -and $existingPages.Text -notmatch 'HTTP 404') { throw $existingPages.Text }
    $pageMethod = if ($existingPages.Code -eq 0) { 'PUT' } else { 'POST' }
    Invoke-Checked gh @('api',$pagesEndpoint,'--method',$pageMethod,'-f','build_type=legacy','-f','source[branch]=main','-f','source[path]=/docs','--silent')
    $site = (Invoke-Checked gh @('api',$pagesEndpoint,'--jq','.html_url')).Trim()
    Invoke-Checked gh @('repo','edit',$repository,'--homepage',$site)
    Write-Host "Repository: https://github.com/$repository"
    Write-Host "Preview: $site"
    Write-Host 'Waiting for GitHub Pages to build the pushed commit...'
    for ($attempt = 0; $attempt -lt 36; $attempt++) {
        $buildResult = Invoke-GhProbe @('api',"$pagesEndpoint/builds/latest")
        if ($buildResult.Code -ne 0) {
            if ($buildResult.Text -notmatch 'HTTP 404') { throw $buildResult.Text }
            Start-Sleep -Seconds 10
            continue
        }
        $build = $buildResult.Text | ConvertFrom-Json
        if ($build.commit -eq $localHead -and $build.status -eq 'errored') { throw "Pages build failed: $($build.error.message)" }
        if ($build.commit -eq $localHead -and $build.status -eq 'built') {
            try { $response = Invoke-WebRequest -Uri $site -UseBasicParsing -TimeoutSec 30 }
            catch { if ($_.Exception.Response.StatusCode -ne 404) { throw }; Start-Sleep -Seconds 10; continue }
            if ($response.StatusCode -eq 200 -and $response.Content.Contains('id="frontSvg"') -and $response.Content.Contains('heightDrag')) {
                Write-Host "Verified: remote commit matches and the public planner returns HTTP 200. Share $site"
                exit 0
            }
        }
        Start-Sleep -Seconds 10
    }
    throw "Pages is still building. Check https://github.com/$repository/actions and rerun this launcher later."
} catch {
    Write-Host "Publishing incomplete: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'If authentication failed, run: gh auth login --hostname github.com --web'
    Write-Host 'If Windows blocked the network connection, run this launcher in your own PowerShell outside the restricted agent session.'
    exit 1
}
