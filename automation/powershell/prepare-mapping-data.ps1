param([string]$SourceId = "")
. (Join-Path $PSScriptRoot "training-common.ps1")
. (Join-Path $PSScriptRoot "runtime-preparation.ps1")
Assert-IsalaActionPreflight -ActionId "20"
Assert-IsalaDetectionGateOpen
Assert-Docker
Assert-IsalaRuntimePrepared | Out-Null
$ProjectInput = Get-IsalaContainerProjectInput
Write-Host "Pipeline B: creating semantic OCR blocks and mapping suggestions from canonical table-cell Ground Truth..."
$args = @(
    "compose","--profile","training","run","--rm","--pull","never",
    "--entrypoint","python",
    "training-collector",
    "-m","isala_ocr.mapping_gt_cli",
    "collect-mapping",
    "--input",$ProjectInput,
    "--workspace","/training/workspace",
    "--config","/app/config/app.yaml"
)
& docker @args
if ($LASTEXITCODE -ne 0) { throw "Mapping preparation failed. Open STDERR in the activity dock for the Python/Docker error." }
