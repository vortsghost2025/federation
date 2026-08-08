$Repo = 'S:\federation'
$Journal = 'S:\federation\docs\handoffs\FEDERATION_CHANGE_JOURNAL.md'
$Index = 'S:\federation\docs\handoffs\JOURNAL_INDEX.md'
$Utc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')

$Root = git -C $Repo rev-parse --show-toplevel 2>$null

if ([string]::IsNullOrWhiteSpace($Root)) {
    Write-Output 'VERDICT: FAIL'
    Write-Output "UTC: $Utc"
    Write-Output 'SOURCE ENTRIES: N/A'
    Write-Output 'INDEXED ENTRIES: N/A'
    Write-Output 'DUPLICATES REMOVED: 0'
    Write-Output 'EXTRA OLD INDEX ENTRIES REMOVED: 0'
    Write-Output 'CONFLICT MARKERS: Repository unavailable'
    Write-Output 'FILE WRITTEN: None'
    exit 1
}

if (-not (Test-Path -LiteralPath $Journal)) {
    Write-Output 'VERDICT: FAIL'
    Write-Output "UTC: $Utc"
    Write-Output 'SOURCE ENTRIES: N/A'
    Write-Output 'INDEXED ENTRIES: N/A'
    Write-Output 'DUPLICATES REMOVED: 0'
    Write-Output 'EXTRA OLD INDEX ENTRIES REMOVED: 0'
    Write-Output 'CONFLICT MARKERS: Journal missing'
    Write-Output 'FILE WRITTEN: None'
    exit 1
}

$JournalLines = @(Get-Content -LiteralPath $Journal)

if ($JournalLines.Count -eq 0 -or
    [string]::IsNullOrWhiteSpace(($JournalLines -join ''))) {
    Write-Output 'VERDICT: FAIL'
    Write-Output "UTC: $Utc"
    Write-Output 'SOURCE ENTRIES: 0'
    Write-Output 'INDEXED ENTRIES: 0'
    Write-Output 'DUPLICATES REMOVED: 0'
    Write-Output 'EXTRA OLD INDEX ENTRIES REMOVED: 0'
    Write-Output 'CONFLICT MARKERS: None'
    Write-Output 'FILE WRITTEN: None'
    exit 1
}

$ConflictMatches = @(
    Select-String `
        -LiteralPath $Journal `
        -Pattern '^\s*(<<<<<<<|=======|>>>>>>>)\s*$'
)

if ($ConflictMatches.Count -gt 0) {
    $ConflictLines = (
        $ConflictMatches |
        ForEach-Object { $_.LineNumber }
    ) -join ', '

    Write-Output 'VERDICT: FAIL'
    Write-Output "UTC: $Utc"
    Write-Output 'SOURCE ENTRIES: N/A'
    Write-Output 'INDEXED ENTRIES: N/A'
    Write-Output 'DUPLICATES REMOVED: 0'
    Write-Output 'EXTRA OLD INDEX ENTRIES REMOVED: 0'
    Write-Output "CONFLICT MARKERS: $ConflictLines"
    Write-Output 'FILE WRITTEN: None'
    exit 1
}

$SourcePattern = '^\s*(?:#{1,6}\s*)?ENTRY\s+(?<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z)\s*[—-]\s*(?<title>.+?)\s*$'

$RawSourceEntries = @(
    foreach ($Line in $JournalLines) {
        if ($Line -match $SourcePattern) {
            $Timestamp = $Matches['timestamp']
            $Title = $Matches['title'].Trim()
            "$Timestamp — $Title"
        }
    }
)

if ($RawSourceEntries.Count -eq 0) {
    Write-Output 'VERDICT: FAIL'
    Write-Output "UTC: $Utc"
    Write-Output "SOURCE ENTRIES: 0"
    Write-Output "INDEXED ENTRIES: 0"
    Write-Output "DUPLICATES REMOVED: 0"
    Write-Output "EXTRA OLD INDEX ENTRIES REMOVED: 0"
    Write-Output "CONFLICT MARKERS: None"
    Write-Output "FILE WRITTEN: None"
    exit 1
}

$SeenSource = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::Ordinal
)

$SourceEntries = [System.Collections.Generic.List[string]]::new()

foreach ($Entry in $RawSourceEntries) {
    if ($SeenSource.Add($Entry)) {
        [void]$SourceEntries.Add($Entry)
    }
}

$DuplicatesRemoved = $RawSourceEntries.Count - $SourceEntries.Count

$OldEntries = @()

if (Test-Path -LiteralPath $Index) {
    $OldPattern = '^\s*(?:(?:#{1,6}\s*)?ENTRY\s+|-\s+)(?<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z)\s*[—-]\s*(?<title>.+?)\s*$'

    $OldEntries = @(
        foreach ($Line in Get-Content -LiteralPath $Index) {
            if ($Line -match $OldPattern) {
                $Timestamp = $Matches['timestamp']
                $Title = $Matches['title'].Trim()
                "$Timestamp — $Title"
            }
        }
    )
}

$SeenOldExtras = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::Ordinal
)

$ExtraOldEntriesRemoved = 0

foreach ($OldEntry in $OldEntries) {
    if (($SourceEntries -notcontains $OldEntry) -and
        $SeenOldExtras.Add($OldEntry)) {
        $ExtraOldEntriesRemoved++
    }
}

$OutputLines = [System.Collections.Generic.List[string]]::new()

[void]$OutputLines.Add('# Federation Change Journal Index')
[void]$OutputLines.Add('')
[void]$OutputLines.Add("Generated UTC: $Utc")
[void]$OutputLines.Add('Source: docs/handoffs/FEDERATION_CHANGE_JOURNAL.md')
[void]$OutputLines.Add("Entry count: $($SourceEntries.Count)")
[void]$OutputLines.Add('')

foreach ($Entry in $SourceEntries) {
    [void]$OutputLines.Add("- $Entry")
}

Set-Content `
    -LiteralPath $Index `
    -Value $OutputLines `
    -Encoding utf8

$WrittenLines = @(Get-Content -LiteralPath $Index)

$IndexPattern = '^\s*-\s+(?<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z)\s*[—-]\s*(?<title>.+?)\s*$'

$WrittenEntries = @(
    foreach ($Line in $WrittenLines) {
        if ($Line -match $IndexPattern) {
            $Timestamp = $Matches['timestamp']
            $Title = $Matches['title'].Trim()
            "$Timestamp — $Title"
        }
    }
)

$VerificationPassed = $true

if ($WrittenEntries.Count -ne $SourceEntries.Count) {
    $VerificationPassed = $false
}

if ($VerificationPassed) {
    for ($i = 0; $i -lt $SourceEntries.Count; $i++) {
        if ($WrittenEntries[$i] -ne $SourceEntries[$i]) {
            $VerificationPassed = $false
            break
        }
    }
}

$WrittenUnique = @($WrittenEntries | Sort-Object -Unique)

if ($WrittenUnique.Count -ne $WrittenEntries.Count) {
    $VerificationPassed = $false
}

$RecordedCountLine = $WrittenLines |
    Where-Object { $_ -match '^Entry count:\s*\d+\s*$' } |
    Select-Object -First 1

if ($RecordedCountLine -ne "Entry count: $($SourceEntries.Count)") {
    $VerificationPassed = $false
}

$WrittenConflicts = @(
    Select-String `
        -LiteralPath $Index `
        -Pattern '^\s*(<<<<<<<|=======|>>>>>>>)\s*$'
)

if ($WrittenConflicts.Count -gt 0) {
    $VerificationPassed = $false
}

if (-not $VerificationPassed) {
    Write-Output 'VERDICT: FAIL'
    Write-Output "UTC: $Utc"
    Write-Output "SOURCE ENTRIES: $($SourceEntries.Count)"
    Write-Output "INDEXED ENTRIES: $($WrittenEntries.Count)"
    Write-Output "DUPLICATES REMOVED: $DuplicatesRemoved"
    Write-Output "EXTRA OLD INDEX ENTRIES REMOVED: $ExtraOldEntriesRemoved"
    Write-Output 'CONFLICT MARKERS: None'
    Write-Output "FILE WRITTEN: $Index"
    exit 1
}

Write-Output 'VERDICT: PASS'
Write-Output "UTC: $Utc"
Write-Output "SOURCE ENTRIES: $($SourceEntries.Count)"
Write-Output "INDEXED ENTRIES: $($WrittenEntries.Count)"
Write-Output "DUPLICATES REMOVED: $DuplicatesRemoved"
Write-Output "EXTRA OLD INDEX ENTRIES REMOVED: $ExtraOldEntriesRemoved"
Write-Output 'CONFLICT MARKERS: None'
Write-Output "FILE WRITTEN: $Index"