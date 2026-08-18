. (Join-Path $PSScriptRoot "training-common.ps1")
. (Join-Path $PSScriptRoot "runtime-preparation.ps1")
Assert-IsalaActionPreflight -ActionId "48"
Assert-Docker
Assert-IsalaRuntimePrepared | Out-Null
$ContainerWorkspace = Get-IsalaContainerWorkspace
$HostWorkspace = Get-IsalaHostProjectWorkspace
New-Item -ItemType Directory -Force -Path $HostWorkspace | Out-Null
Write-Host "Building table-cell COCO dataset from completed table reviews..." -ForegroundColor Cyan
docker compose --profile training run --rm --pull never dataset-builder `
    build-table-cell-dataset --workspace $ContainerWorkspace --config /app/config/app.yaml
if ($LASTEXITCODE -ne 0) { throw "Table-cell dataset build failed." }
