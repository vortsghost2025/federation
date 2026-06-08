[CmdletBinding()]
param(
    [string[]]$Files,
    [string]$RemoteHost = 'root@187.77.3.56',
    [string]$RemoteRoot = '/docker/federation-game',
    [string]$VerifyBase = 'https://federation-game.deliberatefederation.cloud',
    [switch]$NoRestart,
    [switch]$SkipVerify,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $Command $($Arguments -join ' ')"
    }
}

$sshOptions = @(
    '-o', 'BatchMode=yes',
    '-o', 'StrictHostKeyChecking=accept-new'
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$frontendDir = Join-Path $repoRoot 'federation-game\frontend'

if (-not (Test-Path $frontendDir)) {
    throw "Frontend directory not found: $frontendDir"
}

if (-not $Files -or $Files.Count -eq 0) {
    $Files = Get-ChildItem $frontendDir -File |
        Where-Object { $_.Extension -in '.html', '.css', '.js' } |
        Sort-Object Name |
        Select-Object -ExpandProperty Name
}

if (-not $Files -or $Files.Count -eq 0) {
    throw "No frontend files selected for deployment."
}

$remotePublicDir = "$RemoteRoot/public_html"
$remoteFrontendDir = "$RemoteRoot/frontend"

Write-Host "Deploying frontend assets to $RemoteHost" -ForegroundColor Cyan
Write-Host "Repo frontend source: $frontendDir"
Write-Host "Remote bind mount: $remotePublicDir"
Write-Host "Remote mirror: $remoteFrontendDir"

foreach ($fileName in $Files) {
    $localPath = Join-Path $frontendDir $fileName
    if (-not (Test-Path $localPath)) {
        throw "Local frontend file not found: $localPath"
    }

    $remoteTempPath = "/tmp/$fileName"
    $installCommand = "install -m 0644 '$remoteTempPath' '$remotePublicDir/$fileName' && install -m 0644 '$remoteTempPath' '$remoteFrontendDir/$fileName' && rm -f '$remoteTempPath'"

    Write-Host "Syncing $fileName" -ForegroundColor Yellow
    if (-not $DryRun) {
        Invoke-External -Command 'scp' -Arguments ($sshOptions + @($localPath, "${RemoteHost}:$remoteTempPath"))
        Invoke-External -Command 'ssh' -Arguments ($sshOptions + @($RemoteHost, $installCommand))
    }
}

if (-not $NoRestart) {
    Write-Host "Restarting frontend container" -ForegroundColor Yellow
    if (-not $DryRun) {
        Invoke-External -Command 'ssh' -Arguments ($sshOptions + @($RemoteHost, "cd '$RemoteRoot' && docker compose restart frontend"))
        Start-Sleep -Seconds 2
    }
}

if (-not $SkipVerify) {
    $baseUrl = $VerifyBase.TrimEnd('/')
    foreach ($fileName in $Files) {
        $url = "$baseUrl/$fileName"
        Write-Host "Verifying $url" -ForegroundColor Yellow
        if ($DryRun) {
            continue
        }

        $statusCode = & curl.exe -s -o NUL -w "%{http_code}" $url
        if ($LASTEXITCODE -ne 0) {
            throw "curl verification failed for $url"
        }
        if ($statusCode -ne '200') {
            throw "Verification failed for $url (HTTP $statusCode)"
        }
        Write-Host "Verified $fileName -> HTTP $statusCode" -ForegroundColor Green
    }
}

Write-Host "Frontend asset sync finished." -ForegroundColor Green
