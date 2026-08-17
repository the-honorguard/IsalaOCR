param(
    [Alias("Input")]
    [ValidateNotNullOrEmpty()]
    [string]$InputPath = "",

    [ValidateNotNullOrEmpty()]
    [string]$Model = "auto",

    [string]$TableModelId = ""
)

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $ProjectRoot
try {
    . (Join-Path $PSScriptRoot "training-common.ps1")
$ContainerWorkspace = Get-IsalaContainerWorkspace
$HostWorkspace = Get-IsalaHostProjectWorkspace
if ([string]::IsNullOrWhiteSpace($InputPath)) {
    $InputPath = Get-IsalaContainerProjectInput
    New-Item -ItemType Directory -Path (Get-IsalaHostProjectInput) -Force | Out-Null
}
Assert-IsalaActionPreflight -ActionId "2"
    Assert-Docker

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
    Write-Host "Detecting PP-Structure table regions and cell geometry in: $normalizedInput"
    Write-Host "Table-first mode does not mix loose OCR text boxes or the active PicoDet/field detector into this pass."
    Write-Host "Pipeline A does not persist OCR values, field mappings or measurement output."

    New-Item -ItemType Directory -Force -Path training\workspace, training\registry | Out-Null

    $dockerArguments = @(
        "compose",
        "--profile", "training",
        "run", "--rm", "--build",
        "training-collector",
        "collect-training",
        "--input", $normalizedInput,
        "--workspace", $ContainerWorkspace,
        "--config", "/app/config/app.yaml"
    )
    if (-not [string]::IsNullOrWhiteSpace($Model) -and $Model -ne "auto") {
        $dockerArguments += @("--model", $Model)
    }
    if (-not [string]::IsNullOrWhiteSpace($TableModelId)) {
        $dockerArguments += @("--table-model-id", $TableModelId)
    }

    & docker @dockerArguments

    if ($LASTEXITCODE -ne 0) {
        throw "Table/cell geometry detection completed with errors. Review the console output."
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
        Write-Host "Table-first pass complete. Active field detector intentionally NOT merged." -ForegroundColor Green
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
