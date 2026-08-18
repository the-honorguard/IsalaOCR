param(
    [int]$Augmentations = 2,
    [int]$MinimumSamples = 32
)
. (Join-Path $PSScriptRoot "training-common.ps1")
. (Join-Path $PSScriptRoot "runtime-preparation.ps1")
Assert-IsalaActionPreflight -ActionId "24"
Assert-IsalaDetectionGateOpen
Assert-Docker
Assert-IsalaRuntimePrepared | Out-Null
$dockerArguments = @(
    "compose", "--profile", "training", "run", "--rm", "--pull", "never",
    "--entrypoint", "python",
    "dataset-builder",
    "-m", "isala_ocr.table_first_cli",
    "build-dataset",
    "--workspace", "/training/workspace",
    "--config", "/app/config/app.yaml",
    "--augmentations", $Augmentations,
    "--minimum-samples", $MinimumSamples
)
& docker @dockerArguments
if ($LASTEXITCODE -ne 0) { throw "Dataset build failed. Open STDERR in the activity dock for the Python/Docker error." }
