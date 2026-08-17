param(
    [string]$RunDirectory = "",
    [string]$EvaluationFile = "",
    [string]$ModelId = ""
)
. (Join-Path $PSScriptRoot "training-common.ps1")
$ContainerRegistry = Get-IsalaContainerRegistry
Assert-IsalaActionPreflight -ActionId "115"
Assert-Docker
if (-not $RunDirectory) { $RunDirectory = Get-LatestRunDirectory }
if (-not $EvaluationFile) { $EvaluationFile = Get-LatestEvaluationFile "custom" }
$argsList = @(
    "register-model", "--config", "/app/config/app.yaml",
    "--registry", $ContainerRegistry,
    "--run", (Convert-ToContainerTrainingPath $RunDirectory),
    "--evaluation", (Convert-ToContainerTrainingPath $EvaluationFile)
)
if ($ModelId) { $argsList += @("--model-id", $ModelId) }
docker compose --profile training run --rm --build model-manager @argsList
if ($LASTEXITCODE -ne 0) { throw "Model registration failed." }
