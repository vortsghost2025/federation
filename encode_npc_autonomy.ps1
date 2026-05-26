$bytes = [System.IO.File]::ReadAllBytes('S:\federation\federation-game\backend\npc_autonomy.py')
$b64 = [Convert]::ToBase64String($bytes)
$tab = [char]9
$line = "npc_autonomy.py$tab$b64"
Set-Content -Path 'S:\federation\npc_autonomy_fix_b64.txt' -Value $line -Encoding Ascii -NoNewline
Write-Host "Encoded: $($b64.Length) b64 chars"
