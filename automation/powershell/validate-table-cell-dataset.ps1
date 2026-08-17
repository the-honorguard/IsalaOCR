. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-IsalaActionPreflight -ActionId "49"
Assert-Docker
$ContainerWorkspace = Get-IsalaContainerWorkspace
Write-Host "Validating reviewed table-cell dataset..." -ForegroundColor Cyan
docker compose --profile training run --rm --build dataset-builder `
    validate-table-cell-dataset --workspace $ContainerWorkspace --config /app/config/app.yaml --dataset latest
if ($LASTEXITCODE -ne 0) { throw "Table-cell dataset validation failed." }
