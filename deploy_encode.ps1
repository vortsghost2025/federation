$files = @('simulation_engine.py', 'npc_autonomy.py', 'faction_ai.py', 'event_cascade.py', 'main.py', 'map_endpoints.py')
$backendDir = 'S:\federation\federation-game\backend\'
$manifestPath = 'S:\federation\deploy_manifest_b64.txt'

$manifest = ''
foreach ($f in $files) {
    $path = Join-Path $backendDir $f
    $bytes = [System.IO.File]::ReadAllBytes($path)
    $b64 = [Convert]::ToBase64String($bytes)
    $manifest += "$f`t$b64`n"
    Write-Host "Encoded: $f -> $($bytes.Length) bytes -> $($b64.Length) b64 chars"
}

[System.IO.File]::WriteAllText($manifestPath, $manifest, [System.Text.Encoding]::ASCII)
Write-Host "Manifest written to $manifestPath"
