param(
    [Parameter(Position = 0)]
    [ValidateSet("web","menu","check","repair","action")]
    [string]$Mode = "web",

    [Parameter(Position = 1)]
    [string]$Target = "",

    [Parameter(Position = 2)]
    [string]$Value = "",

    # webui-worker.ps1 appends action-specific named flags (e.g. -StartFrom,
    # -TableModelId) directly onto this script's command line for actions
    # whose extra value doesn't fit the single positional $Value slot above.
    # Without ValueFromRemainingArguments those flags don't match any
    # parameter declared here and PowerShell rejects the whole invocation
    # before "action" mode below ever runs - forward them to
    # training-menu.ps1 untouched instead.
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Extra = @()
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
            # Array-splatting (@Extra) binds its elements strictly by
            # position, not by name - it does not re-parse "-Flag" tokens the
            # way typing them directly would. Rebuild the recognized
            # "-Name value" pairs as a hashtable instead: splatting a
            # hashtable (@extraParams) is what actually restores named-
            # parameter binding on training-menu.ps1.
            $extraParams = @{}
            for ($i = 0; $i -lt $Extra.Count; $i += 2) {
                $flagName = [string]$Extra[$i]
                if ($flagName.StartsWith("-")) {
                    $extraParams[$flagName.Substring(1)] = if ($i + 1 -lt $Extra.Count) { $Extra[$i + 1] } else { $true }
                }
            }
            & (Join-Path $PSScriptRoot "training-menu.ps1") -RunAction $Target -ActionValue $Value @extraParams
        }
    }
}
catch {
    Write-Host ""
    Write-Host "IsalaOCR failed:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
