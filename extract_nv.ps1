$j = Get-Content 'C:\Users\seand\AppData\Local\AgentProfiles\kilo-a\cache\kilo\models.json' -Raw | ConvertFrom-Json
$n = $j.nvidia
$env = $n.env -join ','
$api = $n.api
$name = $n.name
Write-Output "ENV:$env"
Write-Output "API:$api"
Write-Output "NAME:$name"
$n.models.PSObject.Properties | Where-Object { $_.Value.tool_call -eq $true } | ForEach-Object {
    $m = $_.Value
    $l = $m.limit
    $c = $m.cost
    Write-Output "MODEL:$($m.id)|$($m.name)|$($m.family)|$($l.context)|$($l.output)|$($c.input)|$($c.output)"
}
