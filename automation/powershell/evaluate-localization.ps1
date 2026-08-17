. (Join-Path $PSScriptRoot "training-common.ps1")
$ContainerWorkspace = Get-IsalaContainerWorkspace
$HostWorkspace = Get-IsalaHostProjectWorkspace
Assert-IsalaActionPreflight -ActionId "9"
Assert-Docker

$SelectionFile = Join-Path $HostWorkspace "localization_artifact_selection.json"
$Selection = $null
if (Test-Path -LiteralPath $SelectionFile -PathType Leaf) {
    try { $Selection = Get-Content -LiteralPath $SelectionFile -Raw | ConvertFrom-Json } catch { $Selection = $null }
}
$DatasetId = if ($null -ne $Selection) { [string]$Selection.evaluation_dataset_id } else { "" }
if ([string]::IsNullOrWhiteSpace($DatasetId)) {
    $DatasetPointer = Join-Path $HostWorkspace "localization_datasets\latest.txt"
    if (Test-Path -LiteralPath $DatasetPointer -PathType Leaf) {
        $DatasetId = (Get-Content -LiteralPath $DatasetPointer -Raw).Trim()
    }
}
if ([string]::IsNullOrWhiteSpace($DatasetId)) { throw "Select or build a localization dataset before evaluation." }

$ModelId = if ($null -ne $Selection) { [string]$Selection.evaluation_model_id } else { "" }
$InferenceDir = ""
$Device = ""

# The persisted UI selection stores the stable model ID, not a full model object.
# Resolve runtime metadata from the per-run registration file so Step 5 always
# evaluates the detector the user actually selected.
if (-not [string]::IsNullOrWhiteSpace($ModelId)) {
    $RunsRoot = Join-Path $HostWorkspace "localization_runs"
    if (Test-Path -LiteralPath $RunsRoot -PathType Container) {
        foreach ($RegistrationFile in Get-ChildItem -LiteralPath $RunsRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object { Join-Path $_.FullName "isala_model_registration.json" }) {
            if (-not (Test-Path -LiteralPath $RegistrationFile -PathType Leaf)) { continue }
            try { $Registration = Get-Content -LiteralPath $RegistrationFile -Raw | ConvertFrom-Json } catch { continue }
            if ([string]$Registration.model_id -ne $ModelId) { continue }
            $InferenceDir = [string]$Registration.inference_dir
            $Device = [string]$Registration.device
            break
        }
    }
}
if ([string]::IsNullOrWhiteSpace($ModelId) -or [string]::IsNullOrWhiteSpace($InferenceDir)) {
    Write-Host "No usable field detector is selected. Running baseline-only test evaluation." -ForegroundColor Yellow
    if (-not [string]::IsNullOrWhiteSpace($ModelId)) {
        Write-Host "Selected model ID: $ModelId, but its run registration/inference path could not be resolved." -ForegroundColor Yellow
    }
    docker compose --profile training run --rm --build training-collector `
        evaluate-localization --workspace $ContainerWorkspace --config /app/config/app.yaml `
        --kind baseline --dataset-id $DatasetId --split test
    if ($LASTEXITCODE -ne 0) { throw "Localization baseline evaluation failed." }
    return
}
if ($Device -notin @("cpu", "gpu")) { $Device = "gpu" }
$Service = if ($Device -eq "gpu") { "trainer-gpu-detection" } else { "trainer-cpu" }
$Profile = if ($Device -eq "gpu") { "training-gpu-detection" } else { "training" }
$SafeModelId = ($ModelId -replace '[^A-Za-z0-9._-]', '_')
$Predictions = "$ContainerWorkspace/localization_diagnostics/predictions-$SafeModelId.json"

Write-Host "Generating low-threshold predictions for selected detector $ModelId..."
docker compose --profile $Profile run --rm --pull never --entrypoint python3 $Service `
    /opt/isala-training/localization_runner.py predict `
    --model-dir $InferenceDir --input $ContainerWorkspace/source_renders --output $Predictions --device $Device --threshold 0.01
if ($LASTEXITCODE -ne 0) { throw "Field-detector diagnostic prediction run failed." }

Write-Host "1/3 - Checking TRAIN and calibrating confidence on VALIDATION..." -ForegroundColor Cyan
docker compose --profile training run --rm --build training-collector `
    diagnose-localization-predictions --workspace $ContainerWorkspace --config /app/config/app.yaml `
    --predictions $Predictions --model-id $ModelId --dataset-id $DatasetId `
    --splits train,val `
    --thresholds 0.01,0.05,0.10,0.15,0.20,0.25,0.35,0.50,0.60,0.70,0.80,0.90,0.95
if ($LASTEXITCODE -ne 0) { throw "Field-detector TRAIN/VALIDATION diagnostic failed." }

$DiagnosticPath = Join-Path $HostWorkspace "localization_diagnostics\latest_trained.json"
if (-not (Test-Path -LiteralPath $DiagnosticPath -PathType Leaf)) { throw "Diagnostic result was not written: $DiagnosticPath" }
$Diagnostic = Get-Content -LiteralPath $DiagnosticPath -Raw | ConvertFrom-Json
$DiagnosticThreshold = 0.25
if ($null -ne $Diagnostic.recommended_threshold) { $DiagnosticThreshold = [double]$Diagnostic.recommended_threshold }

Write-Host ("2/3 - Persisting VALIDATION result at diagnostic confidence {0:N2}..." -f $DiagnosticThreshold) -ForegroundColor Cyan
docker compose --profile training run --rm --build training-collector `
    evaluate-localization-predictions --workspace $ContainerWorkspace --config /app/config/app.yaml `
    --predictions $Predictions --model-id $ModelId --dataset-id $DatasetId --split val --minimum-confidence $DiagnosticThreshold
if ($LASTEXITCODE -ne 0) { throw "Field-detector validation evaluation failed." }

if ($null -eq $Diagnostic.production_threshold) {
    Write-Host "3/3 - HOLD-OUT TEST SKIPPED" -ForegroundColor Yellow
    Write-Host "No confidence threshold satisfies the validation quality criteria. De geparkeerde box-detector-evaluatie bevat de aanbevolen modelverbeteractie. Improve TRAIN/VALIDATION first; TEST remains untouched." -ForegroundColor Yellow
    return
}

$ProductionThreshold = [double]$Diagnostic.production_threshold
Write-Host ("3/3 - VALIDATION READY. Running one final TEST at locked confidence {0:N2}..." -f $ProductionThreshold) -ForegroundColor Green
Write-Host "The TEST result must not be used to retune confidence. If it fails, improve TRAIN/VALIDATION and use a fresh hold-out for a future final assessment." -ForegroundColor Yellow

docker compose --profile training run --rm --build training-collector `
    evaluate-localization --workspace $ContainerWorkspace --config /app/config/app.yaml `
    --kind baseline --dataset-id $DatasetId --split test
if ($LASTEXITCODE -ne 0) { throw "Localization baseline test evaluation failed." }

docker compose --profile training run --rm --build training-collector `
    evaluate-localization-predictions --workspace $ContainerWorkspace --config /app/config/app.yaml `
    --predictions $Predictions --model-id $ModelId --dataset-id $DatasetId --split test --minimum-confidence $ProductionThreshold
if ($LASTEXITCODE -ne 0) { throw "Final field-detector test evaluation failed to execute." }

Write-Host "Comparing baseline and selected trained detector on the same final test split..."
docker compose --profile training run --rm --build training-collector `
    compare-localization --workspace $ContainerWorkspace --config /app/config/app.yaml `
    --dataset-id $DatasetId --model-id $ModelId
if ($LASTEXITCODE -ne 0) { throw "Localization comparison failed." }

Write-Host "Smart evaluation pipeline complete for $ModelId on $DatasetId." -ForegroundColor Green
