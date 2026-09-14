param([string]$SourceId = "")
# TEMPORARY: Detectie-lab cell-merging regression investigation. Remove this
# script, the "62" action-catalog entry in preflight.ps1, the "62" wiring in
# training-menu.ps1/webui-worker.ps1/routes_jobs.py/webui.py,
# isala_ocr.detection_lab_cli and routes_detection_lab.py together once the
# regression is understood and one approach has been folded into the real
# pipeline.
. (Join-Path $PSScriptRoot "training-common.ps1")
. (Join-Path $PSScriptRoot "runtime-preparation.ps1")
Assert-IsalaActionPreflight -ActionId "62"
Assert-Docker
Assert-IsalaRuntimePrepared | Out-Null
if (-not $SourceId) { throw "Detectie-lab vereist een bron-ID." }
Write-Host "Detectie-lab: drie celdetectie-aanpakken vergelijken voor bron $SourceId..."
$args = @(
    "compose","--profile","training","run","--rm","--pull","never",
    "--entrypoint","python",
    "training-collector",
    "-m","isala_ocr.detection_lab_cli",
    "run",
    "--source-id",$SourceId,
    "--workspace","/training/workspace",
    "--config","/app/config/app.yaml"
)
& docker @args
if ($LASTEXITCODE -ne 0) { throw "Detectie-lab-vergelijking mislukt. Open STDERR in de activity dock voor de Python/Docker-fout." }
