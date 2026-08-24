[CmdletBinding()]
param(
    [int]$Tail = 250,
    [switch]$ErrorsOnly,
    [switch]$List
)

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LogRoot = Join-Path $ProjectRoot "diagnostics\terminal-logs"
$HandledPath = Join-Path $LogRoot "handled.json"

function Get-IsalaHandledLogMap {
    if (-not (Test-Path -LiteralPath $HandledPath -PathType Leaf)) {
        return [ordered]@{}
    }
    try {
        $payload = Get-Content -LiteralPath $HandledPath -Raw -ErrorAction Stop | ConvertFrom-Json
        $map = [ordered]@{}
        foreach ($property in @($payload.PSObject.Properties)) {
            $map[[string]$property.Name] = $property.Value
        }
        return $map
    }
    catch {
        Write-Warning "Could not read handled log registry: $HandledPath"
        return [ordered]@{}
    }
}

function Set-IsalaLogHandled {
    param(
        [Parameter(Mandatory = $true)][string]$LogPath,
        [string]$Reason = ""
    )
    $resolved = (Resolve-Path -LiteralPath $LogPath -ErrorAction Stop).Path
    $map = Get-IsalaHandledLogMap
    $map[$resolved] = [ordered]@{
        handled_at = (Get-Date).ToString("o")
        reason = $Reason
    }
    $map | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $HandledPath -Encoding UTF8
    Write-Output "Marked handled: $resolved"
}

function Get-IsalaLatestLogPath {
    $latest = Join-Path $LogRoot "latest.log"
    if (Test-Path -LiteralPath $latest -PathType Leaf) { return $latest }
    return Get-ChildItem -LiteralPath $LogRoot -Filter "startup-*.log" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}

function Read-IsalaLatestLogs {
    param(
        [int]$Tail = 250,
        [switch]$ErrorsOnly,
        [switch]$List
    )

    if (-not (Test-Path -LiteralPath $LogRoot -PathType Container)) {
        Write-Output "No IsalaOCR terminal logs found at $LogRoot"
        return
    }

    if ($List) {
        Get-ChildItem -LiteralPath $LogRoot -Filter "*.log" -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object Name, Length, LastWriteTimeUtc, FullName
        return
    }

    $path = Get-IsalaLatestLogPath
    if ([string]::IsNullOrWhiteSpace($path)) {
        Write-Output "No IsalaOCR terminal logs found at $LogRoot"
        return
    }

    $lines = @(Get-Content -LiteralPath $path -ErrorAction Stop)
    $pattern = '(?i)(error|failed|failure|exception|traceback|stale|blocked|timeout|warning)'
    if ($ErrorsOnly) {
        $selected = @($lines | Where-Object { $_ -match $pattern })
    } else {
        $count = [Math]::Max(1, $Tail)
        $selected = @($lines | Select-Object -Last $count)
    }

    Write-Output ("=== IsalaOCR latest terminal log ===`n{0}`n=== matched/output lines: {1} ===" -f $path, $selected.Count)
    $selected
}

function errorlog {
    param(
        [int]$Tail = 250,
        [int]$RunCount = 10,
        [switch]$IncludeHandled,
        [switch]$MarkHandled,
        [string]$LogPath = "",
        [string]$Reason = ""
    )
    if ($MarkHandled) {
        if ([string]::IsNullOrWhiteSpace($LogPath)) {
            $LogPath = Get-IsalaLatestLogPath
        }
        if ([string]::IsNullOrWhiteSpace($LogPath)) {
            Write-Output "No log available to mark handled."
            return
        }
        Set-IsalaLogHandled -LogPath $LogPath -Reason $Reason
        return
    }

    if ([string]::IsNullOrWhiteSpace($LogPath)) {
        $logs = @(Get-ChildItem -LiteralPath $LogRoot -Filter "startup-*.log" -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First ([Math]::Max(1, $RunCount)))
    } else {
        $logs = @(Get-Item -LiteralPath $LogPath -ErrorAction Stop)
    }
    $handled = Get-IsalaHandledLogMap
    if (-not $IncludeHandled) {
        $logs = @($logs | Where-Object { -not $handled.Contains($_.FullName) })
    }
    if ($logs.Count -eq 0) {
        Read-IsalaLatestLogs -Tail $Tail -ErrorsOnly
        return
    }

    $pattern = '(?i)(error|failed|failure|exception|traceback|stale|blocked|timeout|warning)'
    foreach ($log in $logs) {
        $matches = @(Get-Content -LiteralPath $log.FullName -ErrorAction SilentlyContinue |
            Where-Object { $_ -match $pattern } |
            Select-Object -Unique -Last ([Math]::Max(1, $Tail)))
        if ($matches.Count -eq 0) { continue }
        $status = if ($handled.Contains($log.FullName)) { "handled" } else { "new" }
        Write-Output ("=== errorlog [{0}]: {1} ===" -f $status, $log.FullName)
        $matches
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    Read-IsalaLatestLogs -Tail $Tail -ErrorsOnly:$ErrorsOnly -List:$List
}
