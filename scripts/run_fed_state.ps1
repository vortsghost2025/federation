$ErrorActionPreference = 'Stop'

$Repo = 'S:\federation'
$Script = 'S:\federation\scripts\fed-state.sh'
$Snapshot = 'S:\federation\docs\handoffs\STATE_SNAPSHOT.md'
$Utc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')

function Write-Failure {
    param(
        [string]$Reason
    )

    Write-Output 'VERDICT: FAIL'
    Write-Output "UTC: $Utc"
    Write-Output "REASON: $Reason"
    Write-Output 'FILE WRITTEN: None'
}

function Get-RepositoryCounts {
    $Lines = @(
        git -C $Repo status --short --untracked-files=all
    )

    $Modified = @(
        $Lines | Where-Object {
            $_.Length -ge 2 -and
            $_.Substring(0, 2) -match 'M'
        }
    ).Count

    $Added = @(
        $Lines | Where-Object {
            $_.Length -ge 2 -and
            $_.Substring(0, 2) -match 'A'
        }
    ).Count

    $Deleted = @(
        $Lines | Where-Object {
            $_.Length -ge 2 -and
            $_.Substring(0, 2) -match 'D'
        }
    ).Count

    $Untracked = @(
        $Lines | Where-Object {
            $_.Length -ge 2 -and
            $_.Substring(0, 2) -eq '??'
        }
    ).Count

    [pscustomobject]@{
        Lines = $Lines
        Modified = $Modified
        Added = $Added
        Deleted = $Deleted
        Untracked = $Untracked
    }
}

function Get-ExactPathStatus {
    param(
        [string]$RelativePath
    )

    $Lines = @(
        git -C $Repo status --short -- $RelativePath
    )

    if ($Lines.Count -eq 0) {
        return 'clean'
    }

    $Codes = @(
        $Lines | ForEach-Object {
            if ($_.Length -ge 2) {
                $_.Substring(0, 2)
            }
        }
    )

    $States = [System.Collections.Generic.List[string]]::new()

    if (@($Codes | Where-Object { $_ -eq '??' }).Count -gt 0) {
        [void]$States.Add('untracked')
    }

    if (@($Codes | Where-Object { $_ -match 'M' }).Count -gt 0) {
        [void]$States.Add('modified')
    }

    if (@($Codes | Where-Object { $_ -match 'A' }).Count -gt 0) {
        [void]$States.Add('added')
    }

    if (@($Codes | Where-Object { $_ -match 'D' }).Count -gt 0) {
        [void]$States.Add('deleted')
    }

    if ($States.Count -eq 0) {
        return 'other'
    }

    return ($States -join '+')
}

$Root = git -C $Repo rev-parse --show-toplevel 2>$null

if ([string]::IsNullOrWhiteSpace($Root)) {
    Write-Failure 'Repository unavailable'
    exit 1
}

if (-not (Test-Path -LiteralPath $Script)) {
    Write-Failure 'fed-state.sh missing'
    exit 1
}

$Branch = (
    git -C $Repo branch --show-current
).Trim()

$Head = (
    git -C $Repo rev-parse --short HEAD
).Trim()

$ScriptOutput = @(
    & wsl.exe bash -lc 'bash /mnt/s/federation/scripts/fed-state.sh' 2>&1
)

$ScriptExitCode = $LASTEXITCODE

$ProvisionalSnapshot = @(
    'FEDERATION STATE SNAPSHOT'
    ''
    "UTC: $Utc"
    "branch: $Branch"
    "HEAD: $Head"
    "script exit code: $ScriptExitCode"
    'status counts: calculating'
)

Set-Content `
    -LiteralPath $Snapshot `
    -Value $ProvisionalSnapshot `
    -Encoding utf8

$Counts = Get-RepositoryCounts

$CouncilorBridge = Get-ExactPathStatus `
    'federation-game/backend/councilor_bridge.py'

$CouncilorExchange = Get-ExactPathStatus `
    'federation-game/backend/councilor_exchange.py'

$FederationGameNpcs = Get-ExactPathStatus `
    'federation-game/backend/federation_game_npcs.py'

$Npcs = Get-ExactPathStatus `
    'federation-game/backend/npcs.py'

$RouteCouncilorExchange = Get-ExactPathStatus `
    'federation-game/backend/routes/councilor_exchange.py'

$SimulationEngine = Get-ExactPathStatus `
    'federation-game/backend/simulation_engine.py'

$ResearchDocs = Get-ExactPathStatus `
    'docs/research/'

$SnapshotContent = @(
    'FEDERATION STATE SNAPSHOT'
    ''
    "UTC: $Utc"
    "branch: $Branch"
    "HEAD: $Head"
    "script exit code: $ScriptExitCode"
    "modified: $($Counts.Modified)"
    "added: $($Counts.Added)"
    "deleted: $($Counts.Deleted)"
    "untracked: $($Counts.Untracked)"
    ''
    'EXACT PATH STATUS'
    ''
    "federation-game/backend/councilor_bridge.py: $CouncilorBridge"
    "federation-game/backend/councilor_exchange.py: $CouncilorExchange"
    "federation-game/backend/federation_game_npcs.py: $FederationGameNpcs"
    "federation-game/backend/npcs.py: $Npcs"
    "federation-game/backend/routes/councilor_exchange.py: $RouteCouncilorExchange"
    "federation-game/backend/simulation_engine.py: $SimulationEngine"
    "docs/research/: $ResearchDocs"
)

Set-Content `
    -LiteralPath $Snapshot `
    -Value $SnapshotContent `
    -Encoding utf8

$FinalCounts = Get-RepositoryCounts

if (
    $FinalCounts.Modified -ne $Counts.Modified -or
    $FinalCounts.Added -ne $Counts.Added -or
    $FinalCounts.Deleted -ne $Counts.Deleted -or
    $FinalCounts.Untracked -ne $Counts.Untracked
) {
    $Counts = $FinalCounts

    $SnapshotContent = @(
        'FEDERATION STATE SNAPSHOT'
        ''
        "UTC: $Utc"
        "branch: $Branch"
        "HEAD: $Head"
        "script exit code: $ScriptExitCode"
        "modified: $($Counts.Modified)"
        "added: $($Counts.Added)"
        "deleted: $($Counts.Deleted)"
        "untracked: $($Counts.Untracked)"
        ''
        'EXACT PATH STATUS'
        ''
        "federation-game/backend/councilor_bridge.py: $CouncilorBridge"
        "federation-game/backend/councilor_exchange.py: $CouncilorExchange"
        "federation-game/backend/federation_game_npcs.py: $FederationGameNpcs"
        "federation-game/backend/npcs.py: $Npcs"
        "federation-game/backend/routes/councilor_exchange.py: $RouteCouncilorExchange"
        "federation-game/backend/simulation_engine.py: $SimulationEngine"
        "docs/research/: $ResearchDocs"
    )

    Set-Content `
        -LiteralPath $Snapshot `
        -Value $SnapshotContent `
        -Encoding utf8
}

if ($ScriptExitCode -eq 0) {
    Write-Output 'VERDICT: PASS'
}
else {
    Write-Output 'VERDICT: FAIL'
}

Write-Output "UTC: $Utc"
Write-Output "BRANCH: $Branch"
Write-Output "HEAD: $Head"
Write-Output "SCRIPT EXIT CODE: $ScriptExitCode"
Write-Output "MODIFIED: $($Counts.Modified)"
Write-Output "ADDED: $($Counts.Added)"
Write-Output "DELETED: $($Counts.Deleted)"
Write-Output "UNTRACKED: $($Counts.Untracked)"
Write-Output "FILE WRITTEN: $Snapshot"