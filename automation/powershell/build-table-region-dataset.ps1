. (Join-Path $PSScriptRoot "training-common.ps1")
. (Join-Path $PSScriptRoot "runtime-preparation.ps1")
Assert-IsalaActionPreflight -ActionId "54"
Assert-Docker
Assert-IsalaRuntimePrepared | Out-Null
$ContainerWorkspace = Get-IsalaContainerWorkspace
Write-Host "Building full-page table-region COCO dataset from Step-2 GT..." -ForegroundColor Cyan
docker compose --profile training run --rm --build dataset-builder `
    build-table-region-dataset --workspace $ContainerWorkspace --config /app/config/app.yaml
if ($LASTEXITCODE -ne 0) { throw "Table-region dataset build failed." }
