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

function Get-IsalaRuntimeBuildInputs {
    $files = New-Object System.Collections.Generic.List[System.IO.FileInfo]
    foreach ($relativePath in @(
        "infrastructure\docker\Dockerfile.runtime",
        "application\requirements\runtime.txt",
        "application\pyproject.toml",
        "application\README.md"
    )) {
        $path = Join-Path $ProjectRoot $relativePath
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $files.Add((Get-Item -LiteralPath $path))
        }
    }
    foreach ($relativeDirectory in @(
        "application\src",
        "application\config",
        "application\schemas"
    )) {
        $directory = Join-Path $ProjectRoot $relativeDirectory
        if (Test-Path -LiteralPath $directory -PathType Container) {
            foreach ($file in @(Get-ChildItem -LiteralPath $directory -Recurse -File -ErrorAction SilentlyContinue)) {
                $files.Add($file)
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

    # Docker records the final image timestamp at build completion. A source,
    # config, schema, package metadata, Dockerfile or requirements file that is
    # newer than that image means Stap 1 has not prepared the current checkout.
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
            "Prepared shared runtime image matches the current checkout."
        } else {
            "Prepared shared runtime image is older than the current runtime inputs."
        })
    }
}

function Assert-IsalaRuntimePrepared {
    $state = Get-IsalaRuntimePreparationState
    if (-not [bool]$state.Ready) {
        $imageStamp = if ($null -ne $state.ImageCreatedUtc) { ([DateTime]$state.ImageCreatedUtc).ToString("o") } else { "missing/unknown" }
        $inputStamp = if ($null -ne $state.LatestInputUtc) { ([DateTime]$state.LatestInputUtc).ToString("o") } else { "unknown" }
        throw @"
IsalaOCR runtime is not prepared for the current checkout.
State: $($state.State)
Image: $($state.Image)
Image built: $imageStamp
Newest runtime input: $inputStamp

Open Stap 1 · Voorbereiding and run the recommended preparation again. Stap 5 no longer rebuilds or downloads the general Python/PaddleOCR dependency layer implicitly.
"@
    }
    return $state
}
