param(
    [ValidateSet("all","inference","cpu-detection","gpu-recognition","gpu-detection","pretrained")]
    [string]$Component = "all",
    [ValidateSet("full","download","install","check")]
    [string]$Phase = "full",
    [string]$PreflightActionId = "1"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "training-common.ps1")

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$CoreScript = Join-Path $PSScriptRoot "prepare-training-core.ps1"
$StatusScript = Join-Path $PSScriptRoot "preparation-status.ps1"
$StatusPath = Join-Path $ProjectRoot "models\preparation_status.json"

if (-not (Test-Path -LiteralPath $CoreScript -PathType Leaf)) {
    throw "Preparation core is missing: $CoreScript"
}

function Invoke-PreparationCore {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$RequestedPhase
    )
    & $CoreScript -Component $Name -Phase $RequestedPhase -PreflightActionId $PreflightActionId
}

function Get-PreparationSnapshot {
    try {
        & $StatusScript *> $null
    }
    catch {
        throw "Preparation inventory failed: $($_.Exception.Message)"
    }
    if (-not (Test-Path -LiteralPath $StatusPath -PathType Leaf)) {
        throw "Preparation status was not written: $StatusPath"
    }
    try {
        return (Get-Content -LiteralPath $StatusPath -Raw | ConvertFrom-Json)
    }
    catch {
        throw "Preparation status is unreadable: $($_.Exception.Message)"
    }
}

function Get-PreparationComponentState {
    param(
        [Parameter(Mandatory=$true)]$Snapshot,
        [Parameter(Mandatory=$true)][string]$Name
    )
    $key = $Name -replace '-', '_'
    $property = $Snapshot.components.PSObject.Properties[$key]
    if ($null -eq $property) {
        throw "Preparation status has no component '$key'."
    }
    return $property.Value
}

function Write-PreparationSkip {
    param([Parameter(Mandatory=$true)][string]$Name,[string]$Reason="ready")
    Write-Host ("[SKIP] {0}: {1}; no download/build required." -f $Name,$Reason) -ForegroundColor DarkGreen
}

# Granular maintenance actions keep their established behaviour. Only the
# normal Step 1 path (all/full) is idempotent and state-driven.
if ($Component -ne "all" -or $Phase -ne "full") {
    Invoke-PreparationCore -Name $Component -RequestedPhase $Phase
    return
}

Assert-IsalaActionPreflight -ActionId $PreflightActionId
Assert-Docker

Write-Host "" 
Write-Host "Smart preparation: inventory first, then repair only missing/stale components." -ForegroundColor Cyan
$snapshot = Get-PreparationSnapshot
if ([bool]$snapshot.all_ready) {
    Write-Host "Preparation is already complete. Nothing to download, build or revalidate." -ForegroundColor Green
    return
}

$components = @("inference","cpu-detection","gpu-recognition","gpu-detection","pretrained")
foreach ($name in $components) {
    $state = Get-PreparationComponentState -Snapshot $snapshot -Name $name
    if ([bool]$state.install.ready) {
        Write-PreparationSkip -Name $name -Reason "validated READY"
        continue
    }

    if (-not [bool]$state.download.ready) {
        Write-Host ("[REPAIR] {0}: required download/cache artifact is missing." -f $name) -ForegroundColor Cyan
        Invoke-PreparationCore -Name $name -RequestedPhase "download"
        $snapshot = Get-PreparationSnapshot
        $state = Get-PreparationComponentState -Snapshot $snapshot -Name $name
    }
    else {
        Write-PreparationSkip -Name $name -Reason "downloads already READY"
    }

    if ([bool]$state.install.ready) {
        Write-PreparationSkip -Name $name -Reason "became READY after download refresh"
        continue
    }

    $installState = ([string]$state.install.state).Trim().ToLowerInvariant()
    if ($installState -eq "unknown") {
        Write-Host ("[CHECK] {0}: artifact/image exists; validating it without rebuilding." -f $name) -ForegroundColor Cyan
        $checkSucceeded = $false
        try {
            Invoke-PreparationCore -Name $name -RequestedPhase "check"
            $snapshot = Get-PreparationSnapshot
            $state = Get-PreparationComponentState -Snapshot $snapshot -Name $name
            $checkSucceeded = [bool]$state.install.ready
        }
        catch {
            Write-Warning ("Existing {0} artifact failed validation: {1}" -f $name,$_.Exception.Message)
        }
        if ($checkSucceeded) {
            Write-PreparationSkip -Name $name -Reason "existing artifact validated successfully"
            continue
        }
        Write-Host ("[REPAIR] {0}: validation did not restore readiness; rebuilding only this component." -f $name) -ForegroundColor Yellow
    }
    else {
        Write-Host ("[REPAIR] {0}: install state is '{1}'; building/installing only this component." -f $name,$installState) -ForegroundColor Cyan
    }

    Invoke-PreparationCore -Name $name -RequestedPhase "install"
    Invoke-PreparationCore -Name $name -RequestedPhase "check"
    $snapshot = Get-PreparationSnapshot
    $state = Get-PreparationComponentState -Snapshot $snapshot -Name $name
    if (-not [bool]$state.install.ready) {
        throw "Preparation component '$name' is still not READY after repair."
    }
}

$final = Get-PreparationSnapshot
if (-not [bool]$final.all_ready) {
    $notReady = @(
        $final.components.PSObject.Properties |
            Where-Object { -not [bool]$_.Value.install.ready } |
            Select-Object -ExpandProperty Name
    )
    throw ("Preparation finished, but these components are not READY: " + ($notReady -join ', '))
}

Write-Host "Preparation complete: all required components are READY." -ForegroundColor Green
