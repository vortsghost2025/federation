# Encode just the 3 P0 fix files for deployment
$files = @('worker.py', 'npc_autonomy.py', 'npcs.py')
$backendDir = "S:\federation\federation-game\backend"
$outPath = "S:\federation\p0_fix_manifest_b64.txt"
$manifestBytes = [System.Collections.Generic.List[byte]]::new()
$tabByte = [System.Text.Encoding]::UTF8.GetBytes([char]9)
$newlineByte = [System.Text.Encoding]::UTF8.GetBytes([char]10)

foreach ($name in $files) {
    $fpath = Join-Path $backendDir $name
    $rawBytes = [System.IO.File]::ReadAllBytes($fpath)
    $normalized = [System.Collections.Generic.List[byte]]::new()
    for ($i = 0; $i -lt $rawBytes.Length; $i++) {
        if ($i -lt $rawBytes.Length - 1 -and $rawBytes[$i] -eq 0x0D -and $rawBytes[$i+1] -eq 0x0A) {
            $normalized.Add(0x0A)
            $i++
        } else {
            $normalized.Add($rawBytes[$i])
        }
    }
    $normalizedArray = $normalized.ToArray()
    $b64 = [Convert]::ToBase64String($normalizedArray)
    $nameBytes = [System.Text.Encoding]::UTF8.GetBytes($name)
    $b64Bytes = [System.Text.Encoding]::ASCII.GetBytes($b64)
    $manifestBytes.AddRange($nameBytes)
    $manifestBytes.AddRange($tabByte)
    $manifestBytes.AddRange($b64Bytes)
    $manifestBytes.AddRange($newlineByte)
    $text = [System.Text.Encoding]::UTF8.GetString($normalizedArray)
    $lineCount = $text.Split([char]10).Count
    Write-Host "ENCODED: $name ($lineCount lines, $($b64.Length) b64 chars)"
}

[System.IO.File]::WriteAllBytes($outPath, $manifestBytes.ToArray())
Write-Host ""
Write-Host "MANIFEST_CREATED: $outPath"
$size = [System.IO.File]::ReadAllBytes($outPath).Length
Write-Host "MANIFEST_SIZE: $size bytes"
