param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"
$removed = New-Object System.Collections.Generic.List[string]

function Remove-IsalaTransientPath {
    param([Parameter(Mandatory=$true)][string]$Path)
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        $removed.Add((Resolve-Path -LiteralPath (Split-Path $Path -Parent)).Path + "\" + (Split-Path $Path -Leaf))
    }
}

# Only disposable/interrupted-write artifacts are removed. DICOMs, crops,
# labels, datasets, runs, registered models and the active model are preserved.
Remove-IsalaTransientPath (Join-Path $ProjectRoot ("models\projects\{0}\active-recognition.new" -f (Get-IsalaActiveProjectId)))

$roots = @(
    (Join-Path $ProjectRoot "models"),
    (Join-Path $ProjectRoot "training\workspace\webui\jobs")
)
foreach ($root in $roots) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    Get-ChildItem -LiteralPath $root -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '\.(part|tmp|partial)$' -or $_.Name -like '*.tmp.*' } |
        ForEach-Object {
            $path = $_.FullName
            Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
            if (-not (Test-Path -LiteralPath $path)) { $removed.Add($path) }
        }
}

if ($removed.Count -gt 0) {
    Write-Host "Safe housekeeping removed $($removed.Count) transient artifact(s)."
    foreach ($item in $removed) { Write-Host "  - $item" }
} else {
    Write-Host "Safe housekeeping: no stale transient artifacts found."
}
