$ErrorActionPreference = "Continue"
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}
. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-IsalaActionPreflight -ActionId "3"
. (Join-Path $PSScriptRoot "labeler-common.ps1")
$ErrorActionPreference = "Continue"
Set-Location $ProjectRoot

function Show-DockerStep {
    param(
        [string]$Title,
        [string[]]$Arguments,
        [int]$TimeoutSeconds = 15
    )
    Write-Host ""
    Write-Host $Title -ForegroundColor Yellow
    $result = Invoke-DockerWithTimeout -Arguments $Arguments -TimeoutSeconds $TimeoutSeconds
    if ($result.TimedOut) {
        Write-Host "TIMEOUT after $TimeoutSeconds seconds: docker $($Arguments -join ' ')" -ForegroundColor Red
        return $result
    }
    Write-NativeProcessResult -Result $result -IncludeEmpty
    Write-Host "Exit code: $($result.ExitCode)" -ForegroundColor DarkGray
    return $result
}

Write-Host "=== IsalaOCR labeler diagnostics ===" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"

$dockerVersion = Show-DockerStep -Title "Docker version:" -Arguments @('version') -TimeoutSeconds 15
if ($dockerVersion.TimedOut) {
    Write-Host ""
    Write-Host "Diagnosis:" -ForegroundColor Yellow
    Write-Host "The Docker CLI itself is not returning. This is outside the label web application." -ForegroundColor Red
    Write-Host "1. Press Ctrl+C if another Docker build is still open."
    Write-Host "2. Quit Docker Desktop completely."
    Write-Host "3. Run: wsl --shutdown"
    Write-Host "4. Start Docker Desktop and wait until it reports that the engine is running."
    Write-Host "5. Test in a new PowerShell window: docker version"
    Write-Host "6. Then start menu option 3 again."

    Write-Host ""
    Write-Host "Docker-related Windows processes:" -ForegroundColor Yellow
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ProcessName -match 'docker|com\.docker' } |
        Select-Object ProcessName,Id,CPU,StartTime |
        Format-Table -AutoSize

    Write-Host ""
    Write-Host "Training workspace:" -ForegroundColor Yellow
    $workspace = Join-Path $ProjectRoot "training\workspace"
    Write-Host "Exists: $(Test-Path $workspace)"
    Write-Host "Database exists: $(Test-Path (Join-Path $workspace 'samples.sqlite3'))"
    return
}
if ($dockerVersion.ExitCode -ne 0) {
    Write-Host "Docker returned an error. Restart Docker Desktop before continuing." -ForegroundColor Red
    return
}

$composeValidation = Show-DockerStep -Title "Compose validation:" -Arguments @('compose','--profile','training','config','--quiet') -TimeoutSeconds 20
if ($composeValidation.ExitCode -eq 0 -and -not $composeValidation.TimedOut) {
    Write-Host "compose.yaml is valid." -ForegroundColor Green
}

$containerId = Get-LabelerContainerId
$containerInfo = Get-LabelerContainerInfo -ContainerId $containerId
$port = Get-PublishedLabelerPort -ContainerInfo $containerInfo
$portFile = Join-Path $ProjectRoot "training\workspace\labeler-port.txt"
if ($null -eq $port) { $port = Get-StoredLabelerPort -PortFile $portFile }
if ($null -eq $port) { $port = 8088 }

Write-Host ""
Write-Host "Resolved labeler port: $port" -ForegroundColor Yellow
$env:ISALA_LABEL_PORT = [string]$port

$null = Show-DockerStep -Title "Compose services:" -Arguments @('compose','--profile','training','config','--services') -TimeoutSeconds 20
$null = Show-DockerStep -Title "Container status:" -Arguments @('compose','--profile','training','ps','-a','labeler') -TimeoutSeconds 15

if ($null -ne $containerInfo) {
    $state = Get-LabelerStateSummary -ContainerInfo $containerInfo
    Write-Host ""
    Write-Host "Container state:" -ForegroundColor Yellow
    Write-Host "Container ID: $containerId"
    Write-Host "Status:       $($state.Status)"
    Write-Host "Health:       $($state.Health)"
    Write-Host "Exit code:    $($state.ExitCode)"
    $publishedPort = Get-PublishedLabelerPort -ContainerInfo $containerInfo
    if ($null -ne $publishedPort) {
        Write-Host "Published:    127.0.0.1:$publishedPort -> container 8088"
    }
}
else {
    Write-Host "No labeler container is currently present." -ForegroundColor Yellow
}

$null = Show-DockerStep -Title "Recent logs:" -Arguments @('compose','--profile','training','logs','--tail','250','labeler') -TimeoutSeconds 20

Write-Host ""
Write-Host "Port ${port}:" -ForegroundColor Yellow
Test-NetConnection 127.0.0.1 -Port $port -InformationLevel Detailed |
    Format-List ComputerName,RemoteAddress,RemotePort,TcpTestSucceeded

Write-Host ""
Write-Host "Health endpoint:" -ForegroundColor Yellow
try {
    Invoke-RestMethod "http://127.0.0.1:$port/health" -Method Get -TimeoutSec 5 |
        ConvertTo-Json -Depth 5
}
catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
}

Write-Host ""
Write-Host "Training workspace:" -ForegroundColor Yellow
$workspace = Join-Path $ProjectRoot "training\workspace"
Write-Host "Exists: $(Test-Path $workspace)"
Write-Host "Database exists: $(Test-Path (Join-Path $workspace 'samples.sqlite3'))"
if (Test-Path (Join-Path $workspace "crops")) {
    $cropCount = @(Get-ChildItem (Join-Path $workspace "crops") -Recurse -File -ErrorAction SilentlyContinue).Count
    Write-Host "Crop files: $cropCount"
}
