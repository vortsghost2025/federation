# Deploy-VpsFile.ps1 — Single-command Federation deploy workflow
# Usage:
#   .\scripts\Deploy-VpsFile.ps1 npc-agent              # deploy npc_agent.py
#   .\scripts\Deploy-VpsFile.ps1 npc-agent institutions   # deploy institutions.py to npc-agent
#   .\scripts\Deploy-VpsFile.ps1 backend npc_autonomy     # deploy npc_autonomy.py
#   .\scripts\Deploy-VpsFile.ps1 backend llm_router       # deploy llm_router.py
#   .\scripts\Deploy-VpsFile.ps1 backend institutions     # deploy institutions.py to backend
#   .\scripts\Deploy-VpsFile.ps1 docker-compose          # deploy docker-compose.yml + restart

param(
    [Parameter(Position=0, Mandatory=$true)]
    [ValidateSet('npc-agent','backend','docker-compose')]
    [string]$Target,

    [Parameter(Position=1)]
    [string]$File,

    [switch]$SkipVerify,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$VpsHost = 'root@187.77.3.56'

$LocalRoot = 'S:\federation\federation-game'
$VpsRoot = '/docker/federation-game'

function Ssh-Run([string]$Cmd) {
    $result = ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=no $VpsHost $Cmd 2>&1
    if ($LASTEXITCODE -ne 0) { throw "SSH failed: $result" }
    return $result
}

function Ssh-Scp([string]$Local, [string]$Remote) {
    scp -o ConnectTimeout=8 -o StrictHostKeyChecking=no $Local "${VpsHost}:${Remote}" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "SCP failed" }
}

function Get-Md5([string]$Path) {
    $hash = Get-FileHash -Path $Path -Algorithm MD5
    return $hash.Hash.ToLower()
}

function Ssh-Md5([string]$Path) {
    $result = Ssh-Run "md5sum $Path 2>/dev/null | cut -d' ' -f1"
    return $result.Trim()
}

function Ssh-Container-Md5([string]$Container, [string]$Path) {
    $result = Ssh-Run "docker exec $Container md5sum $Path 2>/dev/null | cut -d' ' -f1"
    return $result.Trim()
}

# ── TARGET: docker-compose ──
if ($Target -eq 'docker-compose') {
    $localFile = Join-Path $LocalRoot 'docker-compose.yml'
    $vpsFile = "$VpsRoot/docker-compose.yml"

    if (-not (Test-Path $localFile)) { throw "Not found: $localFile" }

    Write-Host "[1/5] Validating local docker-compose.yml..." -ForegroundColor Cyan
    docker compose -f $localFile config 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker-compose.yml validation failed" }
    Write-Host "  Valid" -ForegroundColor Green

    $md5 = Get-Md5 $localFile
    Write-Host "[2/5] Local MD5: $md5"

    if ($DryRun) { Write-Host "[DRY RUN] Would SCP to $vpsFile"; return }

    Write-Host "[3/5] Uploading..." -ForegroundColor Cyan
    Ssh-Scp $localFile $vpsFile

    $vpsMd5 = Ssh-Md5 $vpsFile
    if ($vpsMd5 -ne $md5) { throw "MD5 mismatch after upload: local=$md5 vps=$vpsMd5" }
    Write-Host "  VPS MD5: $vpsMd5 - OK" -ForegroundColor Green

    Write-Host "[4/5] Restarting containers..." -ForegroundColor Cyan
    Ssh-Run "cd $VpsRoot && docker compose up -d"

    Write-Host "[5/5] Checking containers..." -ForegroundColor Cyan
    Ssh-Run "docker ps -a --filter name=federation --format 'table {{.Names}}\t{{.Status}}'" | Write-Host
    return
}

# ── TARGET: npc-agent ──
if ($Target -eq 'npc-agent') {
    if (-not $File) { $File = 'npc_agent' }
    $baseName = $File
    if ($baseName -notlike '*.py') { $baseName += '.py' }

    # Special: 'npc_agent' also deploys from _current source
    $sourceFile = Join-Path $LocalRoot "npc-agent\$baseName"
    if (-not (Test-Path $sourceFile)) { throw "Not found: $sourceFile" }

    $vpsFile = "$VpsRoot/npc-agent/$baseName"

    Write-Host "[1/5] Validating Python syntax..." -ForegroundColor Cyan
    $pyCheck = python -m py_compile $sourceFile 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Syntax error: $pyCheck" }
    Write-Host "  Syntax OK" -ForegroundColor Green

    $md5 = Get-Md5 $sourceFile
    Write-Host "[2/5] Local MD5: $md5"

    if ($DryRun) { Write-Host "[DRY RUN] Would SCP to $vpsFile"; return }

    Write-Host "[3/5] Uploading to VPS..." -ForegroundColor Cyan
    Ssh-Scp $sourceFile $vpsFile

    $vpsMd5 = Ssh-Md5 $vpsFile
    if ($vpsMd5 -ne $md5) { throw "MD5 mismatch after upload: local=$md5 vps=$vpsMd5" }
    Write-Host "  VPS MD5: $vpsMd5 - OK" -ForegroundColor Green

    Write-Host "[4/5] Restarting npc-agent containers..." -ForegroundColor Cyan
    Ssh-Run "cd $VpsRoot && docker compose restart npc-agent-001 npc-agent-306"

    if (-not $SkipVerify) {
        Write-Host "[5/5] Verifying container MD5s..." -ForegroundColor Cyan
        Start-Sleep -Seconds 3
        $c001 = Ssh-Container-Md5 'federation-game-npc-agent-001-1' "/app/$baseName"
        $c306 = Ssh-Container-Md5 'federation-game-npc-agent-306-1' "/app/$baseName"
        Write-Host "  agent-001: $c001"
        Write-Host "  agent-306: $c306"
        if ($c001 -ne $md5) { Write-Host "  WARNING: agent-001 MD5 mismatch!" -ForegroundColor Red }
        if ($c306 -ne $md5) { Write-Host "  WARNING: agent-306 MD5 mismatch!" -ForegroundColor Red }
        if ($c001 -eq $md5 -and $c306 -eq $md5) {
            Write-Host "  Both containers match - VERIFIED" -ForegroundColor Green
        }
    }
    return
}

# ── TARGET: backend ──
if ($Target -eq 'backend') {
    if (-not $File) { throw "Must specify file name, e.g.: backend npc_autonomy" }
    $baseName = $File
    if ($baseName -notlike '*.py') { $baseName += '.py' }

    $sourceFile = Join-Path $LocalRoot "backend\$baseName"
    if (-not (Test-Path $sourceFile)) { throw "Not found: $sourceFile" }

    $vpsFile = "$VpsRoot/backend/$baseName"

    Write-Host "[1/5] Validating Python syntax..." -ForegroundColor Cyan
    $pyCheck = python -m py_compile $sourceFile 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Syntax error: $pyCheck" }
    Write-Host "  Syntax OK" -ForegroundColor Green

    $md5 = Get-Md5 $sourceFile
    Write-Host "[2/5] Local MD5: $md5"

    if ($DryRun) { Write-Host "[DRY RUN] Would SCP to $vpsFile"; return }

    Write-Host "[3/5] Uploading to VPS..." -ForegroundColor Cyan
    Ssh-Scp $sourceFile $vpsFile

    $vpsMd5 = Ssh-Md5 $vpsFile
    if ($vpsMd5 -ne $md5) { throw "MD5 mismatch after upload: local=$md5 vps=$vpsMd5" }
    Write-Host "  VPS MD5: $vpsMd5 - OK" -ForegroundColor Green

    Write-Host "[4/5] Restarting backend + worker..." -ForegroundColor Cyan
    Ssh-Run "cd $VpsRoot && docker compose restart backend worker"

    if (-not $SkipVerify) {
        Write-Host "[5/5] Verifying container MD5s..." -ForegroundColor Cyan
        Start-Sleep -Seconds 3
        $be = Ssh-Container-Md5 'federation-game-backend-1' "/app/$baseName"
        $wk = Ssh-Container-Md5 'federation-game-worker-1' "/app/$baseName"
        Write-Host "  backend: $be"
        Write-Host "  worker:  $wk"
        if ($be -ne $md5) { Write-Host "  WARNING: backend MD5 mismatch!" -ForegroundColor Red }
        if ($wk -ne $md5) { Write-Host "  WARNING: worker MD5 mismatch!" -ForegroundColor Red }
        if ($be -eq $md5 -and $wk -eq $md5) {
            Write-Host "  Both containers match - VERIFIED" -ForegroundColor Green
        }
    }
    return
}
