param(
    [ValidateSet("gpu", "cpu")]
    [string]$Device = "gpu"
)

. (Join-Path $PSScriptRoot "runtime-preparation.ps1")

$ErrorActionPreference = "Stop"
Assert-IsalaActionPreflight -ActionId "60"

# Each invoked action performs its own preflight. Mark the parent check as
# completed so the chained run does not spend time repeating the same checks.
$previousNestedPreflight = $env:ISALA_NESTED_PREFLIGHT_APPROVED
$env:ISALA_NESTED_PREFLIGHT_APPROVED = "1"
try {
    Write-Host "Alles uitvoeren: tabelregio-dataset bouwen..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "build-table-region-dataset.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Tabelregio-dataset bouwen is mislukt." }

    Write-Host ("Alles uitvoeren: tabelregio-detector trainen op {0}..." -f $Device.ToUpperInvariant()) -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "train-table-region-model.ps1") -Device $Device
    if ($LASTEXITCODE -ne 0) { throw "Tabelregio-detectortraining is mislukt." }

    Write-Host "Alles uitvoeren: geslaagd model activeren..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "activate-table-region-model.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Tabelregio-modelactivatie is mislukt." }

    Write-Host "Tabelregio-traject volledig afgerond." -ForegroundColor Green
}
finally {
    $env:ISALA_NESTED_PREFLIGHT_APPROVED = $previousNestedPreflight
}
