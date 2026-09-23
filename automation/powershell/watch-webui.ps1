[CmdletBinding()]
param(
    [int]$PollMilliseconds = 800,
    [int]$QuietSeconds = 30
)

if ($QuietSeconds -lt 0) {
    throw "QuietSeconds moet nul of groter zijn."
}

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$watchRoots = @(
    (Join-Path $projectRoot "application\src\isala_ocr"),
    (Join-Path $projectRoot "application\config"),
    (Join-Path $projectRoot "infrastructure\docker\Dockerfile.labeler"),
    (Join-Path $projectRoot "infrastructure\docker\compose.yaml")
)
$watchExtensions = @('.py', '.html', '.css', '.js', '.yaml', '.yml', '.json')

function Get-WebUiFingerprint {
    $files = foreach ($root in $watchRoots) {
        if (Test-Path -LiteralPath $root -PathType Leaf) {
            Get-Item -LiteralPath $root
        } elseif (Test-Path -LiteralPath $root -PathType Container) {
            Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction SilentlyContinue |
                Where-Object { $watchExtensions -contains $_.Extension.ToLowerInvariant() }
        }
    }
    return (($files | Sort-Object FullName | ForEach-Object {
        "{0}|{1}|{2}" -f $_.FullName, $_.Length, $_.LastWriteTimeUtc.Ticks
    }) -join "`n")
}

# Returns the job id the webworker is currently running, or $null when idle.
# A rebuild via label-training-data.ps1 replaces a worker whose script
# fingerprint is outdated, which kills the running job's process tree.
function Get-ActiveWorkerJobId {
    $workerStateFile = Join-Path $projectRoot "training\workspace\webui\jobs\worker.json"
    if (-not (Test-Path -LiteralPath $workerStateFile -PathType Leaf)) { return $null }
    try {
        $state = Get-Content -LiteralPath $workerStateFile -Raw | ConvertFrom-Json
        if ([string]$state.state -ne "running" -or [string]::IsNullOrWhiteSpace([string]$state.current_job_id)) { return $null }
        $heartbeat = [datetimeoffset]::Parse([string]$state.heartbeat_at)
        if ((([datetimeoffset]::Now) - $heartbeat).TotalSeconds -gt 15) { return $null }
        return [string]$state.current_job_id
    } catch { return $null }
}

# Changes are only detected and reported; the WebUI (and the webworker) is
# never rebuilt automatically because that aborted running jobs. Press R to
# rebuild by hand. -QuietSeconds is still honoured as the settle time before
# a detected change is reported.
$lastFingerprint = Get-WebUiFingerprint
Write-Host "IsalaOCR WebUI watch mode actief (handmatig bijwerken)." -ForegroundColor Cyan
Write-Host "Wijzigingen in application/src, config of Docker-config worden gemeld; de WebUI wordt pas bijgewerkt wanneer je op R drukt." -ForegroundColor DarkGray
Write-Host "Stoppen: Ctrl+C · WebUI bijwerken: R" -ForegroundColor DarkGray

$pendingSince = $null
$confirmUntil = $null

while ($true) {
        Start-Sleep -Milliseconds $PollMilliseconds
        try {
            if (-not [Console]::IsInputRedirected -and [Console]::KeyAvailable) {
                $key = [Console]::ReadKey($true)
                if ($key.Key -eq [ConsoleKey]::R) {
                    $activeJob = Get-ActiveWorkerJobId
                    if ($null -ne $activeJob -and ($null -eq $confirmUntil -or (Get-Date) -gt $confirmUntil)) {
                        $confirmUntil = (Get-Date).AddSeconds(10)
                        Write-Host ""
                        Write-Host ("Let op: taak {0} is nog actief en wordt afgebroken als de worker vervangen moet worden. Druk binnen 10 seconden nogmaals op R om toch bij te werken." -f $activeJob) -ForegroundColor Yellow
                        continue
                    }
                    $confirmUntil = $null
                    Write-Host ""
                    Write-Host "Handmatige WebUI-rebuild gestart..." -ForegroundColor Yellow
                    & (Join-Path $PSScriptRoot "label-training-data.ps1") -NoBrowser -ForceRebuild
                    if ($LASTEXITCODE -ne 0) { throw "label-training-data.ps1 exit code $LASTEXITCODE" }
                    $lastFingerprint = Get-WebUiFingerprint
                    $pendingSince = $null
                    Write-Host "Handmatige rebuild klaar. Dezelfde URL blijft actief." -ForegroundColor Green
                    continue
                }
            }
        } catch {
            Write-Host ("Handmatige WebUI-rebuild mislukt: {0}" -f $_.Exception.Message) -ForegroundColor Red
            continue
        }
        $fingerprint = Get-WebUiFingerprint
        if ($fingerprint -ne $lastFingerprint) {
            $lastFingerprint = $fingerprint
            if ($null -eq $pendingSince) {
                Write-Host ("Wijziging gedetecteerd om {0}." -f (Get-Date -Format 'HH:mm:ss')) -ForegroundColor DarkYellow
            }
            $pendingSince = Get-Date
            continue
        }
        if ($null -eq $pendingSince) { continue }
        if (((Get-Date) - $pendingSince).TotalSeconds -lt $QuietSeconds) { continue }
        $pendingSince = $null
        Write-Host ("Workspace is {0} seconden stil; er staan wijzigingen klaar. Druk op R om de WebUI bij te werken." -f $QuietSeconds) -ForegroundColor Yellow
}
