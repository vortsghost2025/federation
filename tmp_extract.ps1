$ErrorActionPreference = 'Stop'
$json = Get-Content "C:\Users\seand\AppData\Local\AgentProfiles\kilo-a\cache\kilo\models.json" -Raw | ConvertFrom-Json
$nvidia = $json.nvidia
$sb = [System.Text.StringBuilder]::new()
[void]$sb.AppendLine("=== NVIDIA PROVIDER ===")
[void]$sb.AppendLine("ENV: $($nvidia.env -join ', ')")
[void]$sb.AppendLine("API: $($nvidia.api)")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("=== NVIDIA MODELS WITH tool_call=true ===")
$nvidia.models.PSObject.Properties | ForEach-Object {
    if ($_.Value.tool_call -eq $true) {
        [void]$sb.AppendLine("$($_.Name) | ctx=$($_.Value.limit.context) | out=$($_.Value.limit.output) | cost_in=$($_.Value.cost.input) | cost_out=$($_.Value.cost.output) | reasoning=$($_.Value.reasoning)")
    }
}
$sb.ToString() | Set-Content -Path "S:\federation\tmp_extract_output.txt" -Encoding utf8
Write-Output "DONE"
