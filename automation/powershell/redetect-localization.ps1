. (Join-Path $PSScriptRoot "training-common.ps1")
$ContainerWorkspace = Get-IsalaContainerWorkspace
$HostWorkspace = Get-IsalaHostProjectWorkspace
$ProjectInput = Get-IsalaContainerProjectInput
Assert-IsalaActionPreflight -ActionId "12"
Assert-Docker
$ActivePath = Join-Path $HostWorkspace "localization_models\active.json"
if (-not (Test-Path -LiteralPath $ActivePath -PathType Leaf)) { throw "No active field detector. Activeer eerst een model via de geparkeerde fallbackpagina Box-detector activeren." }
$Active = Get-Content -LiteralPath $ActivePath -Raw | ConvertFrom-Json
$ActiveModelId = [string]$Active.model_id
$ActiveModelPath = [string]$Active.path
$Device = if ([string]$Active.device -eq "gpu") { "gpu" } else { "cpu" }
$Service = if ($Device -eq "gpu") { "trainer-gpu" } else { "trainer-cpu" }
$Profile = if ($Device -eq "gpu") { "training-gpu" } else { "training" }
Write-Host "Refreshing neutral text/table geometry first..."
docker compose --profile training run --rm --build training-collector `
    collect-training --input $ProjectInput --workspace $ContainerWorkspace --config /app/config/app.yaml
if ($LASTEXITCODE -ne 0) { throw "Baseline geometry collection failed before field-model fusion." }
$Stamp = Get-Date -Format "yyyyMMddTHHmmss"
$Predictions = "$ContainerWorkspace/localization_predictions/active-$Stamp.json"
Write-Host "Running active field detector $($Active.model_id)..."
docker compose --profile $Profile run --rm --pull never --entrypoint python3 $Service `
    /opt/isala-training/localization_runner.py predict `
    --model-dir $ActiveModelPath --input $ContainerWorkspace/source_renders --output $Predictions --device $Device --threshold 0.25
if ($LASTEXITCODE -ne 0) { throw "Active field-detector prediction failed." }
Write-Host "Fusing trained predictions with OCR/table geometry; no value OCR is performed..."
docker compose --profile training run --rm --build training-collector `
    merge-localization-predictions --workspace $ContainerWorkspace --config /app/config/app.yaml `
    --predictions $Predictions --model-id $ActiveModelId
if ($LASTEXITCODE -ne 0) { throw "Field-detector fusion failed." }
