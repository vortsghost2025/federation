# mod.ps1 — Federation moderator CLI wrapper (PowerShell).
# Safe base64 JSON argument transport — immune to bash/PowerShell quoting, $, backticks, and newlines.
#
# Usage:
#   .\scripts\mod.ps1 health
#   .\scripts\mod.ps1 inbox
#   .\scripts\mod.ps1 inbox --all
#   .\scripts\mod.ps1 pins
#   .\scripts\mod.ps1 reply comp_001 "Subject" "Body text"
#   .\scripts\mod.ps1 read comp_001 10
#   .\scripts\mod.ps1 grants
#   .\scripts\mod.ps1 execs comp_001
#   .\scripts\mod.ps1 publish "Title" path\to\content.txt
#   .\scripts\mod.ps1 openq comp_001__comp_010 "Question?"
#   .\scripts\mod.ps1 capreq-close capreq_xxxx "Reason"
param(
    [Parameter(Mandatory = $true)][string]$Command,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
)
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'mod.py'

$argv = [System.Collections.Generic.List[string]]::new()
$argv.Add($Command)

if ($Command -eq 'publish') {
    if (-not $Rest -or $Rest.Count -lt 2) { throw 'publish needs <title> <file>' }
    $title = $Rest[0]
    $filePath = $Rest[1]
    if (-not (Test-Path -LiteralPath $filePath)) { throw "File not found: $filePath" }
    $contentBytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $filePath))
    $b64Content = [Convert]::ToBase64String($contentBytes)
    $argv.Add($title)
    $argv.Add($b64Content)
} elseif ($Rest) {
    foreach ($arg in $Rest) {
        $argv.Add([string]$arg)
    }
}

$jsonArgv = ConvertTo-Json -InputObject @($argv) -Compress
$b64Argv = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($jsonArgv))

# Base64 contains only [A-Za-z0-9+/=] — completely immune to remote shell expansion.
Get-Content -Raw $scriptPath | ssh vps "docker exec -i -w /app federation-game-backend-1 python3 - --b64-argv $b64Argv"
