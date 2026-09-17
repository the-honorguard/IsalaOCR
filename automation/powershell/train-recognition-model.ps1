param(
    [ValidateSet("cpu","gpu")][string]$Device = "gpu",
    [string]$Dataset = "latest",
    [string]$Model = "PP-OCRv6_medium_rec",
    [int]$Epochs = 50,
    [int]$BatchSize = 0,
    [double]$LearningRate = 0.0001,
    [string]$Resume = "",
    [switch]$DetailedOutput,
    [int]$EarlyStopPatience = 10,
    [switch]$SkipTestEvaluation,
    [string]$PreflightActionId = "26"
)
. (Join-Path $PSScriptRoot "training-common.ps1")
$ContainerWorkspace = Get-IsalaContainerWorkspace
Assert-IsalaActionPreflight -ActionId $PreflightActionId
Assert-Docker
Assert-TrainingImagePrepared -Device $Device | Out-Null
if ($Dataset -eq "latest") { $Dataset = Get-LatestDatasetId }
if ($BatchSize -le 0) { $BatchSize = if ($Device -eq "gpu") { 32 } else { 4 } }
$RunId = "run-{0}-{1}" -f (Get-Date -Format "yyyyMMddTHHmmss"), $Model
$RunDirectory = Initialize-TrainingRunDirectory -Name $RunId
$RunPath = Convert-ToContainerTrainingPath $RunDirectory
$Service = if ($Device -eq "gpu") { "trainer-gpu" } else { "trainer-cpu" }
$PaddleDevice = if ($Device -eq "gpu") { "gpu:0" } else { "cpu" }
$Profile = if ($Device -eq "gpu") { "training-gpu" } else { "training" }
$argsList = @(
    "train", "--model", $Model,
    "--dataset", "$ContainerWorkspace/datasets/$Dataset",
    "--output", $RunPath,
    "--device", $PaddleDevice,
    "--epochs", $Epochs,
    "--batch-size", $BatchSize,
    "--learning-rate", $LearningRate,
    "--early-stop-patience", $EarlyStopPatience
)
if ($Resume) { $argsList += @("--resume", $Resume) }
if ($DetailedOutput) { $argsList += "--detailed-output" }
Write-Host "Run ID: $RunId"
Write-Host "Dataset: $Dataset"
Write-Host "Training device: $PaddleDevice"
Write-Host ("Console output: {0}" -f $(if ($DetailedOutput) { "detailed output plus progress" } else { "compact progress; full output is stored in the run directory" }))
if ($Device -eq "cpu") { Write-Warning "PP-OCRv6 medium training on CPU can be very slow. CPU mode is mainly for pipeline validation." }
docker compose --profile $Profile run --rm --pull never $Service @argsList
if ($LASTEXITCODE -ne 0) { throw "Training failed. Output retained under project workspace runs\$RunId" }
$HostWorkspace = Get-IsalaHostProjectWorkspace
Set-Content -Path (Join-Path $HostWorkspace "runs\latest-run.txt") -Value $RunId -NoNewline
Write-Host ("Training output: {0}" -f (Join-Path $HostWorkspace "runs\$RunId"))

$ProgressPath = Join-Path $RunDirectory "training-progress.json"
$BestValidationAccuracy = $null
if (Test-Path -LiteralPath $ProgressPath) {
    $BestValidationAccuracy = (Get-Content -LiteralPath $ProgressPath -Raw | ConvertFrom-Json).best_accuracy
}

if ($SkipTestEvaluation) {
    Write-Host "Skipping automatic held-out test evaluation (-SkipTestEvaluation)."
    return
}

# A small validation split can report 100% accuracy for most of a run while
# still failing on unseen data. Always score the trained model against the
# held-out test.txt split instead of trusting the validation curve alone.
Write-Host "Evaluating the trained model against the held-out test split..."
$TestEvalName = "test-eval-$RunId"
$env:ISALA_NESTED_PREFLIGHT_APPROVED = "1"
try {
    & (Join-Path $PSScriptRoot "export-recognition-model.ps1") -RunDirectory $RunDirectory -Model $Model -Device $Device
    & (Join-Path $PSScriptRoot "evaluate-recognition-model.ps1") -Kind custom -Dataset $Dataset -OutputName $TestEvalName
}
catch {
    Write-Warning "Automatic held-out test evaluation failed; the trained model itself is unaffected. $($_.Exception.Message)"
    Write-Warning ("Run it manually with: evaluate-recognition-model.ps1 -Kind custom -Dataset {0}" -f $Dataset)
    return
}
finally {
    Remove-Item Env:ISALA_NESTED_PREFLIGHT_APPROVED -ErrorAction SilentlyContinue
}

$EvaluationPath = Join-Path $HostWorkspace "runs\$TestEvalName\evaluation.json"
if (-not (Test-Path -LiteralPath $EvaluationPath)) {
    Write-Warning "Test evaluation completed but evaluation.json was not found at $EvaluationPath"
    return
}
$Evaluation = Get-Content -LiteralPath $EvaluationPath -Raw | ConvertFrom-Json
$TestAccuracy = $Evaluation.metrics.exact_match_accuracy
$TestCer = $Evaluation.metrics.character_error_rate
Write-Host ("Held-out test accuracy: {0:P2} (exact match) | CER: {1:P2} | samples: {2}" -f $TestAccuracy, $TestCer, $Evaluation.metrics.samples)
Write-Host ("Full report: {0}" -f (Join-Path $HostWorkspace "runs\$TestEvalName\evaluation.md"))
if ($null -ne $BestValidationAccuracy) {
    Write-Host ("Best validation accuracy during training: {0:P2}" -f $BestValidationAccuracy)
    $Gap = $BestValidationAccuracy - $TestAccuracy
    if ($Gap -gt 0.05) {
        Write-Warning ("Validation accuracy ({0:P2}) is notably higher than the held-out test accuracy ({1:P2}). This usually means the validation split is too small or not representative; trust the test result over the validation curve." -f $BestValidationAccuracy, $TestAccuracy)
    }
}
