param(
    [Alias("Input")]
    [ValidateNotNullOrEmpty()]
    [string]$InputPath = "",

    [ValidateNotNullOrEmpty()]
    [string]$Model = "auto",

    [string]$TableModelId = "",

    [string]$SourceId = "",

    [switch]$RenderOnly,

    [ValidateSet("auto", "cpu", "gpu")]
    [string]$Device = "auto"
)

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $ProjectRoot
try {
    . (Join-Path $PSScriptRoot "training-common.ps1")
    . (Join-Path $PSScriptRoot "table-execution-device.ps1")
    $ContainerWorkspace = Get-IsalaContainerWorkspace
    $HostWorkspace = Get-IsalaHostProjectWorkspace
    if ([string]::IsNullOrWhiteSpace($InputPath)) {
        $InputPath = Get-IsalaContainerProjectInput
        New-Item -ItemType Directory -Path (Get-IsalaHostProjectInput) -Force | Out-Null
    }
    Assert-IsalaActionPreflight -ActionId "2"
    Assert-Docker

$deviceResolution = Resolve-IsalaTableExecutionDevice -Requested $Device -PrepareGpuRuntime:($Device -in @("auto", "gpu"))
    $ResolvedDevice = [string]$deviceResolution.Device
    Write-Host ("Table inference backend: {0} ({1})" -f $ResolvedDevice.ToUpperInvariant(), [string]$deviceResolution.Reason) -ForegroundColor Cyan

    & (Join-Path $PSScriptRoot "safe-housekeeping.ps1") -ProjectRoot $ProjectRoot

    if ([string]::IsNullOrWhiteSpace($InputPath)) {
        throw "InputPath cannot be empty. Use /input or /input/test-dicoms."
    }

    $normalizedInput = ($InputPath -replace '\\', '/').TrimEnd('/')
    if ($normalizedInput -eq '') {
        $normalizedInput = '/input'
    }
    if ($normalizedInput -ne '/input' -and -not $normalizedInput.StartsWith('/input/')) {
        throw "InputPath '$InputPath' is outside the mounted /input directory."
    }

    $relativeInput = $normalizedInput.Substring('/input'.Length).TrimStart('/')
    $hostInputPath = Join-Path $ProjectRoot 'input'
    if ($relativeInput) {
        $hostInputPath = Join-Path $hostInputPath ($relativeInput -replace '/', [IO.Path]::DirectorySeparatorChar)
    }

    if (-not (Test-Path -LiteralPath $hostInputPath)) {
        throw "Host input path does not exist: $hostInputPath"
    }

    $ignoredExtensions = @('.ini', '.yaml', '.yml', '.json', '.txt', '.log')
    $inputFiles = @(
        Get-ChildItem -LiteralPath $hostInputPath -Recurse -File -Force | Where-Object {
            $ignoredExtensions -notcontains $_.Extension.ToLowerInvariant()
        }
    )

    if ($inputFiles.Count -eq 0) {
        $parent = Split-Path $ProjectRoot -Parent
        $candidateLines = @()
        foreach ($candidate in @(Get-ChildItem -LiteralPath $parent -Directory -Filter 'IsalaOCR_docker*' -ErrorAction SilentlyContinue)) {
            if ($candidate.FullName -eq $ProjectRoot) { continue }
            $candidateInput = Join-Path $candidate.FullName 'input'
            if (-not (Test-Path -LiteralPath $candidateInput)) { continue }
            $candidateFiles = @(Get-ChildItem -LiteralPath $candidateInput -Recurse -File -Force -ErrorAction SilentlyContinue)
            if ($candidateFiles.Count -gt 0) {
                $candidateLines += "  - $candidateInput ($($candidateFiles.Count) files)"
            }
        }

        $message = @(
            "No processable input files were found.",
            "Project root: $ProjectRoot",
            "Expected host path: $hostInputPath",
            "Container path: $normalizedInput"
        )
        if ($candidateLines.Count -gt 0) {
            $message += "Other IsalaOCR input folders containing files:"
            $message += $candidateLines
            $message += "Copy the DICOM test files into '$hostInputPath' and run option 2 again."
        } else {
            $message += "Place the DICOM files under '$hostInputPath' and run option 2 again."
        }
        throw ($message -join [Environment]::NewLine)
    }

    Write-Host "Host input path: $hostInputPath"
    Write-Host "Processable input files found: $($inputFiles.Count)"
    if ($RenderOnly) {
        Write-Host "Creating full source renders only in: $normalizedInput"
        Write-Host "Render-only mode does not run OCR, PP-Structure, cell detection or mapping."
    } else {
        Write-Host "Detecting PP-Structure table regions and cell geometry in: $normalizedInput"
        Write-Host "Table-first mode does not mix loose OCR text boxes or the active PicoDet/field detector into this pass."
        Write-Host "Pipeline A does not persist OCR values, field mappings or measurement output."
    }

    New-Item -ItemType Directory -Force -Path training\workspace, training\registry | Out-Null

    $collectArguments = @(
        "collect-training",
        "--input", $normalizedInput,
        "--workspace", $ContainerWorkspace,
        "--config", "/app/config/app.yaml",
        "--device", $ResolvedDevice
    )
    if (-not [string]::IsNullOrWhiteSpace($Model) -and $Model -ne "auto") {
        $collectArguments += @("--model", $Model)
    }
    if (-not [string]::IsNullOrWhiteSpace($TableModelId)) {
        $collectArguments += @("--table-model-id", $TableModelId)
    }
    if (-not [string]::IsNullOrWhiteSpace($SourceId)) {
        $collectArguments += @("--source-id", $SourceId)
    }
    if ($RenderOnly) {
        $collectArguments += "--render-only"
    }

    if ($ResolvedDevice -eq "gpu") {
        # Reuse the already prepared CUDA/PaddleDetection image and add only the
        # small IsalaOCR runtime layer. Docker's build cache keeps subsequent
        # inference rounds cheap while avoiding a second heavyweight GPU stack.
        $baseImage = Get-TrainingImageName -Device "gpu-detection"
        if (-not (Test-TrainingImagePrepared -Device "gpu-detection")) {
            throw "GPU inference selected, but the GPU detection runtime is not prepared."
        }
        $appVersion = ([string](Get-Content -LiteralPath (Join-Path $ProjectRoot "project\VERSION") -Raw)).Trim()
        $inferenceImage = "isalaocr-table-inference-gpu:$appVersion"
        $sourceFingerprintInput = @(
            Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "application\src") -Recurse -File |
                Sort-Object FullName |
                ForEach-Object { "{0}|{1}" -f $_.FullName, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
        ) -join "`n"
        $sourceHasher = [Security.Cryptography.SHA256]::Create()
        try {
            $sourceFingerprint = ([BitConverter]::ToString($sourceHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($sourceFingerprintInput))) -replace '-', '').ToLowerInvariant()
        }
        finally { $sourceHasher.Dispose() }
        Write-Host "Preparing cached GPU inference layer: $inferenceImage" -ForegroundColor Cyan
        & docker build `
            --file (Join-Path $ProjectRoot "infrastructure\docker\Dockerfile.table-inference") `
            --build-arg ("BASE_IMAGE={0}" -f $baseImage) `
            --build-arg ("APP_SOURCE_FINGERPRINT={0}" -f $sourceFingerprint) `
            --tag $inferenceImage `
            $ProjectRoot
        if ($LASTEXITCODE -ne 0) { throw "[ISALA_TABLE_RUNTIME_BROKEN] GPU table-inference image build failed." }

        # The generic Auto probe only proves that Paddle can see CUDA in the
        # heavyweight training image. Verify the actual inference image as well,
        # including the NumPy/pandas ABI and PaddleX/PaddleOCR imports. Keep the
        # Python one-liner whitespace-free for Windows PowerShell 5.1 argument
        # handling (see table-execution-device.ps1).
        $tableSmokeCode = "n=__import__('numpy');pd=__import__('pandas');p=__import__('paddle');__import__('paddlex');__import__('paddleocr');assert(n.__version__=='1.26.4');assert(p.is_compiled_with_cuda());assert(p.device.cuda.device_count()>0);p.device.set_device('gpu:0');print('ISALA_TABLE_GPU_OK:'+n.__version__+':'+pd.__version__)"
        $tableProbe = Invoke-DockerWithTimeout -Arguments @(
            "run", "--rm", "--gpus", "all", "--network", "none",
            "--entrypoint", "python3", $inferenceImage, "-c", $tableSmokeCode
        ) -TimeoutSeconds 60
        $tableProbeOutput = Get-IsalaProcessOutputText -Result $tableProbe -Fallback ""
        if ($tableProbe.TimedOut -or $tableProbe.ExitCode -ne 0 -or $tableProbeOutput -notmatch 'ISALA_TABLE_GPU_OK:') {
            $tableProbeReason = if ($tableProbe.TimedOut) {
                "GPU table-inference runtime probe liep in een timeout"
            } elseif ($tableProbeOutput) {
                $tableProbeOutput
            } else {
                "GPU table-inference runtime probe faalde zonder uitvoer"
            }
            throw "[ISALA_TABLE_RUNTIME_BROKEN] GPU table-inference dependency/CUDA smoke-test failed: $tableProbeReason"
        }
        Write-Host ("GPU table-inference runtime OK ({0})" -f (($tableProbeOutput -split '[\r\n]') | Where-Object { $_ -match 'ISALA_TABLE_GPU_OK:' } | Select-Object -First 1)) -ForegroundColor Green

        $projectId = Get-IsalaActiveProjectId
        $dockerArguments = @(
            "run", "--rm", "--gpus", "all", "--network", "none", "--read-only",
            "--tmpfs", "/tmp:size=2g,mode=1777", "--pids-limit", "256",
            "-e", "ISALA_PROJECT_ID=$projectId",
            "-e", "PADDLE_PDX_CACHE_HOME=/models/paddlex",
            "-e", "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True",
            "-v", ((Join-Path $ProjectRoot "input") + ":/input:ro"),
            "-v", ((Join-Path $ProjectRoot "models") + ":/models"),
            "-v", ((Join-Path $ProjectRoot "training") + ":/training"),
            $inferenceImage
        ) + $collectArguments
        & docker @dockerArguments
    }
    else {
        $dockerArguments = @(
            "compose", "--profile", "training", "run", "--rm", "--build",
            "training-collector"
        ) + $collectArguments
        & docker @dockerArguments
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Table/cell geometry detection completed with errors on $ResolvedDevice. Review the console output."
    }

    # v3.11 table-first experiment: the collector writes its effective strategy
    # into localization_manifest.json. Only legacy/fusion mode may merge an active
    # loose field detector. Table-first must remain a clean PP-Structure measurement.
    $manifestPath = Join-Path $HostWorkspace "localization_manifest.json"
    $strategy = "fusion"
    if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
        try {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
            if (-not [string]::IsNullOrWhiteSpace([string]$manifest.strategy)) { $strategy = [string]$manifest.strategy }
        } catch {
            Write-Warning "Could not read localization strategy from $manifestPath; keeping detector fallback disabled for safety."
            $strategy = "table_first"
        }
    }

    if ($strategy -eq "table_first") {
        Write-Host ("Table-first pass complete on {0}. Active field detector intentionally NOT merged." -f $ResolvedDevice.ToUpperInvariant()) -ForegroundColor Green
    } else {
        $activeModelFile = Join-Path $HostWorkspace "localization_models\active.json"
        if (Test-Path -LiteralPath $activeModelFile -PathType Leaf) {
            $active = Get-Content -LiteralPath $activeModelFile -Raw | ConvertFrom-Json
            $activeModelId = [string]$active.model_id
            $activeModelPath = [string]$active.path
            $device = if ([string]$active.device -eq "gpu") { "gpu" } else { "cpu" }
            $service = if ($device -eq "gpu") { "trainer-gpu" } else { "trainer-cpu" }
            $profile = if ($device -eq "gpu") { "training-gpu" } else { "training" }
            $stamp = Get-Date -Format "yyyyMMddTHHmmss"
            $predictions = "$ContainerWorkspace/localization_predictions/action2-$stamp.json"
            Write-Host "Active field detector found: $($active.model_id). Adding its geometry candidates..."
            & docker compose --profile $profile run --rm --pull never --entrypoint python3 $service `
                /opt/isala-training/localization_runner.py predict `
                --model-dir $activeModelPath --input $ContainerWorkspace/source_renders `
                --output $predictions --device $device --threshold 0.25
            if ($LASTEXITCODE -ne 0) { throw "Active field-detector prediction failed." }
            & docker compose --profile training run --rm --build training-collector `
                merge-localization-predictions --workspace $ContainerWorkspace --config /app/config/app.yaml `
                --predictions $predictions --model-id $activeModelId
            if ($LASTEXITCODE -ne 0) { throw "Candidate fusion with the active field detector failed." }
        }
    }
}
finally {
    Pop-Location
}
