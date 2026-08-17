param(
    [ValidateSet("cpu","gpu")][string]$Device = "gpu",
    [string]$Dataset = "latest",
    [string]$Model = "PP-OCRv6_medium_rec",
    [int]$Epochs = 50,
    [int]$BatchSize = 0,
    [double]$LearningRate = 0.0001,
    [string]$Resume = "",
    [switch]$DetailedOutput,
    [string]$PreflightActionId = "26"
)
. (Join-Path $PSScriptRoot "training-common.ps1")
$ContainerWorkspace = Get-IsalaContainerWorkspace
Assert-IsalaActionPreflight -ActionId $PreflightActionId
Assert-IsalaDetectionGateOpen
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
    "--learning-rate", $LearningRate
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
