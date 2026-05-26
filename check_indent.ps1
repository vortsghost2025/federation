param([string]$File, [int]$Start, [int]$End)
$lines = [System.IO.File]::ReadAllLines($File)
for ($i = $Start - 1; $i -lt $End -and $i -lt $lines.Count; $i++) {
    $spaces = 0
    $line = $lines[$i]
    foreach ($c in $line.ToCharArray()) {
        if ($c -eq ' ') { $spaces++ } else { break }
    }
    $trimmed = $line.TrimStart()
    Write-Host ("{0}: indent={1} | {2}" -f ($i+1), $spaces, $trimmed)
}
