param(
    # Optional overrides for the dynamic hard-example replay policy
    # (table_hard_negative_policy.py). Leave at 0 to keep the built-in
    # defaults (budget ratio 1.50, max replay weight 3). Lower the ratio
    # when hard-example duplicates are dominating the training mix (e.g.
    # 0.5-0.75); set the max weight to 1 to disable replay entirely.
    [double]$ReplayBudgetRatio = 0,
    [int]$ReplayMaxWeight = 0
)
. (Join-Path $PSScriptRoot "training-common.ps1")
. (Join-Path $PSScriptRoot "runtime-preparation.ps1")
Assert-IsalaActionPreflight -ActionId "48"
Assert-Docker
Assert-IsalaRuntimePrepared | Out-Null
$ContainerWorkspace = Get-IsalaContainerWorkspace
$HostWorkspace = Get-IsalaHostProjectWorkspace
New-Item -ItemType Directory -Force -Path $HostWorkspace | Out-Null
$oldReplayBudgetRatio = $env:ISALA_TABLE_REPLAY_BUDGET_RATIO
$oldReplayMaxWeight = $env:ISALA_TABLE_REPLAY_MAX_WEIGHT
try {
    if ($ReplayBudgetRatio -gt 0) {
        $env:ISALA_TABLE_REPLAY_BUDGET_RATIO = [string]$ReplayBudgetRatio
        Write-Host "Hard-example replay budget ratio override: $ReplayBudgetRatio" -ForegroundColor Cyan
    }
    if ($ReplayMaxWeight -gt 0) {
        $env:ISALA_TABLE_REPLAY_MAX_WEIGHT = [string]$ReplayMaxWeight
        Write-Host "Hard-example replay max weight override: $ReplayMaxWeight" -ForegroundColor Cyan
    }
    Write-Host "Building table-cell COCO dataset from completed table reviews..." -ForegroundColor Cyan
    docker compose --profile training run --rm --build dataset-builder `
        build-table-cell-dataset --workspace $ContainerWorkspace --config /app/config/app.yaml
    if ($LASTEXITCODE -ne 0) { throw "Table-cell dataset build failed." }
}
finally {
    $env:ISALA_TABLE_REPLAY_BUDGET_RATIO = $oldReplayBudgetRatio
    $env:ISALA_TABLE_REPLAY_MAX_WEIGHT = $oldReplayMaxWeight
}
