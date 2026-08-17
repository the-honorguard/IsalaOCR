param(
    [int]$Augmentations = 2,
    [int]$MinimumSamples = 32
)
. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-IsalaActionPreflight -ActionId "24"
Assert-IsalaDetectionGateOpen
Assert-Docker
docker compose --profile training run --rm --build dataset-builder `
    build-dataset --workspace /training/workspace --config /app/config/app.yaml `
    --augmentations $Augmentations --minimum-samples $MinimumSamples
if ($LASTEXITCODE -ne 0) { throw "Dataset build failed." }
