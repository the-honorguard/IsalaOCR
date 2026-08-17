param(
    [string]$BaselineEvaluation = "",
    [string]$CustomEvaluation = "",
    [string]$OutputName = "comparison-$(Get-Date -Format 'yyyyMMddTHHmmss')"
)
. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-IsalaActionPreflight -ActionId "114"
Assert-Docker
if (-not $BaselineEvaluation) { $BaselineEvaluation = Get-LatestEvaluationFile "baseline" }
if (-not $CustomEvaluation) { $CustomEvaluation = Get-LatestEvaluationFile "custom" }
$baseline = Convert-ToContainerTrainingPath $BaselineEvaluation
$custom = Convert-ToContainerTrainingPath $CustomEvaluation
$outputDirectory = Initialize-TrainingRunDirectory -Name $OutputName
$output = Convert-ToContainerTrainingPath $outputDirectory
docker compose --profile training run --rm --build evaluator `
    compare-evaluations --baseline $baseline --custom $custom --output $output
$exit = $LASTEXITCODE
Write-Host "Comparison: training\workspace\runs\$OutputName"
if ($exit -ne 0) { throw "Comparison failed." }
Write-Host "Comparison completed. The winning model is shown in comparison.json and in the web interface."
