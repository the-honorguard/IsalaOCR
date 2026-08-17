. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-IsalaActionPreflight -ActionId "11"
Assert-Docker
$HostWorkspace = Get-IsalaHostProjectWorkspace
$ContainerWorkspace = Get-IsalaContainerWorkspace
$SelectionFile = Join-Path $HostWorkspace "localization_artifact_selection.json"
if (-not (Test-Path -LiteralPath $SelectionFile -PathType Leaf)) {
    throw "No field detector is selected. Open de geparkeerde fallbackpagina Box-detector evalueren of Projecten & modellen en selecteer eerst een detector."
}
$Selection = Get-Content -LiteralPath $SelectionFile -Raw | ConvertFrom-Json
$Info = $Selection.model
if ($null -eq $Info) { throw "The selected field detector metadata is missing. Select the model again." }
$ModelId = [string]$Info.model_id
$InferenceDir = [string]$Info.path
$Device = [string]$Info.device
if ([string]::IsNullOrWhiteSpace($ModelId) -or [string]::IsNullOrWhiteSpace($InferenceDir)) {
    throw "The selected field detector metadata is incomplete."
}
if ($Device -notin @("cpu", "gpu")) { $Device = "gpu" }
Write-Host "Activating selected field detector $ModelId. Its current test evaluation on the active work dataset must satisfy the detection gate."
docker compose --profile training run --rm --build training-collector `
    register-localization-model --workspace $ContainerWorkspace --config /app/config/app.yaml `
    --model-id $ModelId --model-name PicoDet-S --model-dir $InferenceDir `
    --device $Device --activate
if ($LASTEXITCODE -ne 0) { throw "Field-detector activation failed. Inspect the selected model, active dataset and Detection Gate." }
