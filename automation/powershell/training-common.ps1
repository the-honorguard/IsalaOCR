$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ProjectMetadataRoot = Join-Path $ProjectRoot "project"
$ComposeFile = Join-Path $ProjectRoot "infrastructure\docker\compose.yaml"
$env:COMPOSE_FILE = $ComposeFile
$env:COMPOSE_PROJECT_NAME = if ($env:ISALA_COMPOSE_PROJECT_NAME) { $env:ISALA_COMPOSE_PROJECT_NAME } else { "isalaocr_docker2" }
$env:DOCKER_BUILDKIT = "1"
Set-Location $ProjectRoot


function Get-TrainingImageVersion {
    $versionFile = Join-Path $ProjectMetadataRoot "TRAINING_IMAGE_VERSION"
    if (-not (Test-Path -LiteralPath $versionFile -PathType Leaf)) {
        throw "TRAINING_IMAGE_VERSION file is missing: $versionFile"
    }
    $version = (Get-Content -LiteralPath $versionFile -Raw).Trim()
    if ($version -notmatch '^[0-9A-Za-z][0-9A-Za-z._-]*$') {
        throw "TRAINING_IMAGE_VERSION contains an invalid Docker tag: $version"
    }
    return $version
}

# Compose reads this environment variable when resolving the reusable training
# image tags. The training image revision is deliberately independent from the
# application release so host-script-only hotfixes do not invalidate gigabytes
# of already downloaded CUDA and PaddlePaddle layers.
$env:ISALA_TRAINING_IMAGE_VERSION = Get-TrainingImageVersion

function Get-IsalaActiveProjectId {
    $candidate = [string]$env:ISALA_PROJECT_ID
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $statePath = Join-Path $ProjectRoot "training\workspace\active_project.json"
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            try {
                $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
                $candidate = [string]$state.project_id
            } catch { $candidate = "" }
        }
    }
    if ([string]::IsNullOrWhiteSpace($candidate)) { $candidate = "cmr_testcase_01" }
    if ($candidate -notmatch '^[a-z0-9][a-z0-9_-]{0,63}$') { throw "Invalid IsalaOCR project ID: $candidate" }
    return $candidate
}

function Get-IsalaHostProjectWorkspace {
    return (Join-Path $ProjectRoot ("training\workspace\projects\{0}" -f (Get-IsalaActiveProjectId)))
}

function Get-IsalaContainerWorkspace {
    return "/training/workspace/projects/$(Get-IsalaActiveProjectId)"
}

function Get-IsalaContainerProjectInput {
    $projectId = Get-IsalaActiveProjectId
    $projectFile = Join-Path (Get-IsalaHostProjectWorkspace) "project.json"
    $candidate = ""
    if (Test-Path -LiteralPath $projectFile -PathType Leaf) {
        try {
            $projectState = Get-Content -LiteralPath $projectFile -Raw | ConvertFrom-Json
            $candidate = [string]$projectState.input_path
        } catch { $candidate = "" }
    }
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $candidate = if ($projectId -eq "cmr_testcase_01") { "/input" } else { "/input/projects/$projectId" }
    }
    $candidate = ($candidate -replace '\\','/').TrimEnd('/')
    if ([string]::IsNullOrWhiteSpace($candidate)) { $candidate = "/input" }
    if ($candidate -ne "/input" -and -not $candidate.StartsWith("/input/")) {
        throw "Invalid project input path '$candidate'. It must be /input or a subdirectory below /input."
    }
    if ($candidate -match '(^|/)\.\.(/|$)') { throw "Invalid project input path '$candidate'." }
    return $candidate
}

function Get-IsalaHostProjectInput {
    $containerPath = Get-IsalaContainerProjectInput
    $relative = $containerPath.Substring('/input'.Length).TrimStart('/')
    $hostRoot = Join-Path $ProjectRoot 'input'
    if ([string]::IsNullOrWhiteSpace($relative)) { return $hostRoot }
    return (Join-Path $hostRoot ($relative -replace '/', [IO.Path]::DirectorySeparatorChar))
}

function Get-IsalaContainerRegistry {
    return "/training/registry/projects/$(Get-IsalaActiveProjectId)"
}

function Get-IsalaHostProjectRegistry {
    return (Join-Path $ProjectRoot ("training\registry\projects\{0}" -f (Get-IsalaActiveProjectId)))
}

function Get-IsalaContainerActiveRecognition {
    return "/models/projects/$(Get-IsalaActiveProjectId)/active-recognition"
}

function Invoke-NativeProcessWithTimeout {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = 20
    )

    if ($TimeoutSeconds -lt 1) { $TimeoutSeconds = 1 }

    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()
    $process = $null
    try {
        $startParams = @{
            FilePath = $FilePath
            ArgumentList = $Arguments
            PassThru = $true
            NoNewWindow = $true
            RedirectStandardOutput = $stdoutFile
            RedirectStandardError = $stderrFile
            ErrorAction = 'Stop'
        }
        $process = Start-Process @startParams
        $finished = $process.WaitForExit($TimeoutSeconds * 1000)
        if (-not $finished) {
            try { $process.Kill() } catch { }
            try { $process.WaitForExit(3000) | Out-Null } catch { }
        }
        else {
            # Windows PowerShell 5.1 can expose an incomplete Process object after
            # WaitForExit(timeout). The parameterless call and Refresh make ExitCode
            # reliable after redirected stdout/stderr have been flushed.
            try { $process.WaitForExit() } catch { }
            try { $process.Refresh() } catch { }
        }

        $stdout = if (Test-Path $stdoutFile) { Get-Content $stdoutFile -Raw -ErrorAction SilentlyContinue } else { '' }
        $stderr = if (Test-Path $stderrFile) { Get-Content $stderrFile -Raw -ErrorAction SilentlyContinue } else { '' }
        $exitCode = $null
        if ($finished) {
            try { $exitCode = [int]$process.ExitCode } catch { $exitCode = $null }
        }

        return [pscustomobject]@{
            FilePath = $FilePath
            Arguments = @($Arguments)
            ExitCode = $exitCode
            TimedOut = (-not $finished)
            StdOut = [string]$stdout
            StdErr = [string]$stderr
        }
    }
    catch {
        return [pscustomobject]@{
            FilePath = $FilePath
            Arguments = @($Arguments)
            ExitCode = $null
            TimedOut = $false
            StdOut = ''
            StdErr = $_.Exception.Message
        }
    }
    finally {
        Remove-Item $stdoutFile,$stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-DockerWithTimeout {
    param(
        [string[]]$Arguments,
        [int]$TimeoutSeconds = 20
    )
    return Invoke-NativeProcessWithTimeout -FilePath 'docker.exe' -Arguments $Arguments -TimeoutSeconds $TimeoutSeconds
}

function Get-IsalaProcessOutputText {
    param(
        $Result,
        [string]$Fallback = "The process returned no diagnostic output."
    )

    if ($null -eq $Result) { return $Fallback }
    $stdout = [string]$Result.StdOut
    $stderr = [string]$Result.StdErr
    $combined = ($stdout + [Environment]::NewLine + $stderr).Trim()
    if ([string]::IsNullOrWhiteSpace($combined)) { return $Fallback }
    return $combined
}

function Write-NativeProcessResult {
    param(
        $Result,
        [switch]$IncludeEmpty
    )

    if ($null -eq $Result) {
        if ($IncludeEmpty) { Write-Host "(no process result)" -ForegroundColor DarkGray }
        return
    }
    $stdout = [string]$Result.StdOut
    $stderr = [string]$Result.StdErr
    if (-not [string]::IsNullOrWhiteSpace($stdout)) {
        Write-Host $stdout.TrimEnd()
    }
    elseif ($IncludeEmpty) {
        Write-Host "(no standard output)" -ForegroundColor DarkGray
    }

    if (-not [string]::IsNullOrWhiteSpace($stderr)) {
        Write-Host $stderr.TrimEnd() -ForegroundColor DarkYellow
    }
}

function Test-DockerEngineResult {
    param($Result)

    if ($null -eq $Result -or $Result.TimedOut) { return $false }

    $combined = Get-IsalaProcessOutputText -Result $Result -Fallback ""
    if ($combined -match '(?im)error during connect|cannot connect to the docker daemon|open //\./pipe|the system cannot find the file specified|het systeem kan het opgegeven bestand niet vinden') {
        return $false
    }

    if ($Result.ExitCode -eq 0) { return $true }

    # Fallback for Windows PowerShell 5.1: Start-Process can occasionally fail
    # to expose ExitCode even though Docker returned a complete successful result.
    # A valid Docker Desktop response contains a Server section, Engine section,
    # and a Linux server architecture.
    $stdout = [string]$Result.StdOut
    return (
        $stdout -match '(?im)^Server:' -and
        $stdout -match '(?im)^\s*Engine:' -and
        $stdout -match '(?im)^\s*OS/Arch:\s*linux/'
    )
}

function Get-DockerDesktopExecutable {
    $candidates = New-Object System.Collections.Generic.List[string]

    foreach ($root in @($env:ProgramFiles, $env:ProgramW6432, $env:LOCALAPPDATA)) {
        if (-not [string]::IsNullOrWhiteSpace($root)) {
            $candidates.Add((Join-Path $root 'Docker\Docker\Docker Desktop.exe'))
        }
    }

    foreach ($registryPath in @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Docker Desktop.exe',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Docker Desktop.exe'
    )) {
        try {
            $entry = Get-ItemProperty -Path $registryPath -ErrorAction SilentlyContinue
            if ($null -eq $entry) { continue }
            if ($entry.'(default)') { $candidates.Add([string]$entry.'(default)') }
            elseif ($entry.PSPath) {
                $defaultValue = (Get-Item -Path $registryPath -ErrorAction SilentlyContinue).GetValue('')
                if ($defaultValue) { $candidates.Add([string]$defaultValue) }
            }
        }
        catch { }
    }

    try {
        $command = Get-Command 'Docker Desktop.exe' -ErrorAction Stop
        if ($command.Source) { $candidates.Add([string]$command.Source) }
    }
    catch { }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Test-DockerDesktopProcess {
    $processes = Get-Process -Name 'Docker Desktop','com.docker.backend' -ErrorAction SilentlyContinue
    return ($null -ne $processes)
}

function Start-DockerDesktopIfNeeded {
    if (Test-DockerDesktopProcess) {
        Write-Host 'Docker Desktop is already starting or running. Waiting for the Linux engine...' -ForegroundColor Yellow
        return
    }

    $executable = Get-DockerDesktopExecutable
    if ([string]::IsNullOrWhiteSpace($executable)) {
        throw @"
The Docker CLI is installed, but Docker Desktop could not be found in a supported installation location.
Start Docker Desktop manually and run this task again.
"@
    }

    Write-Host "Docker Engine is not available. Starting Docker Desktop..." -ForegroundColor Yellow
    Start-Process -FilePath $executable -ErrorAction Stop | Out-Null
}

function Assert-Docker {
    if (-not (Get-Command 'docker.exe' -ErrorAction SilentlyContinue)) {
        throw 'Docker CLI was not found. Install Docker Desktop or add docker.exe to PATH.'
    }

    $initial = Invoke-DockerWithTimeout -Arguments @('version') -TimeoutSeconds 20
    if (Test-DockerEngineResult $initial) { return }

    Start-DockerDesktopIfNeeded

    # Docker Desktop can take several minutes to restore its WSL2 VM after a
    # Windows reboot. Keep the startup task alive long enough for that normal
    # cold-start path to complete instead of failing while Docker is still
    # booting.
    $waitSeconds = 360
    $pollSeconds = 3
    $deadline = (Get-Date).AddSeconds($waitSeconds)
    $attempt = 0
    $lastResult = $initial

    while ((Get-Date) -lt $deadline) {
        $attempt++
        $elapsed = [Math]::Min($waitSeconds, $attempt * $pollSeconds)
        Write-Host ("Waiting for Docker Desktop [{0}/{1}s]" -f $elapsed, $waitSeconds) -ForegroundColor DarkYellow
        Start-Sleep -Seconds $pollSeconds

        $lastResult = Invoke-DockerWithTimeout -Arguments @('version') -TimeoutSeconds 12
        if (Test-DockerEngineResult $lastResult) {
            Write-Host 'Docker Desktop is ready. Continuing...' -ForegroundColor Green
            return
        }
    }

    $details = Get-IsalaProcessOutputText -Result $lastResult -Fallback 'No response was received from Docker.'

    throw @"
Docker Desktop did not become ready within $waitSeconds seconds.
Close and restart Docker Desktop. If it remains stuck, run 'wsl --shutdown' and start Docker Desktop again.
Last Docker response:
$details
"@
}

function Initialize-TrainingRunDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [switch]$Reset
    )

    if ([string]::IsNullOrWhiteSpace($Name) -or
        $Name.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -ge 0 -or
        $Name.Contains('\') -or $Name.Contains('/')) {
        throw "Invalid training run directory name: $Name"
    }

    $runsRoot = Join-Path (Get-IsalaHostProjectWorkspace) "runs"
    New-Item -ItemType Directory -Path $runsRoot -Force | Out-Null
    $directory = Join-Path $runsRoot $Name

    if ($Reset -and (Test-Path -LiteralPath $directory)) {
        Write-Host "Removing stale validation output: training\workspace\runs\$Name" -ForegroundColor DarkYellow
        Remove-Item -LiteralPath $directory -Recurse -Force
    }
    elseif ((Test-Path -LiteralPath $directory) -and -not (Test-Path -LiteralPath $directory -PathType Container)) {
        throw "Training output path exists but is not a directory: $directory"
    }

    New-Item -ItemType Directory -Path $directory -Force | Out-Null

    # Create and delete a host-side probe. This both verifies NTFS access and
    # ensures Docker Desktop receives a host-created bind-mounted directory,
    # rather than reusing a directory created by an older container UID/GID.
    $probe = Join-Path $directory (".isalaocr-host-write-probe-{0}" -f $PID)
    try {
        [System.IO.File]::WriteAllText($probe, "ok", [System.Text.UTF8Encoding]::new($false))
    }
    catch {
        throw "Training output directory is not writable from Windows: $directory. $($_.Exception.Message)"
    }
    finally {
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
    }

    return $directory
}

function Get-IsalaDatasetInfo {
    param([Parameter(Mandatory = $true)][string]$DatasetId)

    $cleanId = ([string]$DatasetId).Trim().TrimStart([char]0xFEFF)
    $datasetsRoot = Join-Path (Get-IsalaHostProjectWorkspace) "datasets"
    $validName = (-not [string]::IsNullOrWhiteSpace($cleanId)) -and
        ($cleanId -match '^[0-9A-Za-z][0-9A-Za-z._-]*$')
    $datasetRoot = if ($validName) { Join-Path $datasetsRoot $cleanId } else { $null }
    $required = @("train.txt", "val.txt", "test.txt", "manifest.json")
    $optional = @("characters.txt")
    $missing = New-Object System.Collections.Generic.List[string]
    $optionalMissing = New-Object System.Collections.Generic.List[string]

    if (-not $validName) {
        foreach ($name in $required) { $missing.Add($name) }
    }
    elseif (-not (Test-Path -LiteralPath $datasetRoot -PathType Container)) {
        foreach ($name in $required) { $missing.Add($name) }
    }
    else {
        foreach ($name in $required) {
            if (-not (Test-Path -LiteralPath (Join-Path $datasetRoot $name) -PathType Leaf)) {
                $missing.Add($name)
            }
        }
        foreach ($name in $optional) {
            if (-not (Test-Path -LiteralPath (Join-Path $datasetRoot $name) -PathType Leaf)) {
                $optionalMissing.Add($name)
            }
        }
    }

    return [pscustomobject]@{
        Id = $cleanId
        ValidName = $validName
        Root = $datasetRoot
        Exists = ($validName -and (Test-Path -LiteralPath $datasetRoot -PathType Container))
        Ready = ($missing.Count -eq 0)
        MissingFiles = @($missing)
        OptionalMissingFiles = @($optionalMissing)
        DictionaryReady = ($validName -and (Test-Path -LiteralPath (Join-Path $datasetRoot "dict.txt") -PathType Leaf))
    }
}

function Get-LatestDatasetResolution {
    $datasetsRoot = Join-Path (Get-IsalaHostProjectWorkspace) "datasets"
    $pointer = Join-Path $datasetsRoot "latest.txt"
    $pointerExists = Test-Path -LiteralPath $pointer -PathType Leaf
    $pointerValue = ""
    $pointerInfo = $null
    $pointerProblem = ""

    if ($pointerExists) {
        try {
            $pointerValue = ([string](Get-Content -LiteralPath $pointer -Raw -ErrorAction Stop)).Trim().TrimStart([char]0xFEFF)
            $pointerInfo = Get-IsalaDatasetInfo -DatasetId $pointerValue
            if (-not $pointerInfo.ValidName) {
                $pointerProblem = "latest.txt contains an invalid dataset ID: '$pointerValue'."
            }
            elseif (-not $pointerInfo.Exists) {
                $pointerProblem = "latest.txt points to a missing dataset directory: $pointerValue."
            }
            elseif (-not $pointerInfo.Ready) {
                $pointerProblem = "latest.txt points to an incomplete dataset '$pointerValue'; missing: $($pointerInfo.MissingFiles -join ', ')."
            }
        }
        catch {
            $pointerProblem = "latest.txt could not be read: $($_.Exception.Message)"
        }
    }
    else {
        $pointerProblem = "latest.txt is missing."
    }

    if ($pointerInfo -and $pointerInfo.Ready) {
        return [pscustomobject]@{
            Found = $true
            Dataset = $pointerInfo
            Source = "pointer"
            PointerPath = $pointer
            PointerProblem = ""
        }
    }

    $fallback = $null
    if (Test-Path -LiteralPath $datasetsRoot -PathType Container) {
        foreach ($directory in @(Get-ChildItem -LiteralPath $datasetsRoot -Directory -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)) {
            $candidate = Get-IsalaDatasetInfo -DatasetId $directory.Name
            if ($candidate.Ready) {
                $fallback = $candidate
                break
            }
        }
    }

    return [pscustomobject]@{
        Found = ($null -ne $fallback)
        Dataset = $fallback
        Source = $(if ($fallback) { "fallback" } else { "none" })
        PointerPath = $pointer
        PointerProblem = $pointerProblem
    }
}

function Repair-LatestDatasetPointer {
    param([Parameter(Mandatory = $true)][string]$DatasetId)
    $datasetsRoot = Join-Path (Get-IsalaHostProjectWorkspace) "datasets"
    New-Item -ItemType Directory -Path $datasetsRoot -Force | Out-Null
    $pointer = Join-Path $datasetsRoot "latest.txt"
    [IO.File]::WriteAllText($pointer, $DatasetId, [Text.UTF8Encoding]::new($false))
}

function Get-LatestDatasetId {
    $resolution = Get-LatestDatasetResolution
    if (-not $resolution.Found) {
        $details = if ($resolution.PointerProblem) { $resolution.PointerProblem } else { "No complete dataset directory was found." }
        throw "$details Run option 7 only when no reviewed dataset is available."
    }
    if ($resolution.Source -eq "fallback") {
        Repair-LatestDatasetPointer -DatasetId $resolution.Dataset.Id
        Write-Host ("Repaired latest dataset pointer: {0}" -f $resolution.Dataset.Id) -ForegroundColor DarkYellow
    }
    return $resolution.Dataset.Id
}

function Get-LatestRunDirectory {
    $pointer = Join-Path (Get-IsalaHostProjectWorkspace) "runs\latest-run.txt"
    if (Test-Path $pointer) {
        $runId = (Get-Content $pointer -Raw).Trim()
        $path = Join-Path (Get-IsalaHostProjectWorkspace) "runs\$runId"
        if (Test-Path $path) { return (Resolve-Path $path).Path }
    }
    $runs = Get-ChildItem (Join-Path (Get-IsalaHostProjectWorkspace) "runs") -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "run-*" } | Sort-Object LastWriteTime -Descending
    if (-not $runs) { throw "No training run exists yet." }
    return $runs[0].FullName
}

function Get-InferenceDirectory([string]$RunDirectory) {
    $run = (Resolve-Path $RunDirectory).Path
    $candidates = @(
        (Join-Path $run "best_accuracy\inference"),
        (Join-Path $run "inference"),
        (Join-Path $run "exported")
    )
    foreach ($candidate in $candidates) {
        if ((Test-Path (Join-Path $candidate "inference.json")) -or
            (Test-Path (Join-Path $candidate "inference.pdmodel"))) { return $candidate }
    }
    $found = Get-ChildItem $run -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("inference.json", "inference.pdmodel") } |
        Select-Object -First 1
    if ($found) { return $found.Directory.FullName }
    throw "No exported inference model was found under $run. Run export-recognition-model.ps1."
}

function Get-LatestEvaluationFile([ValidateSet("baseline","custom")][string]$Kind) {
    $runsRoot = Join-Path (Get-IsalaHostProjectWorkspace) "runs"
    $matches = Get-ChildItem $runsRoot -Recurse -Filter evaluation.json -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Directory.Name -like "*${Kind}*" -or $_.Directory.Parent.Name -like "*${Kind}*" } |
        Sort-Object LastWriteTime -Descending
    if (-not $matches) { throw "No $Kind evaluation was found. Run evaluate-recognition-model first." }
    return $matches[0].FullName
}

function Convert-ToContainerTrainingPath([string]$HostPath) {
    $full = (Resolve-Path $HostPath).Path
    $trainingRoot = (Resolve-Path (Join-Path $ProjectRoot "training")).Path
    if (-not $full.StartsWith($trainingRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path must be below the training directory: $HostPath"
    }
    $relative = $full.Substring($trainingRoot.Length).TrimStart('\','/') -replace '\\','/'
    return "/training/$relative"
}


function Get-TrainingImageName {
    param(
        [ValidateSet("cpu","gpu","gpu-detection")]
        [string]$Device
    )

    $version = Get-TrainingImageVersion
    return "isalaocr-training-${Device}:$version"
}

function Get-DockerImageState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Image,
        [int]$TimeoutSeconds = 20,
        [int]$RetryCount = 1,
        [int]$RetryDelayMilliseconds = 350
    )

    if ($RetryCount -lt 1) { $RetryCount = 1 }
    $lastResult = $null
    for ($attempt = 1; $attempt -le $RetryCount; $attempt++) {
        $result = Invoke-DockerWithTimeout -Arguments @("image", "inspect", "--format", "{{.Id}}", $Image) -TimeoutSeconds $TimeoutSeconds
        $lastResult = $result
        $id = if ($null -ne $result) { ([string]$result.StdOut).Trim() } else { "" }

        # Docker Desktop on Windows can occasionally expose a null/late ExitCode
        # immediately after BuildKit exported an image. A valid inspect ID is
        # authoritative even in that case; a blank ID is never treated as present.
        $present = (
            $null -ne $result -and
            -not $result.TimedOut -and
            -not [string]::IsNullOrWhiteSpace($id) -and
            $id -match '^sha256:[0-9a-fA-F]{32,}$' -and
            ($result.ExitCode -eq 0 -or $null -eq $result.ExitCode)
        )
        if ($present) {
            return [pscustomobject]@{
                Image = $Image
                Present = $true
                Id = $id
                Detail = $id
                Result = $result
                Attempts = $attempt
            }
        }

        if ($attempt -lt $RetryCount -and $RetryDelayMilliseconds -gt 0) {
            Start-Sleep -Milliseconds $RetryDelayMilliseconds
        }
    }

    $detail = Get-IsalaProcessOutputText -Result $lastResult -Fallback "Docker image not found or Docker is not reachable."
    return [pscustomobject]@{
        Image = $Image
        Present = $false
        Id = ""
        Detail = $detail
        Result = $lastResult
        Attempts = $RetryCount
    }
}

function Get-DockerImageId {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Image,
        [int]$RetryCount = 1
    )

    $state = Get-DockerImageState -Image $Image -RetryCount $RetryCount
    if (-not $state.Present) { return "" }
    return [string]$state.Id
}

function Test-TrainingImagePrepared {
    param(
        [ValidateSet("cpu","gpu","gpu-detection")]
        [string]$Device
    )

    $image = Get-TrainingImageName -Device $Device
    $state = Get-DockerImageState -Image $image
    return [bool]$state.Present
}

function Assert-TrainingImagePrepared {
    param(
        [ValidateSet("cpu","gpu","gpu-detection")]
        [string]$Device
    )

    $image = Get-TrainingImageName -Device $Device
    if (-not (Test-TrainingImagePrepared -Device $Device)) {
        throw @"
Prepared training image is missing: $image
Open Stap 1 · Voorbereiding and install the missing component: CPU/PicoDet, GPU OCR recognition, or GPU PaddleDetection/PicoDet. “Alles voorbereiden” installs everything.
"@
    }
    return $image
}

function Assert-IsalaDetectionGateOpen {
    # v3.11 table-first: the authoritative TABLE-FIRST CHECK lives in the web UI
    # and is evaluated directly from SQLite review data before value jobs can be
    # enqueued. Do not require the legacy field-detector detection_gate.json in
    # that mode; it is intentionally parked and may remain closed forever.
    $configPath = Join-Path $ProjectRoot "application\config\app.yaml"
    if (Test-Path -LiteralPath $configPath -PathType Leaf) {
        $tableFirst = Select-String -LiteralPath $configPath -Pattern '^\s*strategy\s*:\s*table_first\s*$' -Quiet
        if ($tableFirst) { return }
    }

    $gatePath = Join-Path (Get-IsalaHostProjectWorkspace) "detection_gate.json"
    if (-not (Test-Path -LiteralPath $gatePath -PathType Leaf)) {
        throw "DETECTION GATE is closed. Train and evaluate the field detector before starting Mapping/OCR."
    }
    try {
        $gate = Get-Content -LiteralPath $gatePath -Raw | ConvertFrom-Json
    }
    catch {
        throw "Detection gate state is unreadable: $gatePath"
    }
    if (-not [bool]$gate.ready) {
        $reason = [string]$gate.reason
        if ([string]::IsNullOrWhiteSpace($reason)) { $reason = "The trained field detector has not passed the quality thresholds." }
        throw ("DETECTION GATE is closed: {0}" -f $reason)
    }
}

function Assert-IsalaActionPreflight {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ActionId
    )

    if ($env:ISALA_PREFLIGHT_APPROVED -eq $ActionId -or $env:ISALA_NESTED_PREFLIGHT_APPROVED -eq "1") { return }

    $preflightScript = Join-Path $PSScriptRoot "preflight.ps1"
    if (-not (Test-Path -LiteralPath $preflightScript -PathType Leaf)) {
        throw "Preflight framework is missing: $preflightScript"
    }
    . $preflightScript

    $allowDockerFailure = ($ActionId -eq "5")
    $check = Invoke-IsalaPreflight -ActionId $ActionId `
        -EnsureDocker:(-not $allowDockerFailure) `
        -AllowDockerFailure:$allowDockerFailure
    if (-not $check.Passed) {
        throw "Prerequisite check failed for this task."
    }
    $env:ISALA_PREFLIGHT_APPROVED = $ActionId
}
