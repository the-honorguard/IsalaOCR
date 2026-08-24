. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-IsalaActionPreflight -ActionId "57"
$HostWorkspace = Get-IsalaHostProjectWorkspace
$RunsRoot = Join-Path $HostWorkspace "table_region_runs"
$candidate = Get-ChildItem -LiteralPath $RunsRoot -Directory -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "model.json") } |
    Select-Object -First 1
if ($null -eq $candidate) { throw "Geen getraind tabelregio-model gevonden." }
$model = Get-Content -LiteralPath (Join-Path $candidate.FullName "model.json") -Raw | ConvertFrom-Json
$model.active = $true
$model | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $HostWorkspace "table_region_modelsactive.json") -Encoding UTF8
Write-Host "Actief tabelregio-model: $($model.model_id)" -ForegroundColor Green
