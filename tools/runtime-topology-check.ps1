# runtime-topology-check.ps1
# READ-ONLY Library-lane preflight. Prints proof of the live Federation topology.
# Patches NOTHING. Run before any frontend / proxy / deploy change so a Builder
# agent observes runtime reality (mounts, route owner, served-file hash) instead
# of trusting docs or assumed request paths.
#
# Requires: ssh access to the VPS, and curl/ssh on PATH (built into Windows 10+).
# Usage:  .\tools\runtime-topology-check.ps1
#         .\tools\runtime-topology-check.ps1 -VPSHost federation-vps -Domain federation-game.deliberatefederation.cloud

param(
    [string]$VPSHost = "federation-vps",
    [string]$Domain  = "federation-game.deliberatefederation.cloud"
)

$ErrorActionPreference = "SilentlyContinue"

function Remote {
    param([string]$Cmd)
    ssh $VPSHost $Cmd 2>&1
}

function Section($Title) {
    Write-Host ""
    Write-Host "==== $Title ====" -ForegroundColor Cyan
}

Section "1. docker ps (edge + relevant containers)"
Remote "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'"

Section "2. frontend mounts (public_html + nginx conf)"
Remote "docker inspect federation-game-frontend-1 --format '{{range .Mounts}}{{.Type}} {{.Source}} -> {{.Destination}} ({{.Mode}}) {{end}}'"

Section "3. backend mounts (/app + universe)"
Remote "docker inspect federation-game-backend-1 --format '{{range .Mounts}}{{.Type}} {{.Source}} -> {{.Destination}} ({{.Mode}}) {{end}}'"

Section "4. frontend Traefik labels (serving)"
Remote "docker inspect federation-game-frontend-1 | grep -iE 'routers.federation-game.rule|routers.federation-game.service|services.federation-game-svc'"

Section "5. backend command (uvicorn flags)"
Remote "docker inspect federation-game-backend-1 --format '{{json .Config.Cmd}}'"

Section "6. /npcs route-owner proof"
Write-Host "-- localhost:80 (frontend nginx direct) --"
Remote "curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1/npcs/?limit=1"
Write-Host "-- public HTTPS (through Traefik) --"
curl.exe -sI "https://$Domain/npcs/?limit=1" 2>&1 | Select-String -Pattern "HTTP/|server|location"

Section "7. served simulation.js md5"
$served = Join-Path $env:TEMP "sim_served_$(Get-Date -Format yyyyMMddHHmmss).js"
curl.exe -s "https://$Domain/simulation.js" -o $served 2>&1
if (Test-Path $served) {
    $hash = (Get-FileHash $served -Algorithm MD5).Hash.ToLower()
    Write-Host "served simulation.js MD5 = $hash  (compare against the local repo file)"
    Remove-Item $served -Force
} else {
    Write-Host "could not fetch served file"
}

Section "Preflight gate"
Write-Host "BLOCK if: serving path unknown | route owner unknown | mount type unknown |" -ForegroundColor Yellow
Write-Host "validation only checks source | local vs deployed build not both checked." -ForegroundColor Yellow
