param(
    [string]$RunDirectory = "",
    [string]$WeightFile = "",
    [string]$Model = "PP-OCRv6_medium_rec",
    [ValidateSet("cpu","gpu")][string]$Device = "gpu"
)
. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-IsalaActionPreflight -ActionId "112"
Assert-Docker
Assert-TrainingImagePrepared -Device $Device | Out-Null
if (-not $RunDirectory) { $RunDirectory = Get-LatestRunDirectory }
$RunDirectory = (Resolve-Path $RunDirectory).Path
if (-not $WeightFile) {
    $weights = Get-ChildItem $RunDirectory -Recurse -Filter *.pdparams -File |
        Sort-Object @{Expression={ if ($_.FullName -match "best_accuracy") { 0 } else { 1 } }}, LastWriteTime -Descending
    if (-not $weights) { throw "No .pdparams weights found under $RunDirectory" }
    $WeightFile = $weights[0].FullName
}
$OutputDirectory = Join-Path $RunDirectory "exported"
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$service = if ($Device -eq "gpu") { "trainer-gpu" } else { "trainer-cpu" }
$profile = if ($Device -eq "gpu") { "training-gpu" } else { "training" }
$paddleDevice = if ($Device -eq "gpu") { "gpu:0" } else { "cpu" }
docker compose --profile $profile run --rm --pull never $service `
    export --model $Model --device $paddleDevice `
    --weight (Convert-ToContainerTrainingPath $WeightFile) `
    --output (Convert-ToContainerTrainingPath $OutputDirectory)
if ($LASTEXITCODE -ne 0) { throw "Model export failed." }
Write-Host "Inference model: $OutputDirectory"
