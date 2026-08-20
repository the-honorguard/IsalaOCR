param()
. (Join-Path $PSScriptRoot "training-common.ps1")
. (Join-Path $PSScriptRoot "runtime-preparation.ps1")
Assert-IsalaActionPreflight -ActionId "23"
Assert-IsalaDetectionGateOpen
Assert-Docker
Assert-IsalaRuntimePrepared | Out-Null

$dockerArguments = @(
    "compose", "--profile", "training", "run", "--rm", "--pull", "never",
    "--entrypoint", "python",
    "dataset-builder",
    "-m", "isala_ocr.recognition_gt_cli",
    "--workspace", "/training/workspace",
    "--config", "/app/config/app.yaml"
)
& docker @dockerArguments
if ($LASTEXITCODE -ne 0) {
    throw "Recognition-GT preparation failed. Open STDERR in the activity dock for the Python/Docker error."
}
