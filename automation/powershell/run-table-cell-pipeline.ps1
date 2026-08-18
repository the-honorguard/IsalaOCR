. (Join-Path $PSScriptRoot "training-common.ps1")

$ErrorActionPreference = "Stop"
Assert-IsalaActionPreflight -ActionId "53"

# One complete table-model iteration. The individual scripts remain the source
# of truth; this wrapper only sequences them and stops immediately on failure.
# Canonical GT geometry is never changed here. When source-level GT review flags
# are still open, they are explicitly completed before the dataset snapshot is
# built so the normal iterative loop can be: run everything -> review -> repeat.
$oldNested = $env:ISALA_NESTED_PREFLIGHT_APPROVED
try {
    $env:ISALA_NESTED_PREFLIGHT_APPROVED = "1"
    $ContainerWorkspace = Get-IsalaContainerWorkspace
    $HostWorkspace = Get-IsalaHostProjectWorkspace

    Write-Host "Alles laten draaien: open GT-bronnen afronden indien nodig..." -ForegroundColor Cyan
    $gtPython = "from isala_ocr.training.table_cell_ground_truth import list_ground_truth_sources,set_ground_truth_source_review_completed; import sys; w=sys.argv[1]; s=list_ground_truth_sources(w); o=[str(x.get('source_id') or '') for x in s if not bool(x.get('review_completed'))]; [set_ground_truth_source_review_completed(w,i,True) for i in o if i]; print('GT sources marked correct: %d' % len(o))"
    & docker compose --profile training run --rm --build --entrypoint python training-collector -c $gtPython $ContainerWorkspace
    if ($LASTEXITCODE -ne 0) { throw "Canonical GT completion failed." }

    Write-Host "Alles laten draaien: dataset bouwen..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "build-table-cell-dataset.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Table-cell dataset build failed." }

    Write-Host "Alles laten draaien: dataset valideren..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "validate-table-cell-dataset.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Table-cell dataset validation failed." }

    Write-Host "Alles laten draaien: GPU-training..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "train-table-cell-model.ps1") -Device gpu
    if ($LASTEXITCODE -ne 0) { throw "Table-cell detector training failed." }

    Write-Host "Alles laten draaien: model activeren..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "activate-table-cell-model.ps1") -ModelId latest
    if ($LASTEXITCODE -ne 0) { throw "Table-cell model activation failed." }

    $activePath = Join-Path $HostWorkspace "table_cell_models\active.json"
    if (-not (Test-Path -LiteralPath $activePath -PathType Leaf)) {
        throw "Active table-cell model pointer ontbreekt na activatie: $activePath"
    }
    $active = Get-Content -LiteralPath $activePath -Raw | ConvertFrom-Json
    $activeModelId = [string]$active.model_id
    if ([string]::IsNullOrWhiteSpace($activeModelId)) {
        throw "Active table-cell model bevat geen model_id."
    }

    Write-Host ("Alles laten draaien: nieuw actief model uitvoeren ({0})..." -f $activeModelId) -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "collect-training-data.ps1") -TableModelId $activeModelId
    if ($LASTEXITCODE -ne 0) { throw "Nieuwe table-cell modelrun failed." }

    Write-Host "Alles afgerond. Het nieuwe model is getraind, actief en opnieuw uitgevoerd. Open Stap 7 om alleen de afwijkingen te beoordelen." -ForegroundColor Green
}
finally {
    $env:ISALA_NESTED_PREFLIGHT_APPROVED = $oldNested
}
