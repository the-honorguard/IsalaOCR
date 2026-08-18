. (Join-Path $PSScriptRoot "training-common.ps1")
. (Join-Path $PSScriptRoot "runtime-preparation.ps1")
Assert-IsalaActionPreflight -ActionId "49"
Assert-Docker
Assert-IsalaRuntimePrepared | Out-Null
$ContainerWorkspace = Get-IsalaContainerWorkspace
Write-Host "Validating reviewed table-cell dataset..." -ForegroundColor Cyan
docker compose --profile training run --rm --pull never dataset-builder `
    validate-table-cell-dataset --workspace $ContainerWorkspace --config /app/config/app.yaml --dataset latest
if ($LASTEXITCODE -ne 0) { throw "Table-cell dataset validation failed." }

$HostWorkspace = Get-IsalaHostProjectWorkspace
$pointer = Join-Path $HostWorkspace "table_cell_datasets\latest.txt"
if (-not (Test-Path -LiteralPath $pointer -PathType Leaf)) { throw "Table-cell dataset pointer ontbreekt na validatie." }
$datasetId = ([string](Get-Content -LiteralPath $pointer -Raw)).Trim()
if ([string]::IsNullOrWhiteSpace($datasetId)) { throw "Table-cell dataset pointer is leeg." }
$ContainerDataset = "$ContainerWorkspace/table_cell_datasets/$datasetId"

Write-Host "Running strict numeric/geometry sanity check before training..." -ForegroundColor Cyan
docker compose --profile training run --rm --pull never --entrypoint python dataset-builder `
    /opt/isala-training/table_cell_dataset_sanity.py --dataset $ContainerDataset
if ($LASTEXITCODE -ne 0) {
    throw "Table-cell dataset contains invalid numeric/geometry data. Review validation.json for the exact image/annotation."
}
