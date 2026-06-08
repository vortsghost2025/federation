$json = Get-Content "C:\Users\seand\AppData\Local\AgentProfiles\kilo-a\cache\kilo\models.json" -Raw | ConvertFrom-Json
$nvidia = $json.nvidia
Write-Output "=== ENV ==="
Write-Output $nvidia.env
Write-Output "=== API ==="
Write-Output $nvidia.api
Write-Output "=== MODELS WITH tool_call=true ==="
$nvidia.models.PSObject.Properties | ForEach-Object {
    if ($_.Value.tool_call -eq $true) {
        $ctx = $_.Value.limit.context
        $out = $_.Value.limit.output
        $ci = $_.Value.cost.input
        $co = $_.Value.cost.output
        Write-Output "- $($_.Name) (context: $ctx, output: $out, cost_in: $ci, cost_out: $co)"
    }
}
