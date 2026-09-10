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

$lastFingerprint = Get-WebUiFingerprint
Write-Host "IsalaOCR WebUI watch mode actief." -ForegroundColor Cyan
Write-Host ("Opslaan in application/src, config of Docker-config bouwt de WebUI automatisch opnieuw nadat de workspace {0} seconden stil is geweest." -f $QuietSeconds) -ForegroundColor DarkGray
Write-Host "Stoppen: Ctrl+C · Handmatig opnieuw bouwen: R" -ForegroundColor DarkGray

$pendingFingerprint = $null
$pendingSince = $null

while ($true) {
        Start-Sleep -Milliseconds $PollMilliseconds
        try {
            if (-not [Console]::IsInputRedirected -and [Console]::KeyAvailable) {
                $key = [Console]::ReadKey($true)
                if ($key.Key -eq [ConsoleKey]::R) {
                    Write-Host ""
                    Write-Host "Handmatige WebUI-rebuild gestart..." -ForegroundColor Yellow
                    & (Join-Path $PSScriptRoot "label-training-data.ps1") -NoBrowser -ForceRebuild
                    if ($LASTEXITCODE -ne 0) { throw "label-training-data.ps1 exit code $LASTEXITCODE" }
                    $lastFingerprint = Get-WebUiFingerprint
                    $pendingFingerprint = $null
                    $pendingSince = $null
                    Write-Host "Handmatige rebuild klaar." -ForegroundColor Green
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
            $pendingFingerprint = $fingerprint
            $pendingSince = Get-Date
            Write-Host ("Wijziging gedetecteerd om {0}; wachten tot de workspace {1} seconden stil is..." -f (Get-Date -Format 'HH:mm:ss'), $QuietSeconds) -ForegroundColor DarkYellow
            continue
        }
        if ($null -eq $pendingFingerprint -or $null -eq $pendingSince) { continue }
        if (((Get-Date) - $pendingSince).TotalSeconds -lt $QuietSeconds) { continue }
        $pendingFingerprint = $null
        $pendingSince = $null

        Write-Host ""
        Write-Host ("Workspace is {0} seconden stil; WebUI wordt bijgewerkt om {1}..." -f $QuietSeconds, (Get-Date -Format 'HH:mm:ss')) -ForegroundColor Yellow
        try {
            & (Join-Path $PSScriptRoot "label-training-data.ps1") -NoBrowser
            if ($LASTEXITCODE -ne 0) { throw "label-training-data.ps1 exit code $LASTEXITCODE" }
            Write-Host "WebUI bijgewerkt. Dezelfde URL blijft actief." -ForegroundColor Green
        } catch {
            Write-Host ("Automatische update mislukt: {0}" -f $_.Exception.Message) -ForegroundColor Red
            Write-Host "De watcher blijft actief en probeert opnieuw bij de volgende wijziging." -ForegroundColor DarkGray
        }
}
