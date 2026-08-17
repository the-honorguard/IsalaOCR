param(
    [string]$Dataset = "latest",
    [string]$Model = "PP-OCRv6_medium_rec"
)
. (Join-Path $PSScriptRoot "training-common.ps1")
$ContainerWorkspace = Get-IsalaContainerWorkspace
Assert-IsalaActionPreflight -ActionId "25"
Assert-IsalaDetectionGateOpen
Assert-Docker
Assert-TrainingImagePrepared -Device cpu | Out-Null
if ($Dataset -eq "latest") { $Dataset = Get-LatestDatasetId }
$OutputDirectory = Initialize-TrainingRunDirectory -Name "check-$Dataset" -Reset
$Output = Convert-ToContainerTrainingPath $OutputDirectory
docker compose --profile training run --rm --pull never trainer-cpu `
    check --model $Model --dataset "$ContainerWorkspace/datasets/$Dataset" --output $Output
if ($LASTEXITCODE -ne 0) { throw "Dataset validation failed. Check charset_report.json and PaddleX output." }
