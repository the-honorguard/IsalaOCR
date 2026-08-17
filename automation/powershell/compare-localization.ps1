. (Join-Path $PSScriptRoot "training-common.ps1")
$ContainerWorkspace = Get-IsalaContainerWorkspace
$HostWorkspace = Get-IsalaHostProjectWorkspace
Assert-IsalaActionPreflight -ActionId "10"
Assert-Docker
$SelectionFile = Join-Path $HostWorkspace "localization_artifact_selection.json"
$DatasetId = ""
$ModelId = ""
$BaselineId = ""
$TrainedId = ""
if (Test-Path -LiteralPath $SelectionFile -PathType Leaf) {
    try {
        $Selection = Get-Content -LiteralPath $SelectionFile -Raw | ConvertFrom-Json
        $DatasetId = [string]$Selection.evaluation_dataset_id
        $ModelId = [string]$Selection.evaluation_model_id
        $BaselineId = [string]$Selection.baseline_evaluation_id
        $TrainedId = [string]$Selection.trained_evaluation_id
    } catch {}
}
$Args = @("compare-localization", "--workspace", $ContainerWorkspace, "--config", "/app/config/app.yaml")
if (-not [string]::IsNullOrWhiteSpace($DatasetId)) { $Args += @("--dataset-id", $DatasetId) }
if (-not [string]::IsNullOrWhiteSpace($ModelId)) { $Args += @("--model-id", $ModelId) }
if (-not [string]::IsNullOrWhiteSpace($BaselineId)) { $Args += @("--baseline-evaluation-id", $BaselineId) }
if (-not [string]::IsNullOrWhiteSpace($TrainedId)) { $Args += @("--trained-evaluation-id", $TrainedId) }
Write-Host "Comparing the selected baseline and trained field-detector evaluations..."
docker compose --profile training run --rm --build training-collector @Args
if ($LASTEXITCODE -ne 0) { throw "Localization comparison failed." }
