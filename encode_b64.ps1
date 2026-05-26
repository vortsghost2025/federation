$filePath = "S:\federation\federation-game\backend\map_endpoints.py"
$content = [System.IO.File]::ReadAllText($filePath)
$content = $content -replace "`r`n", "`n"
$bytes = [System.Text.Encoding]::UTF8.GetBytes($content)
$b64 = [Convert]::ToBase64String($bytes)
$outPath = "S:\federation\map_endpoints_clean_b64.txt"
[System.IO.File]::WriteAllText($outPath, $b64)
Write-Host "ENCODED_OK lines=$($content.Split("`n").Count)"
