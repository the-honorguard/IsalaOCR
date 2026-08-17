. (Join-Path $PSScriptRoot "training-common.ps1")
$ContainerWorkspace = Get-IsalaContainerWorkspace
$HostWorkspace = Get-IsalaHostProjectWorkspace
Assert-IsalaActionPreflight -ActionId "6"
Assert-Docker
Assert-TrainingImagePrepared -Device cpu | Out-Null
$Pointer = Join-Path $HostWorkspace "localization_datasets\latest.txt"
if (-not (Test-Path -LiteralPath $Pointer -PathType Leaf)) { throw "No localization dataset exists. Open de geparkeerde fallbackpagina Losse box-detector trainen en bouw daar eerst de localization-dataset." }
$DatasetId = (Get-Content -LiteralPath $Pointer -Raw).Trim()
$DatasetRoot = Join-Path $HostWorkspace ("localization_datasets\{0}" -f $DatasetId)
$ReadyMarker = Join-Path $DatasetRoot "training_ready.json"
# A validation attempt invalidates any previous canonical readiness marker until
# both the IsalaOCR and PaddleX checks have completed successfully again.
if (Test-Path -LiteralPath $ReadyMarker -PathType Leaf) {
    Remove-Item -LiteralPath $ReadyMarker -Force -ErrorAction SilentlyContinue
}
Write-Host ("Current localization dataset: {0}" -f $DatasetId)
Write-Host "Validating localization dataset structure and bounding boxes with IsalaOCR..."
docker compose --profile training run --rm --build dataset-builder `
    validate-localization-dataset --workspace $ContainerWorkspace --config /app/config/app.yaml --dataset $DatasetId
if ($LASTEXITCODE -ne 0) { throw "IsalaOCR localization dataset validation failed." }
Write-Host "Validating the same COCO dataset with PaddleX/PaddleDetection..."
docker compose --profile training run --rm --pull never --entrypoint python3 trainer-cpu `
    /opt/isala-training/localization_runner.py validate `
    --dataset "$ContainerWorkspace/localization_datasets/$DatasetId" `
    --output "$ContainerWorkspace/localization_datasets/$DatasetId/paddlex_validation"
if ($LASTEXITCODE -ne 0) { throw "PaddleX rejected the localization dataset." }
$ManifestPath = Join-Path $DatasetRoot "manifest.json"
$AppValidationPath = Join-Path $DatasetRoot "validation.json"
$PaddleXValidationPath = Join-Path $DatasetRoot "paddlex_validation\isala_paddlex_validation.json"
$ManifestHash = if (Test-Path -LiteralPath $ManifestPath -PathType Leaf) { (Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant() } else { "" }
$ReadyPayload = [ordered]@{
    status = "ok"
    ready = $true
    dataset_id = $DatasetId
    manifest_sha256 = $ManifestHash
    app_validation = "ok"
    paddlex_validation = "ok"
    app_validation_path = "validation.json"
    paddlex_validation_path = "paddlex_validation/isala_paddlex_validation.json"
    validated_at = (Get-Date).ToUniversalTime().ToString("o")
}
$ReadyJson = $ReadyPayload | ConvertTo-Json -Depth 6
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($ReadyMarker,$ReadyJson,$Utf8NoBom)
Write-Host ("Training-ready marker written: {0}" -f $ReadyMarker)
Write-Host "Localization dataset is valid for field-detector training."
