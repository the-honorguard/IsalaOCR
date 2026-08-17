param(
    [Parameter(Position = 0)]
    [ValidateSet("web","menu","check","repair","action")]
    [string]$Mode = "web",

    [Parameter(Position = 1)]
    [string]$Target = "",

    [Parameter(Position = 2)]
    [string]$Value = ""
)

$ErrorActionPreference = "Stop"
$ProjectRootHint = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
try {
    Get-ChildItem -LiteralPath $ProjectRootHint -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @(".ps1", ".cmd") } |
        Unblock-File -ErrorAction SilentlyContinue
}
catch {
    # START.cmd already uses ExecutionPolicy Bypass. Failure to remove an
    # optional Zone.Identifier must not block the application itself.
}
& (Join-Path $PSScriptRoot "layout-migration.ps1")
. (Join-Path $PSScriptRoot "preflight.ps1")

try {
    switch ($Mode) {
        "web" {
            & (Join-Path $PSScriptRoot "label-training-data.ps1")
        }
        "menu" {
            & (Join-Path $PSScriptRoot "training-menu.ps1")
        }
        "check" {
            if ($Target) {
                $result = Invoke-IsalaPreflight -ActionId $Target -EnsureDocker -SaveReport
            } else {
                $result = Invoke-IsalaPreflight -AllActions -EnsureDocker -SaveReport
            }
            if (-not $result.Passed) { exit 1 }
        }
        "repair" {
            Invoke-IsalaPermissionRepair
        }
        "action" {
            if (-not $Target) { throw "Usage: START.cmd action <pipeline action id>" }
            & (Join-Path $PSScriptRoot "training-menu.ps1") -RunAction $Target -ActionValue $Value
        }
    }
}
catch {
    Write-Host ""
    Write-Host "IsalaOCR failed:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
