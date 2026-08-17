. (Join-Path $PSScriptRoot "training-common.ps1")

$ErrorActionPreference = "Stop"
Assert-IsalaActionPreflight -ActionId "53"

# The individual actions remain the source of truth. This wrapper only runs
# them in order and stops immediately if a prerequisite or task fails.
$oldNested = $env:ISALA_NESTED_PREFLIGHT_APPROVED
try {
    $env:ISALA_NESTED_PREFLIGHT_APPROVED = "1"
    Write-Host "Stap 6 volledig uitvoeren: dataset bouwen..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "build-table-cell-dataset.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Table-cell dataset build failed." }

    Write-Host "Stap 6 volledig uitvoeren: dataset valideren..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "validate-table-cell-dataset.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Table-cell dataset validation failed." }

    Write-Host "Stap 6 volledig uitvoeren: GPU-training..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "train-table-cell-model.ps1") -Device gpu
    if ($LASTEXITCODE -ne 0) { throw "Table-cell detector training failed." }

    Write-Host "Stap 6 volledig uitvoeren: model activeren..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "activate-table-cell-model.ps1") -ModelId latest
    if ($LASTEXITCODE -ne 0) { throw "Table-cell model activation failed." }
    Write-Host "Stap 6 volledig afgerond. Voer Stap 3 opnieuw uit om het actieve model te meten." -ForegroundColor Green
}
finally {
    $env:ISALA_NESTED_PREFLIGHT_APPROVED = $oldNested
}
