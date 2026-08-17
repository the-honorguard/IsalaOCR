param(
    [ValidateSet("all","inference","cpu-detection","gpu-recognition","gpu-detection","pretrained")]
    [string]$Component = "all",
    [ValidateSet("full","download","install","check")]
    [string]$Phase = "full",
    [string]$PreflightActionId = "1"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-IsalaActionPreflight -ActionId $PreflightActionId
Assert-Docker
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$CheckRoot = Join-Path $ProjectRoot "models\preparation_checks"
New-Item -ItemType Directory -Force -Path $CheckRoot | Out-Null

$CpuBaseImage = if (-not [string]::IsNullOrWhiteSpace($env:PADDLEX_CPU_IMAGE)) { $env:PADDLEX_CPU_IMAGE } else { "ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlex/paddlex:paddlex3.3.11-paddlepaddle3.2.0-cpu" }
$GpuBaseImage = if (-not [string]::IsNullOrWhiteSpace($env:PADDLEX_GPU_IMAGE)) { $env:PADDLEX_GPU_IMAGE } else { "ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlex/paddlex:paddlex3.3.11-paddlepaddle3.2.0-gpu-cuda11.8-cudnn8.9-trt8.6" }

function Update-PreparationStatusSnapshot {
    try { & (Join-Path $PSScriptRoot "preparation-status.ps1") }
    catch { Write-Warning ("Preparation status refresh failed: {0}" -f $_.Exception.Message) }
}

function Assert-DockerImage {
    param(
        [Parameter(Mandatory=$true)][string]$Image,
        [string]$Hint="",
        [int]$RetryCount=1
    )
    $state = Get-DockerImageState -Image $Image -RetryCount $RetryCount -RetryDelayMilliseconds 500
    if (-not $state.Present) {
        $diagnostic = [string]$state.Detail
        if ([string]::IsNullOrWhiteSpace($diagnostic)) { $diagnostic = "Docker image inspect returned no usable image ID." }
        throw "Required Docker image is missing: $Image`n$diagnostic`n$Hint"
    }
    return [string]$state.Id
}

function Write-CheckMarker {
    param([Parameter(Mandatory=$true)][string]$Name,[hashtable]$Data=@{})
    $payload = [ordered]@{ component=$Name; validated_at=(Get-Date).ToString("o") }
    foreach ($key in $Data.Keys) { $payload[$key] = $Data[$key] }
    $path = Join-Path $CheckRoot ($Name + ".json")
    [System.IO.File]::WriteAllText($path,($payload|ConvertTo-Json -Depth 6),[System.Text.UTF8Encoding]::new($false))
}

function Clear-CheckMarker {
    param([Parameter(Mandatory=$true)][string]$Name)
    Remove-Item (Join-Path $CheckRoot ($Name + ".json")) -Force -ErrorAction SilentlyContinue
}

function Ensure-ModelPrepImage {
    & docker compose --profile setup build model-prep
    if ($LASTEXITCODE -ne 0) { throw "The model-prep helper image could not be built." }
}

function Download-Inference {
    Write-Host "Downloading/warming inference OCR and table model files..." -ForegroundColor Cyan
    Ensure-ModelPrepImage
    & docker compose --profile setup run --rm --pull never model-prep
    if ($LASTEXITCODE -ne 0) { throw "Inference/table model download failed." }
}

function Download-CpuDetection {
    Write-Host "Pulling CPU PaddleX base image..." -ForegroundColor Cyan
    & docker pull $CpuBaseImage
    if ($LASTEXITCODE -ne 0) { throw "CPU PaddleX base-image download failed." }
    Download-PicoDetPretrained
}

function Download-GpuBase {
    Write-Host "Pulling shared NVIDIA PaddleX base image..." -ForegroundColor Cyan
    & docker pull $GpuBaseImage
    if ($LASTEXITCODE -ne 0) { throw "GPU PaddleX base-image download failed." }
    if ($Component -eq "gpu-detection") { Download-PicoDetPretrained }
}

function Download-PicoDetPretrained {
    $weight = Join-Path $ProjectRoot "models\training\PicoDet-S_pretrained.pdparams"
    if ((Test-Path -LiteralPath $weight -PathType Leaf) -and (Get-Item -LiteralPath $weight).Length -gt 1MB) {
        Write-Host "PicoDet-S training weight already downloaded: $weight" -ForegroundColor Green
        return
    }
    Ensure-ModelPrepImage
    Write-Host "Downloading official PicoDet-S training pretrain weight..." -ForegroundColor Cyan
    & docker compose --profile setup run --rm --pull never --entrypoint python model-prep `
        /opt/isala-training/paddlex_runner.py probe-pretrain --model PicoDet-S --timeout 30
    if ($LASTEXITCODE -ne 0) { throw "PicoDet-S pretrained-weight source is not reachable from Docker." }
    & docker compose --profile setup run --rm --pull never --entrypoint python model-prep `
        /opt/isala-training/paddlex_runner.py download-pretrain --model PicoDet-S --pretrain-root /models/training
    if ($LASTEXITCODE -ne 0) { throw "PicoDet-S pretrained-weight download failed." }
}

function Download-Pretrained {
    $weight = Join-Path $ProjectRoot "models\training\PP-OCRv6_medium_rec_pretrained.pdparams"
    if ((Test-Path -LiteralPath $weight -PathType Leaf) -and (Get-Item -LiteralPath $weight).Length -gt 1MB) {
        Write-Host "Pretrained weight already downloaded: $weight" -ForegroundColor Green
        return
    }
    Ensure-ModelPrepImage
    & docker compose --profile setup run --rm --pull never --entrypoint python model-prep `
        /opt/isala-training/paddlex_runner.py probe-pretrain --model PP-OCRv6_medium_rec --timeout 30
    if ($LASTEXITCODE -ne 0) { throw "Pretrained-weight source is not reachable from Docker." }
    & docker compose --profile setup run --rm --pull never --entrypoint python model-prep `
        /opt/isala-training/paddlex_runner.py download-pretrain --model PP-OCRv6_medium_rec --pretrain-root /models/training
    if ($LASTEXITCODE -ne 0) { throw "Pretrained-weight download failed." }
}

function Invoke-AllDownloadsParallel {
    Write-Host "Preparing helper image before parallel downloads..." -ForegroundColor Cyan
    Ensure-ModelPrepImage
    $jobs = @()
    $jobs += Start-Job -Name "inference-models" -ArgumentList $ProjectRoot -ScriptBlock {
        param($root); Set-Location $root
        & docker compose --profile setup run --rm --pull never model-prep
        if ($LASTEXITCODE -ne 0) { throw "Inference/table model download failed." }
    }
    $jobs += Start-Job -Name "pretrained-weight" -ArgumentList $ProjectRoot -ScriptBlock {
        param($root); Set-Location $root
        $weight=Join-Path $root "models\training\PP-OCRv6_medium_rec_pretrained.pdparams"
        if ((Test-Path -LiteralPath $weight -PathType Leaf) -and (Get-Item -LiteralPath $weight).Length -gt 1MB) { return }
        & docker compose --profile setup run --rm --pull never --entrypoint python model-prep /opt/isala-training/paddlex_runner.py probe-pretrain --model PP-OCRv6_medium_rec --timeout 30
        if ($LASTEXITCODE -ne 0) { throw "Pretrained source probe failed." }
        & docker compose --profile setup run --rm --pull never --entrypoint python model-prep /opt/isala-training/paddlex_runner.py download-pretrain --model PP-OCRv6_medium_rec --pretrain-root /models/training
        if ($LASTEXITCODE -ne 0) { throw "Pretrained download failed." }
    }
    $jobs += Start-Job -Name "picodet-pretrained-weight" -ArgumentList $ProjectRoot -ScriptBlock {
        param($root); Set-Location $root
        $weight=Join-Path $root "models\training\PicoDet-S_pretrained.pdparams"
        if ((Test-Path -LiteralPath $weight -PathType Leaf) -and (Get-Item -LiteralPath $weight).Length -gt 1MB) { return }
        & docker compose --profile setup run --rm --pull never --entrypoint python model-prep /opt/isala-training/paddlex_runner.py probe-pretrain --model PicoDet-S --timeout 30
        if ($LASTEXITCODE -ne 0) { throw "PicoDet-S pretrained source probe failed." }
        & docker compose --profile setup run --rm --pull never --entrypoint python model-prep /opt/isala-training/paddlex_runner.py download-pretrain --model PicoDet-S --pretrain-root /models/training
        if ($LASTEXITCODE -ne 0) { throw "PicoDet-S pretrained download failed." }
    }
    $jobs += Start-Job -Name "cpu-base-image" -ArgumentList $CpuBaseImage -ScriptBlock {
        param($image); & docker pull $image; if ($LASTEXITCODE -ne 0) { throw "CPU base-image pull failed." }
    }
    $jobs += Start-Job -Name "gpu-base-image" -ArgumentList $GpuBaseImage -ScriptBlock {
        param($image); & docker pull $image; if ($LASTEXITCODE -ne 0) { throw "GPU base-image pull failed." }
    }
    $failed=@()
    while (@($jobs | Where-Object { $_.State -in @("NotStarted","Running") }).Count -gt 0) {
        foreach ($job in $jobs) {
            Receive-Job $job -ErrorAction Continue
        }
        Start-Sleep -Seconds 1
    }
    foreach ($job in $jobs) {
        Receive-Job $job -ErrorAction Continue
        if ($job.State -ne "Completed") { $failed += $job.Name }
        Remove-Job $job -Force -ErrorAction SilentlyContinue
    }
    if ($failed.Count -gt 0) { throw ("One or more parallel downloads failed: " + ($failed -join ", ")) }
    Write-Host "All independent download groups completed." -ForegroundColor Green
}

function Install-Inference {
    Clear-CheckMarker "inference"
    $manifest=Join-Path $ProjectRoot "models\paddlex\isala_ocr_model_manifest.json"
    if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw "Download the inference/table model files first." }
    Write-Host "Inference models are file-based; install prepares the local runtime image. The separate check proves offline use." -ForegroundColor Cyan
    Ensure-ModelPrepImage
}

function Check-Inference {
    Write-Host "Validating inference/table models with networking disabled..." -ForegroundColor Cyan
    & docker compose --profile setup run --rm --pull never model-prep-offline
    if ($LASTEXITCODE -ne 0) { throw "Offline inference/table model validation failed." }
    $manifest=Join-Path $ProjectRoot "models\paddlex\isala_ocr_model_manifest.json"
    if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw "Inference manifest is missing after validation." }
    Write-CheckMarker "inference" @{ manifest_last_write_utc=(Get-Item $manifest).LastWriteTimeUtc.ToString("o") }
}

function Install-CpuDetection {
    Clear-CheckMarker "cpu_detection"
    Assert-DockerImage -Image $CpuBaseImage -Hint "Run the CPU detector download step first." | Out-Null
    $image=Get-TrainingImageName -Device cpu
    Write-Host "Building CPU detector/PicoDet training image: $image" -ForegroundColor Cyan
    & docker compose --profile training-build build training-image-cpu
    if ($LASTEXITCODE -ne 0) { throw "CPU detector/PicoDet image build failed." }
    Assert-DockerImage -Image $image -RetryCount 4 | Out-Null
    Write-Host "Materializing the PicoDet-S model files during installation..." -ForegroundColor Cyan
    & docker compose --profile setup run --rm --pull never localization-model-prep
    if ($LASTEXITCODE -ne 0) { throw "PicoDet-S model installation failed." }
}

function Check-CpuDetection {
    $weight=Join-Path $ProjectRoot "models\training\PicoDet-S_pretrained.pdparams"
    if (-not (Test-Path -LiteralPath $weight -PathType Leaf) -or (Get-Item -LiteralPath $weight).Length -le 1MB) { throw "PicoDet-S training pretrain weight is missing. Run the CPU detector download phase first." }
    $image=Get-TrainingImageName -Device cpu
    $imageId=Assert-DockerImage -Image $image -Hint "Install/build the CPU detector image first."
    Write-Host "Validating CPU Paddle runtime..." -ForegroundColor Cyan
    & docker compose --profile training run --rm --pull never --entrypoint python3 trainer-cpu /opt/isala-training/paddlex_runner.py runtime-check --device cpu
    if ($LASTEXITCODE -ne 0) { throw "CPU training-image runtime validation failed." }
    Write-Host "Validating PicoDet-S localization model cache with networking disabled..." -ForegroundColor Cyan
    & docker compose --profile setup run --rm --pull never localization-model-check
    if ($LASTEXITCODE -ne 0) { throw "PicoDet-S localization runtime validation failed." }
    $manifest=Join-Path $ProjectRoot "models\paddlex\isala_localization_model_manifest.json"
    if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw "PicoDet-S localization manifest is missing." }
    Write-CheckMarker "cpu_detection" @{ image_id=$imageId; localization_manifest_last_write_utc=(Get-Item $manifest).LastWriteTimeUtc.ToString("o") }
}

function Install-GpuRecognition {
    Clear-CheckMarker "gpu_recognition"
    Assert-DockerImage -Image $GpuBaseImage -Hint "Run the GPU base download step first." | Out-Null
    $image=Get-TrainingImageName -Device gpu
    Write-Host "Building GPU OCR-recognition image: $image" -ForegroundColor Cyan
    & docker compose --profile training-build build training-image-gpu
    if ($LASTEXITCODE -ne 0) { throw "GPU OCR-recognition image build failed." }
    Assert-DockerImage -Image $image -RetryCount 4 | Out-Null
}

function Check-GpuRecognition {
    $image=Get-TrainingImageName -Device gpu
    $imageId=Assert-DockerImage -Image $image -Hint "Install/build the GPU OCR-recognition image first."
    Write-Host "Validating PaddlePaddle/CUDA in the started GPU recognition container..." -ForegroundColor Cyan
    & docker compose --profile training-gpu run --rm --pull never --entrypoint python3 trainer-gpu /opt/isala-training/paddlex_runner.py runtime-check --device gpu:0
    if ($LASTEXITCODE -ne 0) { throw "GPU OCR-recognition runtime validation failed." }
    Write-CheckMarker "gpu_recognition" @{ image_id=$imageId }
}

function Install-GpuDetection {
    Clear-CheckMarker "gpu_detection"
    Assert-DockerImage -Image $GpuBaseImage -Hint "Run the GPU base download step first." | Out-Null
    $image=Get-TrainingImageName -Device gpu-detection
    Write-Host "Building GPU PaddleDetection/PicoDet image: $image" -ForegroundColor Cyan
    & docker compose --profile training-build build training-image-gpu-detection
    if ($LASTEXITCODE -ne 0) { throw "GPU PaddleDetection/PicoDet image build failed." }
    Assert-DockerImage -Image $image -RetryCount 4 | Out-Null
}

# trainer-gpu-detection is defined with `gpus: all` in compose.yaml; CUDA validation
# belongs here at container runtime, never inside Docker BuildKit.
function Check-GpuDetection {
    $weight=Join-Path $ProjectRoot "models\training\PicoDet-S_pretrained.pdparams"
    if (-not (Test-Path -LiteralPath $weight -PathType Leaf) -or (Get-Item -LiteralPath $weight).Length -le 1MB) { throw "PicoDet-S training pretrain weight is missing. Run the GPU detector download phase first." }
    $image=Get-TrainingImageName -Device gpu-detection
    $imageId=Assert-DockerImage -Image $image -Hint "Install/build the GPU PaddleDetection image first."
    Write-Host "Validating PaddlePaddle, CUDA and PaddleDetection in a started GPU container..." -ForegroundColor Cyan
    & docker compose --profile training-gpu-detection run --rm --pull never --entrypoint python3 trainer-gpu-detection /opt/isala-training/paddlex_runner.py runtime-check --device gpu:0 --require-paddledet
    if ($LASTEXITCODE -ne 0) { throw "GPU PaddleDetection runtime validation failed." }
    Write-CheckMarker "gpu_detection" @{ image_id=$imageId }
}

function Install-Pretrained {
    Clear-CheckMarker "pretrained"
    $weight=Join-Path $ProjectRoot "models\training\PP-OCRv6_medium_rec_pretrained.pdparams"
    if (-not (Test-Path -LiteralPath $weight -PathType Leaf) -or (Get-Item -LiteralPath $weight).Length -le 1MB) { throw "Download the pretrained weight first." }
}

function Check-Pretrained {
    $weight=Join-Path $ProjectRoot "models\training\PP-OCRv6_medium_rec_pretrained.pdparams"
    if (-not (Test-Path -LiteralPath $weight -PathType Leaf) -or (Get-Item -LiteralPath $weight).Length -le 1MB) { throw "Pretrained weight is missing or incomplete." }
    $cpuImage=Get-TrainingImageName -Device cpu
    Assert-DockerImage -Image $cpuImage -Hint "The pretrained training check requires the CPU training image." | Out-Null
    Write-Host "Validating pretrained weight offline..." -ForegroundColor Cyan
    & docker compose --profile training-setup run --rm --pull never training-setup
    if ($LASTEXITCODE -ne 0) { throw "Offline pretrained-weight validation failed." }
    Write-CheckMarker "pretrained" @{ bytes=[long](Get-Item -LiteralPath $weight).Length; last_write_utc=(Get-Item -LiteralPath $weight).LastWriteTimeUtc.ToString("o") }
}

function Invoke-ComponentPhase {
    param([Parameter(Mandatory=$true)][string]$Name,[Parameter(Mandatory=$true)][string]$RequestedPhase)
    $download = switch ($Name) {
        "inference" { { Download-Inference } }
        "cpu-detection" { { Download-CpuDetection } }
        "gpu-recognition" { { Download-GpuBase } }
        "gpu-detection" { { Download-GpuBase } }
        "pretrained" { { Download-Pretrained } }
    }
    $install = switch ($Name) {
        "inference" { { Install-Inference } }
        "cpu-detection" { { Install-CpuDetection } }
        "gpu-recognition" { { Install-GpuRecognition } }
        "gpu-detection" { { Install-GpuDetection } }
        "pretrained" { { Install-Pretrained } }
    }
    $check = switch ($Name) {
        "inference" { { Check-Inference } }
        "cpu-detection" { { Check-CpuDetection } }
        "gpu-recognition" { { Check-GpuRecognition } }
        "gpu-detection" { { Check-GpuDetection } }
        "pretrained" { { Check-Pretrained } }
    }
    try {
        switch ($RequestedPhase) {
            "download" { & $download }
            "install" { & $install }
            "check" { & $check }
            "full" { & $download; & $install; & $check }
        }
    }
    finally {
        # Even a failed check changes what the UI must show. Never leave a stale
        # green preparation_status.json behind after a missing image/runtime error.
        Update-PreparationStatusSnapshot
    }
}

function Invoke-AllChecks {
    $failures = New-Object System.Collections.Generic.List[string]
    foreach($name in @("inference","cpu-detection","gpu-recognition","gpu-detection","pretrained")) {
        try {
            Invoke-ComponentPhase -Name $name -RequestedPhase "check"
        }
        catch {
            $message = $_.Exception.Message
            Write-Warning ("Preparation check failed for {0}: {1}" -f $name,$message)
            [void]$failures.Add(("{0}: {1}" -f $name,$message))
        }
    }
    Update-PreparationStatusSnapshot
    if ($failures.Count -gt 0) {
        throw ("One or more preparation checks failed:`n - " + ($failures -join "`n - "))
    }
}

Push-Location $ProjectRoot
try {
    New-Item -ItemType Directory -Force -Path models\training,models\paddlex,$CheckRoot | Out-Null
    if ($Component -eq "all") {
        if ($Phase -eq "download") {
            Invoke-AllDownloadsParallel
        }
        elseif ($Phase -eq "install") {
            foreach($name in @("inference","cpu-detection","gpu-recognition","gpu-detection","pretrained")) { Invoke-ComponentPhase -Name $name -RequestedPhase "install" }
        }
        elseif ($Phase -eq "check") {
            # Inventory every component instead of aborting on the first missing image.
            # This produces one complete, current preparation status for the UI.
            Invoke-AllChecks
        }
        else {
            Invoke-AllDownloadsParallel
            foreach($name in @("inference","cpu-detection","gpu-recognition","gpu-detection","pretrained")) {
                Invoke-ComponentPhase -Name $name -RequestedPhase "install"
                Invoke-ComponentPhase -Name $name -RequestedPhase "check"
            }
        }
    }
    else { Invoke-ComponentPhase -Name $Component -RequestedPhase $Phase }
    Write-Host ("Preparation {0}/{1} completed." -f $Component,$Phase) -ForegroundColor Green
}
finally { Pop-Location }
