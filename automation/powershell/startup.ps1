[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LogRoot = Join-Path $ProjectRoot "diagnostics\terminal-logs"
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $LogRoot ("startup-{0}-{1}.log" -f $stamp, $PID)
$latestPath = Join-Path $LogRoot "latest.log"
$exitCode = 0
$transcriptStarted = $false

try {
    Start-Transcript -Path $logPath -Force | Out-Null
    $transcriptStarted = $true
    Write-Host "IsalaOCR startup log: $logPath"
    Write-Host "Started: $(Get-Date -Format o)"
    Write-Host "Project root: $ProjectRoot"

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git is not available in PATH. Startup aborted."
    }

    Write-Host "Updating IsalaOCR from Git..." -ForegroundColor Cyan
    & git -C $ProjectRoot pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        throw "Git pull failed. Startup aborted to avoid running stale code."
    }

    Write-Host "Starting launcher..." -ForegroundColor Cyan
    # PowerShell can materialize an empty ValueFromRemainingArguments array as
    # one empty string. Do not forward that value: launcher.ps1's Mode has a
    # ValidateSet and an empty argument is not the same as the default web mode.
    $launcherPath = Join-Path $PSScriptRoot "launcher.ps1"
    if ($null -eq $Arguments -or $Arguments.Count -eq 0 -or
        ($Arguments.Count -eq 1 -and [string]::IsNullOrWhiteSpace($Arguments[0]))) {
        & $launcherPath
    } else {
        & $launcherPath @Arguments
    }
    $exitCode = $LASTEXITCODE
}
catch {
    $exitCode = 1
    Write-Host "IsalaOCR failed: $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if ($transcriptStarted) {
        Write-Host "Finished: $(Get-Date -Format o)"
        Stop-Transcript | Out-Null
    }
    if (Test-Path -LiteralPath $logPath -PathType Leaf) {
        Copy-Item -LiteralPath $logPath -Destination $latestPath -Force
        Write-Host "Latest startup log: $latestPath"
    }
}

exit $exitCode
