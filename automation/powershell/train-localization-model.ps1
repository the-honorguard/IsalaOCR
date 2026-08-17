param(
    [ValidateSet("cpu","gpu")][string]$Device = "gpu",
    [int]$Epochs = 0
)
. (Join-Path $PSScriptRoot "training-common.ps1")
$ContainerWorkspace = Get-IsalaContainerWorkspace
$HostWorkspace = Get-IsalaHostProjectWorkspace
$ActionId = if ($Device -eq "gpu") { "7" } else { "8" }
Assert-IsalaActionPreflight -ActionId $ActionId
Assert-Docker
Assert-TrainingImagePrepared -Device $(if ($Device -eq "gpu") { "gpu-detection" } else { "cpu" }) | Out-Null
$PicoDetPretrain = Join-Path $ProjectRoot "models\training\PicoDet-S_pretrained.pdparams"
if (-not (Test-Path -LiteralPath $PicoDetPretrain -PathType Leaf) -or (Get-Item -LiteralPath $PicoDetPretrain).Length -le 1MB) {
    Write-Host "PicoDet-S training pretrain weight is missing; preparing the lightweight download helper..." -ForegroundColor Cyan
    & docker compose --profile setup build model-prep
    if ($LASTEXITCODE -ne 0) { throw "Model-prep helper image could not be built for the PicoDet-S weight download." }
    Write-Host "Downloading the official PicoDet-S training weight before the offline train container starts..." -ForegroundColor Cyan
    & docker compose --profile setup run --rm --pull never --entrypoint python model-prep `
        /opt/isala-training/paddlex_runner.py download-pretrain --model PicoDet-S --pretrain-root /models/training
    if ($LASTEXITCODE -ne 0) { throw "PicoDet-S pretrained-weight download failed. Open Stap 1 - Voorbereiding and run the detector download phase." }
}
Write-Host ("PicoDet-S training pretrain ready: {0:N1} MiB" -f ((Get-Item -LiteralPath $PicoDetPretrain).Length / 1MB)) -ForegroundColor Green
$Pointer = Join-Path $HostWorkspace "localization_datasets\latest.txt"
if (-not (Test-Path -LiteralPath $Pointer -PathType Leaf)) { throw "No localization dataset exists. Open de geparkeerde fallbackpagina Losse box-detector trainen en bouw daar eerst de localization-dataset." }
$DatasetId = (Get-Content -LiteralPath $Pointer -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($DatasetId)) { throw "Localization dataset pointer is empty." }
$RunId = "loc-run-{0}-PicoDet-S" -f (Get-Date -Format "yyyyMMddTHHmmss")
$HostRun = Join-Path $HostWorkspace ("localization_runs\{0}" -f $RunId)
New-Item -ItemType Directory -Force -Path $HostRun | Out-Null
$Service = if ($Device -eq "gpu") { "trainer-gpu-detection" } else { "trainer-cpu" }
$Profile = if ($Device -eq "gpu") { "training-gpu-detection" } else { "training" }
$ContainerDataset = "$ContainerWorkspace/localization_datasets/$DatasetId"
$ContainerRun = "$ContainerWorkspace/localization_runs/$RunId"
$ContainerSanity = "$ContainerRun/sanity"
Write-Host "Running small-dataset sanity-overfit check before the full detector training..." -ForegroundColor Cyan
docker compose --profile $Profile run --rm --pull never --entrypoint python3 $Service `
    /opt/isala-training/localization_runner.py sanity-check `
    --dataset $ContainerDataset --output $ContainerSanity --device $Device
if ($LASTEXITCODE -ne 0) {
    $SanityResult = Join-Path $HostRun "sanity\sanity_check.json"
    throw "Field-detector sanity check failed. Full training was not started. See $SanityResult and the terminal log."
}
Write-Host "Sanity check passed (or was not required for a larger dataset). Starting full training..." -ForegroundColor Green
$TrainArgs = @(
    "/opt/isala-training/localization_runner.py", "train",
    "--dataset", $ContainerDataset, "--output", $ContainerRun, "--device", $Device
)
if ($Epochs -gt 0) { $TrainArgs += @("--epochs", [string]$Epochs) }
Write-Host "Training field-localization detector $RunId on $Device..."
docker compose --profile $Profile run --rm --pull never --entrypoint python3 $Service $TrainArgs
if ($LASTEXITCODE -ne 0) {
    $PaddleLog = Join-Path $HostRun "paddlex_train.log"
    if (Test-Path -LiteralPath $PaddleLog -PathType Leaf) {
        Write-Host "--- PaddleX training error tail ---" -ForegroundColor Yellow
        Get-Content -LiteralPath $PaddleLog -Tail 80 | ForEach-Object { Write-Host $_ }
        Write-Host "--- End PaddleX training error tail ---" -ForegroundColor Yellow
    }
    throw "Field-detector training failed. Full PaddleX log retained under $PaddleLog"
}
$RunMetadata = Join-Path $HostRun "isala_localization_run.json"
if (-not (Test-Path -LiteralPath $RunMetadata -PathType Leaf)) { throw "Training completed without run metadata: $RunMetadata" }
$Metadata = Get-Content -LiteralPath $RunMetadata -Raw | ConvertFrom-Json
$InferenceDir = [string]$Metadata.inference_dir
if ([string]::IsNullOrWhiteSpace($InferenceDir)) { throw "Training metadata has no inference_dir." }
$ModelId = "field-PicoDet-S-$RunId"
$Predictions = "$ContainerRun/predictions.json"
Write-Host "Running trained detector over reviewed source renders for independent geometry evaluation..."
docker compose --profile $Profile run --rm --pull never --entrypoint python3 $Service `
    /opt/isala-training/localization_runner.py predict `
    --model-dir $InferenceDir --input $ContainerWorkspace/source_renders --output $Predictions --device $Device --threshold 0.01
if ($LASTEXITCODE -ne 0) { throw "Field-detector prediction run failed." }
Write-Host "Running post-training sanity checks and confidence calibration on TRAIN/VALIDATION..."
docker compose --profile training run --rm --build training-collector `
    diagnose-localization-predictions --workspace $ContainerWorkspace --config /app/config/app.yaml `
    --predictions $Predictions --model-id $ModelId --dataset-id $DatasetId `
    --splits train,val `
    --thresholds 0.01,0.05,0.10,0.15,0.20,0.25,0.35,0.50,0.60,0.70,0.80,0.90,0.95
if ($LASTEXITCODE -ne 0) { throw "Field-detector diagnostic evaluation failed to execute." }

$DiagnosticPath = Join-Path $HostWorkspace "localization_diagnostics\latest_trained.json"
if (-not (Test-Path -LiteralPath $DiagnosticPath -PathType Leaf)) { throw "Diagnostic result was not written: $DiagnosticPath" }
$Diagnostic = Get-Content -LiteralPath $DiagnosticPath -Raw | ConvertFrom-Json
$DiagnosticThreshold = 0.25
if ($null -ne $Diagnostic.recommended_threshold) { $DiagnosticThreshold = [double]$Diagnostic.recommended_threshold }
Write-Host ("Persisting the validation evaluation at diagnostic confidence {0:N2}..." -f $DiagnosticThreshold)
docker compose --profile training run --rm --build training-collector `
    evaluate-localization-predictions --workspace $ContainerWorkspace --config /app/config/app.yaml `
    --predictions $Predictions --model-id $ModelId --dataset-id $DatasetId --split val --minimum-confidence $DiagnosticThreshold
if ($LASTEXITCODE -ne 0) { throw "Field-detector validation evaluation failed to execute." }

if ($null -eq $Diagnostic.production_threshold) {
    Write-Host "Validation does not yet produce a production-confidence. The hold-out TEST split is intentionally not used during training iteration." -ForegroundColor Yellow
} else {
    Write-Host ("Validation found production-confidence {0:N2}. Open de geparkeerde fallbackpagina Box-detector evalueren om de finale hold-out test uit te voeren zonder de threshold opnieuw te tunen." -f [double]$Diagnostic.production_threshold) -ForegroundColor Green
}
Write-Host "Registering trained detector (activation remains a separate quality-gated action)..."
docker compose --profile training run --rm --build training-collector `
    register-localization-model --workspace $ContainerWorkspace --config /app/config/app.yaml `
    --model-id $ModelId --model-name PicoDet-S --model-dir $InferenceDir --device $Device
if ($LASTEXITCODE -ne 0) { throw "Field-detector registration failed." }
Set-Content -LiteralPath (Join-Path (Split-Path $HostRun -Parent) "latest.txt") -Value $RunId -NoNewline -Encoding ASCII
@{ run_id=$RunId; model_id=$ModelId; dataset_id=$DatasetId; inference_dir=$InferenceDir; device=$Device } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $HostRun "isala_model_registration.json") -Encoding UTF8
Write-Host "Field detector trained and evaluated: $ModelId"
