param(
    [ValidateSet("cpu","gpu")][string]$Device = "gpu",
    [int]$Epochs = 0
)
. (Join-Path $PSScriptRoot "training-common.ps1")
$ActionId = if ($Device -eq "gpu") { "50" } else { "51" }
Assert-IsalaActionPreflight -ActionId $ActionId
Assert-Docker
$ContainerWorkspace = Get-IsalaContainerWorkspace
$HostWorkspace = Get-IsalaHostProjectWorkspace
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

$TrainingDevice = if ($Device -eq "gpu") { "gpu-detection" } else { "cpu" }
if (-not (Test-TrainingImagePrepared -Device $TrainingDevice)) {
    Write-Host "Table-cell training runtime is not prepared yet; preparing it now..." -ForegroundColor Cyan
    $oldNested = $env:ISALA_NESTED_PREFLIGHT_APPROVED
    try {
        $env:ISALA_NESTED_PREFLIGHT_APPROVED = "1"
        & (Join-Path $PSScriptRoot "prepare-training.ps1") `
            -Component $(if ($Device -eq "gpu") { "gpu-detection" } else { "cpu-detection" }) `
            -Phase full -PreflightActionId $ActionId
    }
    finally { $env:ISALA_NESTED_PREFLIGHT_APPROVED = $oldNested }
}
Assert-TrainingImagePrepared -Device $TrainingDevice | Out-Null

$Pretrain = Join-Path $ProjectRoot "models\training\RT-DETR-L_wireless_table_cell_det_pretrained.pdparams"
if (-not (Test-Path -LiteralPath $Pretrain -PathType Leaf) -or (Get-Item -LiteralPath $Pretrain).Length -le 1MB) {
    Write-Host "Downloading official RT-DETR-L wireless table-cell pretrained weight..." -ForegroundColor Cyan
    & docker compose --profile setup build model-prep
    if ($LASTEXITCODE -ne 0) { throw "Model-prep helper could not be built." }
    & docker compose --profile setup run --rm --pull never --entrypoint python model-prep `
        /opt/isala-training/paddlex_runner.py download-pretrain `
        --model RT-DETR-L_wireless_table_cell_det --pretrain-root /models/training
    if ($LASTEXITCODE -ne 0) { throw "Wireless table-cell pretrained-weight download failed." }
}

$Pointer = Join-Path $HostWorkspace "table_cell_datasets\latest.txt"
if (-not (Test-Path -LiteralPath $Pointer -PathType Leaf)) { throw "No table-cell dataset exists. Build and validate the dataset first." }
$DatasetId = (Get-Content -LiteralPath $Pointer -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($DatasetId)) { throw "Table-cell dataset pointer is empty." }
$ValidationPath = Join-Path $HostWorkspace ("table_cell_datasets\{0}\validation.json" -f $DatasetId)
if (-not (Test-Path -LiteralPath $ValidationPath -PathType Leaf)) { throw "Dataset has not been validated yet. Run Table-cell dataset valideren first." }
$Validation = Get-Content -LiteralPath $ValidationPath -Raw | ConvertFrom-Json
if (-not [bool]$Validation.valid) { throw "Latest table-cell dataset is invalid. Fix the dataset validation errors first." }
$ContainerDataset = "$ContainerWorkspace/table_cell_datasets/$DatasetId"

# Re-run the strict finite-number/image-bound check immediately before training.
# This closes the gap where COCO JSON containing NaN/Infinity could pass ordinary
# comparisons because every comparison with NaN evaluates to false.
Write-Host "Pre-training numeric/geometry sanity check..." -ForegroundColor Cyan
& docker compose --profile training run --rm --build --entrypoint python dataset-builder `
    /opt/isala-training/table_cell_dataset_sanity.py --dataset $ContainerDataset
if ($LASTEXITCODE -ne 0) {
    throw "Latest table-cell dataset failed the strict numeric/geometry sanity check. Review validation.json."
}

# A failed post-training registration must not force another 120-epoch run.
# Look for the newest completed + evaluated run for the current dataset that
# has not yet been registered and recover that model first.
$RunsRoot = Join-Path $HostWorkspace "table_cell_runs"
$ModelsRoot = Join-Path $HostWorkspace "table_cell_models"
$RegisteredRunIds = @{}
if (Test-Path -LiteralPath $ModelsRoot -PathType Container) {
    Get-ChildItem -LiteralPath $ModelsRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $modelJson = Join-Path $_.FullName "model.json"
        if (Test-Path -LiteralPath $modelJson -PathType Leaf) {
            try {
                $modelState = Get-Content -LiteralPath $modelJson -Raw | ConvertFrom-Json
                $registeredRunId = [string]$modelState.run_id
                if (-not [string]::IsNullOrWhiteSpace($registeredRunId)) { $RegisteredRunIds[$registeredRunId] = $true }
            } catch { }
        }
    }
}

$RecoverableRun = $null
if (Test-Path -LiteralPath $RunsRoot -PathType Container) {
    foreach ($candidate in (Get-ChildItem -LiteralPath $RunsRoot -Directory -ErrorAction SilentlyContinue | Sort-Object LastWriteTimeUtc -Descending)) {
        if ($RegisteredRunIds.ContainsKey($candidate.Name)) { continue }
        $runJson = Join-Path $candidate.FullName "table_cell_run.json"
        $evalJson = Join-Path $candidate.FullName "validation_evaluation.json"
        if (-not (Test-Path -LiteralPath $runJson -PathType Leaf) -or -not (Test-Path -LiteralPath $evalJson -PathType Leaf)) { continue }
        try {
            $runState = Get-Content -LiteralPath $runJson -Raw | ConvertFrom-Json
            if ([string]$runState.status -ne "trained") { continue }
            $runDataset = ([string]$runState.dataset -replace '\\','/').TrimEnd('/')
            if (-not $runDataset.EndsWith("/table_cell_datasets/$DatasetId")) { continue }
            $runInference = [string]$runState.inference_dir
            if ([string]::IsNullOrWhiteSpace($runInference)) { continue }
            $RecoverableRun = [pscustomobject]@{
                RunId = $candidate.Name
                InferenceDir = $runInference
                Evaluation = "$ContainerWorkspace/table_cell_runs/$($candidate.Name)/validation_evaluation.json"
            }
            break
        } catch { }
    }
}

if ($null -ne $RecoverableRun) {
    $RecoveryModelId = "table-RTDETR-L-$($RecoverableRun.RunId)"
    Write-Host "Found a completed table-cell training run whose registration did not finish: $($RecoverableRun.RunId)" -ForegroundColor Yellow
    Write-Host "Recovering registration only; the detector will NOT be trained again." -ForegroundColor Cyan
    docker compose --profile training run --rm --build training-collector `
        register-table-cell-model --workspace $ContainerWorkspace --config /app/config/app.yaml `
        --model-id $RecoveryModelId --run-id $RecoverableRun.RunId --dataset-id $DatasetId `
        --model-dir $RecoverableRun.InferenceDir --device $Device --evaluation $RecoverableRun.Evaluation
    if ($LASTEXITCODE -ne 0) { throw "Existing trained table-cell model registration failed." }
    Set-Content -LiteralPath (Join-Path $RunsRoot "latest.txt") -Value $RecoverableRun.RunId -NoNewline -Encoding ASCII
    Write-Host "Recovered and registered existing table-cell model: $RecoveryModelId" -ForegroundColor Green
    Write-Host "No retraining was performed. Review validation metrics, then activate the model explicitly." -ForegroundColor Cyan
    exit 0
}

# Iteration 2+ continues from the currently active custom detector whenever
# its training weights are still available.  The registered inference model is
# not a training checkpoint, so resolve the original run's .pdparams file.
$TrainingPretrain = "/models/training/RT-DETR-L_wireless_table_cell_det_pretrained.pdparams"
$ParentModelId = ""
$TrainingMode = "fresh"
$LearningRate = 0.0001
$EffectiveEpochs = $Epochs
$ActiveTableModelPath = Join-Path $HostWorkspace "table_cell_models\active.json"
if (Test-Path -LiteralPath $ActiveTableModelPath -PathType Leaf) {
    try {
        $ActiveTableModel = Get-Content -LiteralPath $ActiveTableModelPath -Raw | ConvertFrom-Json
        $ParentRunId = [string]$ActiveTableModel.run_id
        $ParentModelId = [string]$ActiveTableModel.model_id
        if (-not [string]::IsNullOrWhiteSpace($ParentRunId)) {
            $ParentRunRoot = Join-Path $HostWorkspace ("table_cell_runs\{0}" -f $ParentRunId)
            $ParentWeight = Get-ChildItem -LiteralPath $ParentRunRoot -Recurse -File -Filter *.pdparams -ErrorAction SilentlyContinue |
                Sort-Object @{Expression={ if ($_.FullName -match '[\\/]best_model[\\/]') { 0 } else { 1 } }}, LastWriteTimeUtc -Descending |
                Select-Object -First 1
            if ($null -ne $ParentWeight -and $ParentWeight.Length -gt 1MB) {
                # System.IO.Path.GetRelativePath is unavailable in Windows
                # PowerShell 5.1/.NET Framework. Both paths are already below the
                # project workspace, so derive the relative path portably.
                $workspaceFull = [System.IO.Path]::GetFullPath($HostWorkspace).TrimEnd('\','/')
                $weightFull = [System.IO.Path]::GetFullPath($ParentWeight.FullName)
                $workspacePrefix = $workspaceFull + [System.IO.Path]::DirectorySeparatorChar
                if (-not $weightFull.StartsWith($workspacePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw "Active model checkpoint is outside the project workspace: $weightFull"
                }
                $relativeWeight = $weightFull.Substring($workspacePrefix.Length).Replace('\','/')
                $TrainingPretrain = "$ContainerWorkspace/$relativeWeight"
                $TrainingMode = "continue"
                $LearningRate = 0.00003
                if ($EffectiveEpochs -le 0) { $EffectiveEpochs = 40 }
                Write-Host "Continuing from active custom model $ParentModelId ($ParentRunId)." -ForegroundColor Cyan
                Write-Host "Continuation learning rate: $LearningRate; epochs: $EffectiveEpochs" -ForegroundColor Cyan
            }
        }
    } catch {
        Write-Host "Could not resolve active model training checkpoint; falling back to official pretrain: $($_.Exception.Message)" -ForegroundColor Yellow
        $ParentModelId = ""
        $TrainingMode = "fresh"
        $LearningRate = 0.0001
    }
}

# RT-DETR-L CPU training is a portability fallback, not the fast path. Keep the
# optimizer conservative and use one image per batch; this substantially reduces
# CPU-side numerical spikes in the DINO/Hungarian matcher while preserving the
# same model family and dataset semantics.
if ($Device -eq "cpu") {
    $LearningRate = [Math]::Min([double]$LearningRate, 0.00003)
    Write-Host "CPU-safe RT-DETR settings: batch size 1; learning rate $LearningRate." -ForegroundColor Yellow
}

$RunId = "table-run-{0}-RTDETR-L" -f (Get-Date -Format "yyyyMMddTHHmmss")
$HostRun = Join-Path $HostWorkspace ("table_cell_runs\{0}" -f $RunId)
$ContainerRun = "$ContainerWorkspace/table_cell_runs/$RunId"
New-Item -ItemType Directory -Force -Path $HostRun | Out-Null
$Service = if ($Device -eq "gpu") { "trainer-gpu-detection" } else { "trainer-cpu" }
$Profile = if ($Device -eq "gpu") { "training-gpu-detection" } else { "training" }

$TrainArgs = @(
    "/opt/isala-training/table_cell_runner.py", "train",
    "--dataset", $ContainerDataset, "--output", $ContainerRun,
    "--device", $Device, "--pretrain", $TrainingPretrain,
    "--learning-rate", [string]$LearningRate, "--training-mode", $TrainingMode
)
if ($Device -eq "cpu") { $TrainArgs += @("--batch-size", "1") }
if (-not [string]::IsNullOrWhiteSpace($ParentModelId)) { $TrainArgs += @("--parent-model-id", $ParentModelId) }
if ($EffectiveEpochs -gt 0) { $TrainArgs += @("--epochs", [string]$EffectiveEpochs) }
Write-Host "Fine-tuning RT-DETR-L wireless table-cell detector on reviewed cell geometry + Step-7 hard examples..." -ForegroundColor Cyan
docker compose --profile $Profile run --rm --pull never --entrypoint python3 $Service $TrainArgs
if ($LASTEXITCODE -ne 0) {
    $log = Join-Path $HostRun "paddlex_train.log"
    if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log -Tail 80 | ForEach-Object { Write-Host $_ } }
    if ($Device -eq "cpu" -and (Test-Path -LiteralPath $log -PathType Leaf)) {
        $logText = [string](Get-Content -LiteralPath $log -Raw -ErrorAction SilentlyContinue)
        if ($logText -match 'matrix contains invalid numeric entries') {
            throw "CPU RT-DETR matcher produced non-finite costs even with CPU-safe settings. Dataset sanity passed; use GPU when available or inspect this run's paddlex_train.log for a Paddle CPU numerical issue."
        }
    }
    throw "Table-cell detector training failed."
}

$MetadataPath = Join-Path $HostRun "table_cell_run.json"
if (-not (Test-Path -LiteralPath $MetadataPath -PathType Leaf)) { throw "Training completed without table_cell_run.json." }
$Metadata = Get-Content -LiteralPath $MetadataPath -Raw | ConvertFrom-Json
$InferenceDir = [string]$Metadata.inference_dir
if ([string]::IsNullOrWhiteSpace($InferenceDir)) { throw "Training metadata has no inference_dir." }
$Predictions = "$ContainerRun/predictions.json"
Write-Host "Evaluating the new detector on the fixed validation split..." -ForegroundColor Cyan
docker compose --profile $Profile run --rm --pull never --entrypoint python3 $Service `
    /opt/isala-training/table_cell_runner.py predict --model-dir $InferenceDir `
    --input "$ContainerDataset/images" --output $Predictions --device $Device --threshold 0.01
if ($LASTEXITCODE -ne 0) { throw "Table-cell validation prediction failed." }

$ContainerEval = "$ContainerRun/validation_evaluation.json"
docker compose --profile training run --rm --build training-collector `
    evaluate-table-cell-predictions --workspace $ContainerWorkspace --config /app/config/app.yaml `
    --predictions $Predictions --dataset-id $DatasetId --split val --minimum-confidence 0.25 --iou-threshold 0.50 --output $ContainerEval
if ($LASTEXITCODE -ne 0) { throw "Table-cell validation evaluation failed." }

$ModelId = "table-RTDETR-L-$RunId"
Write-Host "Registering trained table-cell model (activation stays explicit)..." -ForegroundColor Cyan
docker compose --profile training run --rm --build training-collector `
    register-table-cell-model --workspace $ContainerWorkspace --config /app/config/app.yaml `
    --model-id $ModelId --run-id $RunId --dataset-id $DatasetId --model-dir $InferenceDir --device $Device --evaluation $ContainerEval
if ($LASTEXITCODE -ne 0) { throw "Table-cell model registration failed." }
Set-Content -LiteralPath (Join-Path (Split-Path $HostRun -Parent) "latest.txt") -Value $RunId -NoNewline -Encoding ASCII
Write-Host "Table-cell model trained and registered: $ModelId" -ForegroundColor Green
Write-Host "Next: review validation metrics, activate the model, then rerun Step 3 to measure whether direct Paddle coverage improves." -ForegroundColor Cyan
