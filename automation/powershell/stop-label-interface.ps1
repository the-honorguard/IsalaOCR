$ErrorActionPreference = "Stop"
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}
. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-IsalaActionPreflight -ActionId "3"
. (Join-Path $PSScriptRoot "labeler-common.ps1")
Assert-Docker

Write-Host "Stopping the local exact-label interface..." -ForegroundColor Cyan
$containerId = Get-LabelerContainerId
if ([string]::IsNullOrWhiteSpace($containerId)) {
    Write-Host "No label interface container is running or stopped; nothing to remove." -ForegroundColor Yellow
}
else {
    $removed = Remove-LabelerContainer -ContainerId $containerId
    if ($removed) {
        Write-Host "Label interface container removed." -ForegroundColor Green
    }
}

$portFile = Join-Path $ProjectRoot "training\workspace\labeler-port.txt"
if (Test-Path $portFile) {
    Remove-Item $portFile -Force
}
Write-Host "Label interface stopped." -ForegroundColor Green
