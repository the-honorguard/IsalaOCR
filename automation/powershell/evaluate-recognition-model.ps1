param(
    [ValidateSet("baseline","custom")][string]$Kind = "baseline",
    [string]$Dataset = "latest",
    [string]$Model = "PP-OCRv6_medium_rec",
    [string]$ModelDirectory = "",
    [string]$OutputName = "",
    [string]$PreflightActionId = ""
)
. (Join-Path $PSScriptRoot "training-common.ps1")
if ([string]::IsNullOrWhiteSpace($PreflightActionId)) {
    $PreflightActionId = if ($Kind -eq "baseline") { "109" } else { "113" }
}
Assert-IsalaActionPreflight -ActionId $PreflightActionId
Assert-Docker
if ($Dataset -eq "latest") { $Dataset = Get-LatestDatasetId }
if (-not $OutputName) { $OutputName = "evaluation-$Kind-$(Get-Date -Format 'yyyyMMddTHHmmss')" }
$OutputDirectory = Initialize-TrainingRunDirectory -Name $OutputName
$Output = Convert-ToContainerTrainingPath $OutputDirectory

if ($Kind -eq "baseline") {
    $BaselineDirectory = Join-Path $ProjectRoot ("models\paddlex\official_models\{0}" -f $Model)
    $Metadata = @(
        "inference.json",
        "inference.pdmodel",
        "model.safetensors"
    ) | ForEach-Object { Join-Path $BaselineDirectory $_ } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
    $Weights = @(
        Get-ChildItem -LiteralPath $BaselineDirectory -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "*.pdiparams" -or $_.Name -like "*.safetensors" }
    )
    if ($Metadata.Count -eq 0 -or $Weights.Count -eq 0) {
        throw @"
Offline baseline model is missing: $Model
Expected model files under:
$BaselineDirectory
Run training menu option 1 once, then retry option 9.
"@
    }
}

$argsList = @(
    "evaluate-recognition", "--dataset", $Dataset,
    "--workspace", "/training/workspace",
    "--config", "/app/config/app.yaml",
    "--output", $Output,
    "--split", "test"
)
if ($Kind -eq "baseline") {
    $argsList += @("--model-name", $Model)
} else {
    if (-not $ModelDirectory) {
        $ModelDirectory = Get-InferenceDirectory (Get-LatestRunDirectory)
    }
    $argsList += @("--model-dir", (Convert-ToContainerTrainingPath $ModelDirectory))
}
docker compose --profile training run --rm --build evaluator @argsList
if ($LASTEXITCODE -ne 0) { throw "Evaluation failed." }
Write-Host "Evaluation: training\workspace\runs\$OutputName"
