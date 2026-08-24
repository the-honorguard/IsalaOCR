# Shared runtime-image readiness helpers.
# This file is dot-sourced after training-common.ps1 so $ProjectRoot and
# Get-DockerImageState are already available.

function Get-IsalaRuntimeImageName {
    $version = if (-not [string]::IsNullOrWhiteSpace([string]$env:ISALA_APP_IMAGE_VERSION)) {
        ([string]$env:ISALA_APP_IMAGE_VERSION).Trim()
    } else {
        "3.14.1"
    }
    if ($version -notmatch '^[0-9A-Za-z][0-9A-Za-z._-]*$') {
        throw "ISALA_APP_IMAGE_VERSION contains an invalid Docker tag: $version"
    }
    return "isalaocr-runtime:$version"
}

function Test-IsalaComputeRuntimeInput {
    param([Parameter(Mandatory = $true)][System.IO.FileInfo]$File)

    # Python bytecode is generated locally by imports/compile checks and is
    # never part of the compute runtime image. Counting it here makes a normal
    # WebUI restart or a local syntax check incorrectly mark the image stale.
    if ($File.Extension -in @('.pyc', '.pyo') -or
        $File.FullName -match '(?i)[\\/]__pycache__[\\/]') {
        return $false
    }

    # The WebUI is built and restarted independently through Dockerfile.labeler.
    # Changes in that presentation/control layer must never force a rebuild of
    # the heavy OCR/mapping runtime used by training-collector/dataset-builder.
    $uiOnlyDirectories = @(
        (Join-Path $ProjectRoot "application\src\isala_ocr\training\static"),
        (Join-Path $ProjectRoot "application\src\isala_ocr\training\templates")
    )
    foreach ($directory in $uiOnlyDirectories) {
        $prefix = [System.IO.Path]::GetFullPath($directory).TrimEnd('\') + '\'
        if ([System.IO.Path]::GetFullPath($File.FullName).StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $false
        }
    }

    $uiOnlyFiles = @(
        (Join-Path $ProjectRoot "application\src\isala_ocr\training\webui.py"),
        (Join-Path $ProjectRoot "application\src\isala_ocr\training\webui_server.py"),
        (Join-Path $ProjectRoot "application\src\isala_ocr\training\labeler.py"),
        (Join-Path $ProjectRoot "application\src\isala_ocr\training\labeler_server.py"),
        (Join-Path $ProjectRoot "application\src\isala_ocr\training\comparison_review_queue_web.py"),
        (Join-Path $ProjectRoot "application\src\isala_ocr\training\job_cancellation.py"),
        (Join-Path $ProjectRoot "application\src\isala_ocr\training\recognition_ground_truth_web.py"),
        (Join-Path $ProjectRoot "application\src\isala_ocr\training\recognition_model_factory.py")
    )
    $fullName = [System.IO.Path]::GetFullPath($File.FullName)
    foreach ($path in $uiOnlyFiles) {
        if ($fullName.Equals([System.IO.Path]::GetFullPath($path), [System.StringComparison]::OrdinalIgnoreCase)) {
            return $false
        }
    }

    return $true
}

function Get-IsalaRuntimeBuildInputs {
    $files = New-Object System.Collections.Generic.List[System.IO.FileInfo]
    foreach ($relativePath in @(
        "infrastructure\docker\Dockerfile.runtime",
        "application\requirements\runtime.txt",
        "application\pyproject.toml"
    )) {
        $path = Join-Path $ProjectRoot $relativePath
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $files.Add((Get-Item -LiteralPath $path))
        }
    }

    # application/config is deliberately not a build-freshness input. Every
    # shared-runtime Compose service bind-mounts the current config at /app/config,
    # so a config edit is visible immediately and does not require image rebuild.
    foreach ($relativeDirectory in @(
        "application\src",
        "application\schemas"
    )) {
        $directory = Join-Path $ProjectRoot $relativeDirectory
        if (Test-Path -LiteralPath $directory -PathType Container) {
            foreach ($file in @(Get-ChildItem -LiteralPath $directory -Recurse -File -ErrorAction SilentlyContinue)) {
                if (Test-IsalaComputeRuntimeInput -File $file) {
                    $files.Add($file)
                }
            }
        }
    }
    return @($files | Sort-Object FullName -Unique)
}

function Get-IsalaRuntimeLatestInputStamp {
    $inputs = @(Get-IsalaRuntimeBuildInputs)
    if ($inputs.Count -eq 0) { return [DateTime]::MinValue }
    return [DateTime](($inputs | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1).LastWriteTimeUtc)
}

function Get-IsalaRuntimePreparationState {
    $image = Get-IsalaRuntimeImageName
    $imageState = Get-DockerImageState -Image $image -RetryCount 2 -RetryDelayMilliseconds 250
    $latestInput = Get-IsalaRuntimeLatestInputStamp
    if (-not $imageState.Present) {
        return [pscustomobject]@{
            Ready = $false
            State = "missing"
            Image = $image
            ImageId = ""
            ImageCreatedUtc = $null
            LatestInputUtc = $latestInput
            Detail = "Prepared shared runtime image is missing."
        }
    }

    $createdProbe = Invoke-DockerWithTimeout -Arguments @(
        "image", "inspect", "--format", "{{.Created}}", $image
    ) -TimeoutSeconds 20
    $createdText = if ($null -ne $createdProbe) { ([string]$createdProbe.StdOut).Trim() } else { "" }
    $created = [DateTimeOffset]::MinValue
    $createdOk = [DateTimeOffset]::TryParse(
        $createdText,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::AssumeUniversal,
        [ref]$created
    )
    if (-not $createdOk) {
        return [pscustomobject]@{
            Ready = $false
            State = "unknown"
            Image = $image
            ImageId = [string]$imageState.Id
            ImageCreatedUtc = $null
            LatestInputUtc = $latestInput
            Detail = "Prepared runtime image exists, but its build timestamp could not be read."
        }
    }

    # Docker records the final image timestamp at build completion. Only actual
    # compute-runtime inputs newer than that image make Stap 1 stale. Restarting
    # Docker/the WebUI or editing UI-only files does not affect this timestamp.
    $createdUtc = $created.UtcDateTime
    $ready = ($createdUtc -ge $latestInput)
    return [pscustomobject]@{
        Ready = $ready
        State = $(if ($ready) { "ready" } else { "stale" })
        Image = $image
        ImageId = [string]$imageState.Id
        ImageCreatedUtc = $createdUtc
        LatestInputUtc = $latestInput
        Detail = $(if ($ready) {
            "Prepared shared runtime image matches the current compute checkout."
        } else {
            "Prepared shared runtime image is older than the current compute-runtime inputs."
        })
    }
}

function Assert-IsalaRuntimePrepared {
    $state = Get-IsalaRuntimePreparationState
    if (-not [bool]$state.Ready) {
        $imageStamp = if ($null -ne $state.ImageCreatedUtc) { ([DateTime]$state.ImageCreatedUtc).ToString("o") } else { "missing/unknown" }
        $inputStamp = if ($null -ne $state.LatestInputUtc) { ([DateTime]$state.LatestInputUtc).ToString("o") } else { "unknown" }
        throw @"
IsalaOCR runtime is not prepared for the current compute checkout.
State: $($state.State)
Image: $($state.Image)
Image built: $imageStamp
Newest compute-runtime input: $inputStamp

Open Stap 1 - Voorbereiding only after compute-runtime code, requirements, schemas or Dockerfile.runtime changed. A normal restart or WebUI-only update does not require preparation.
"@
    }
    return $state
}
