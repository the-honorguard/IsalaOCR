param(
    [int]$PreferredPort = 8088,
    [int]$StartupTimeoutSeconds = 300,
    [switch]$NoBrowser,
    [switch]$ForceRebuild
)

$ErrorActionPreference = "Stop"
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

function Wait-IsalaWebUiQuiet {
    param([int]$QuietSeconds = 30)
    $root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    $watchRoots = @(
        (Join-Path $root "application\src\isala_ocr"),
        (Join-Path $root "application\config"),
        (Join-Path $root "infrastructure\docker\Dockerfile.labeler"),
        (Join-Path $root "infrastructure\docker\compose.yaml")
    )
    $extensions = @('.py', '.html', '.css', '.js', '.yaml', '.yml', '.json')
    while ($true) {
        $latest = $null
        foreach ($watchRoot in $watchRoots) {
            $files = if (Test-Path -LiteralPath $watchRoot -PathType Leaf) {
                @(Get-Item -LiteralPath $watchRoot)
            } elseif (Test-Path -LiteralPath $watchRoot -PathType Container) {
                @(Get-ChildItem -LiteralPath $watchRoot -Recurse -File -ErrorAction SilentlyContinue |
                    Where-Object { $extensions -contains $_.Extension.ToLowerInvariant() })
            } else { @() }
            foreach ($file in $files) {
                if ($null -eq $latest -or $file.LastWriteTimeUtc -gt $latest) {
                    $latest = $file.LastWriteTimeUtc
                }
            }
        }
        $quietFor = if ($null -eq $latest) { $QuietSeconds } else { ((Get-Date).ToUniversalTime() - $latest).TotalSeconds }
        if ($quietFor -ge $QuietSeconds) { return }
        $remaining = [math]::Ceiling($QuietSeconds - $quietFor)
        Write-Host ("Automatische WebUI-update wacht nog {0} seconden op een stille workspace..." -f $remaining) -ForegroundColor DarkYellow
        Start-Sleep -Seconds ([math]::Min(5, [math]::Max(1, $remaining)))
    }
}

if ($NoBrowser -and -not $ForceRebuild) {
    Wait-IsalaWebUiQuiet
}
. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-IsalaActionPreflight -ActionId "3"
. (Join-Path $PSScriptRoot "labeler-common.ps1")
Assert-Docker

# The browser queues long-running actions as JSON jobs. A single hidden host-side
# PowerShell worker executes the existing, preflight-protected scripts. Docker's
# socket is deliberately not exposed to the web container.
$workerScript = Join-Path $PSScriptRoot "webui-worker.ps1"
$jobsRoot = Join-Path $ProjectRoot "training\workspace\webui\jobs"
$workerStateFile = Join-Path $jobsRoot "worker.json"
$workerStartupLog = Join-Path $jobsRoot "worker-startup.log"
$workerStartupErrorLog = Join-Path $jobsRoot "worker-startup.err.log"
$expectedWorkerVersion = Get-IsalaWorkerVersionFingerprint
New-Item -ItemType Directory -Path $jobsRoot -Force | Out-Null

function Test-IsalaWorkerState {
    param($State,[int]$MaxHeartbeatAgeSeconds=15)
    if ($null -eq $State -or $null -eq $State.pid -or $null -eq $State.heartbeat_at) { return $false }
    try {
        $pidValue=[int]$State.pid
        $process=Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($null -eq $process -or $process.ProcessName -notin @('powershell','pwsh')) { return $false }
        $heartbeat=[datetimeoffset]::Parse([string]$State.heartbeat_at)
        if ((([datetimeoffset]::Now)-$heartbeat).TotalSeconds -gt $MaxHeartbeatAgeSeconds) { return $false }
        $cim=Get-CimInstance Win32_Process -Filter "ProcessId = $pidValue" -ErrorAction SilentlyContinue
        if ($null -eq $cim -or [string]$cim.CommandLine -notmatch '(?i)webui-worker\.ps1') { return $false }
        if ([string]$State.worker_version -ne $expectedWorkerVersion) { return $false }
        return $true
    } catch { return $false }
}

function Stop-ObsoleteIsalaWorker {
    param($State)
    if ($null -eq $State -or $null -eq $State.pid) { return }
    try {
        $pidValue=[int]$State.pid
        $cim=Get-CimInstance Win32_Process -Filter "ProcessId = $pidValue" -ErrorAction SilentlyContinue
        if ($null -eq $cim -or [string]$cim.CommandLine -notmatch '(?i)webui-worker\.ps1') { return }
        Write-Host "Stopping obsolete or unhealthy IsalaOCR worker (PID $pidValue)..." -ForegroundColor Yellow
        try { & taskkill.exe /PID $pidValue /T /F *> $null }
        catch { Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 500
    }
    catch {
        Write-Warning "The obsolete worker could not be stopped cleanly: $($_.Exception.Message)"
    }
}

$workerHealthy=$false
if (Test-Path $workerStateFile) {
    $workerState=$null
    try {
        $workerState = Get-Content $workerStateFile -Raw | ConvertFrom-Json
        $workerHealthy = Test-IsalaWorkerState $workerState
    } catch { $workerHealthy=$false }
    if (-not $workerHealthy) {
        Stop-ObsoleteIsalaWorker -State $workerState
        Remove-Item $workerStateFile -Force -ErrorAction SilentlyContinue
    }
}

if (-not $workerHealthy) {
    Remove-Item $workerStartupLog,$workerStartupErrorLog -Force -ErrorAction SilentlyContinue
    $workerArgumentLine='-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $workerScript.Replace('"','""')
    Start-Process -FilePath "powershell.exe" -ArgumentList $workerArgumentLine -WindowStyle Hidden `
        -RedirectStandardOutput $workerStartupLog -RedirectStandardError $workerStartupErrorLog | Out-Null

    $workerDeadline=(Get-Date).AddSeconds(12)
    while((Get-Date) -lt $workerDeadline){
        Start-Sleep -Milliseconds 500
        if(Test-Path $workerStateFile){
            try{
                $workerState=Get-Content $workerStateFile -Raw|ConvertFrom-Json
                if(Test-IsalaWorkerState $workerState){$workerHealthy=$true;break}
            }catch{}
        }
    }
    if(-not $workerHealthy){
        $details=""
        if(Test-Path $workerStartupErrorLog){$details=(Get-Content $workerStartupErrorLog -Raw -ErrorAction SilentlyContinue)}
        if([string]::IsNullOrWhiteSpace($details) -and (Test-Path $workerStartupLog)){$details=(Get-Content $workerStartupLog -Raw -ErrorAction SilentlyContinue)}
        throw "The local PowerShell worker did not become healthy. See $workerStartupLog and $workerStartupErrorLog. $details"
    }
}

$workspace = Join-Path $ProjectRoot "training\workspace"
$database = Join-Path $workspace "samples.sqlite3"
$portFile = Join-Path $workspace "labeler-port.txt"
New-Item -ItemType Directory -Path $workspace -Force | Out-Null

if (-not (Test-Path $database)) {
    Write-Warning "No samples.sqlite3 exists yet. First run menu option 2 to collect training crops."
}

# START always rebuilds and recreates the labeler from the current checkout.
# Docker's layer cache keeps unchanged layers fast, while any pulled/edited
# application, template or static file is guaranteed to reach the running UI.
$existingContainerId = Get-LabelerContainerId

# Remove stale port metadata and remove the previous container when one exists.
# Do not call `docker compose rm` unconditionally: Windows PowerShell 5.1 treats
# Compose's harmless "No stopped containers" stderr message as a terminating error.
if (Test-Path $portFile) { Remove-Item $portFile -Force -ErrorAction SilentlyContinue }
if (-not [string]::IsNullOrWhiteSpace($existingContainerId)) {
    Write-Host "Removing previous labeler container..."
    $null = Remove-LabelerContainer -ContainerId $existingContainerId
}

$selectedPort = $null
foreach ($candidate in $PreferredPort..($PreferredPort + 10)) {
    if (Test-LocalPortAvailable -Port $candidate) {
        $selectedPort = $candidate
        break
    }
}
if ($null -eq $selectedPort) {
    throw "No free localhost port was found between $PreferredPort and $($PreferredPort + 10)."
}

$env:ISALA_LABEL_PORT = [string]$selectedPort
$url = "http://127.0.0.1:$selectedPort"

Write-Host "Starting the local exact-label interface..." -ForegroundColor Cyan
Write-Host "Address: $url"
Write-Host "Docker will rebuild/recreate the labeler from the current checkout; unchanged layers may come from cache."
Write-Host ""

# Validate Compose interpolation. Temporarily use Continue because Windows
# PowerShell 5.1 may classify harmless native stderr as a PowerShell error.
$previousPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    & docker compose --profile training config --quiet
    $configExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousPreference
}
if ($configExitCode -ne 0) {
    throw "compose.yaml could not be validated. Run menu option 5 for diagnostics."
}

$previousPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    & docker compose --profile training up --build -d --force-recreate labeler
    $upExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousPreference
}
if ($upExitCode -ne 0) {
    Show-LabelerDiagnostics -ContainerId $null -Port $selectedPort
    throw "The label container could not be built or started."
}

$deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
$ready = $false
$containerId = $null
while ((Get-Date) -lt $deadline) {
    $containerId = Get-LabelerContainerId
    if ([string]::IsNullOrWhiteSpace($containerId)) {
        Start-Sleep -Seconds 2
        continue
    }

    $containerInfo = Get-LabelerContainerInfo -ContainerId $containerId
    $state = Get-LabelerStateSummary -ContainerInfo $containerInfo
    if ($state.Status -in @('exited', 'dead', 'removing')) {
        Show-LabelerDiagnostics -ContainerId $containerId -Port $selectedPort
        throw "The label container stopped before the web interface became ready."
    }

    # A container can be internally healthy while its port is not published to
    # Windows. Verify Docker's actual binding instead of trusting EXPOSE or the
    # internal healthcheck. This catches an isolated/internal Compose network.
    $publishedPort = Get-PublishedLabelerPort -ContainerInfo $containerInfo
    if ($state.Status -eq 'running' -and $null -eq $publishedPort) {
        Show-LabelerDiagnostics -ContainerId $containerId -Port $selectedPort
        throw "Docker started the labeler without a host port mapping. Expected 127.0.0.1:${selectedPort}->8088/tcp. Install the current compose.yaml and recreate the container."
    }
    if ($null -ne $publishedPort -and $publishedPort -ne $selectedPort) {
        $selectedPort = $publishedPort
        $url = "http://127.0.0.1:$selectedPort"
    }

    if (Test-LabelerHealth -Port $selectedPort) {
        $ready = $true
        break
    }

    Start-Sleep -Seconds 2
}

if (-not $ready) {
    Show-LabelerDiagnostics -ContainerId $containerId -Port $selectedPort
    throw "The interface did not become reachable within $StartupTimeoutSeconds seconds."
}

Set-Content -Path $portFile -Value $selectedPort -Encoding ascii
$imageBuild = Get-LabelerImageBuildInfo -ContainerInfo $containerInfo
Write-Host ""
Write-Host "Label interface is ready: $url" -ForegroundColor Green
if ($null -ne $imageBuild) {
    Write-Host ("Laatste labeler-rebuild: {0} (lokaal: {1})" -f $imageBuild.Display, $imageBuild.Image) -ForegroundColor DarkGray
}
Write-Host "Use menu option 4 to stop it and option 5 for diagnostics."

if (-not $NoBrowser) {
    try { Start-Process $url }
    catch { Write-Warning "The browser could not be opened automatically. Open $url manually." }
}
