param()
. (Join-Path $PSScriptRoot "training-common.ps1")
. (Join-Path $PSScriptRoot "runtime-preparation.ps1")

$projectWorkspace = Get-IsalaHostProjectWorkspace
$groundTruthPath = Join-Path $projectWorkspace "table_cell_ground_truth.json"
if (-not (Test-Path -LiteralPath $groundTruthPath -PathType Leaf)) {
    throw "Canonical table-cell Ground Truth is missing: $groundTruthPath. Complete Steps 3-4 before Recognition GT."
}
$renderRoot = Join-Path $projectWorkspace "source_renders"
$renderCount = if (Test-Path -LiteralPath $renderRoot -PathType Container) { @(Get-ChildItem -LiteralPath $renderRoot -Filter '*.png' -File -ErrorAction SilentlyContinue).Count } else { 0 }
if ($renderCount -lt 1) {
    throw "No source renders are available for Recognition GT. Complete the geometry Ground Truth flow first."
}

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
