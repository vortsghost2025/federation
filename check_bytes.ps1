$bytes = [System.IO.File]::ReadAllBytes('S:\federation\federation-game\backend\simulation_engine.py')
Write-Output ("File size: $($bytes.Length) bytes")

# Find the help_ally line
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
$idx = $text.IndexOf('elif category == "help_ally"')
Write-Output ("help_ally found at offset: $idx")

# Show bytes around it
for ($i = $idx - 12; $i -lt $idx + 30; $i++) {
    $b = $bytes[$i]
    $ch = if ($b -eq 10) {"LF"} elseif ($b -eq 13) {"CR"} elseif ($b -eq 32) {"SP"} else {[char]$b}
    Write-Output ("  byte[$i] = $b ($ch)")
}

# Check how many spaces before elif
$lineStart = $idx
while ($lineStart -gt 0 -and $bytes[$lineStart - 1] -ne 10 -and $bytes[$lineStart - 1] -ne 13) {
    $lineStart--
}
$spaces = $idx - $lineStart
Write-Output ("Line starts at offset: $lineStart, spaces before 'elif': $spaces")
for ($j = $lineStart; $j -lt $idx; $j++) {
    Write-Output ("  byte[$j] = $($bytes[$j])")
}
