$json = Get-Content 'C:\Users\seand\AppData\Local\AgentProfiles\kilo-a\cache\kilo\models.json' -Raw | ConvertFrom-Json
$nvidia = $json.nvidia
Write-Output "=== NVIDIA PROVIDER ==="
Write-Output "env: $($nvidia.env -join ', ')"
Write-Output "api: $($nvidia.api)"
Write-Output "name: $($nvidia.name)"
Write-Output ""
Write-Output "=== MODELS WITH tool_call=true ==="
$nvidia.models.PSObject.Properties | Where-Object { $_.Value.tool_call -eq $true } | ForEach-Object {
    $m = $_.Value
    Write-Output "id: $($m.id)"
    Write-Output "  name: $($m.name)"
    Write-Output "  family: $($m.family)"
    Write-Output "  context: $($m.limit.context)"
    Write-Output "  output: $($m.limit.output)"
    Write-Output "  cost_input: $($m.cost.input)"
    Write-Output "  cost_output: $($m.cost.output)"
    Write-Output "---"
}
