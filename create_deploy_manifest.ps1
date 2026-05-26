$files = @(
  'S:\federation\federation-game\backend\simulation_engine.py',
  'S:\federation\federation-game\backend\faction_ai.py',
  'S:\federation\federation-game\backend\event_cascade.py',
  'S:\federation\federation-game\backend\main.py',
  'S:\federation\federation-game\backend\npc_autonomy.py',
  'S:\federation\federation-game\backend\llm_router.py',
  'S:\federation\federation-game\backend\npc_cognition.py',
  'S:\federation\federation-game\backend\narrator.py'
)
$out = 'S:\federation\deploy_manifest_b64.txt'
Remove-Item $out -ErrorAction SilentlyContinue
foreach ($f in $files) {
    $name = Split-Path $f -Leaf
    $bytes = [System.IO.File]::ReadAllBytes($f)
    $b64 = [Convert]::ToBase64String($bytes)
    $line = $name + "`t" + $b64
    Add-Content -Path $out -Value $line -Encoding Ascii -NoNewline
    Add-Content -Path $out -Value ''
}
Write-Host "Manifest created: $((Get-Item $out).Length) bytes"
Get-Content $out | ForEach-Object {
    $parts = $_ -split "`t"
    Write-Host "$($parts[0]) $($parts[1].Length) b64 chars"
}
