. (Join-Path $PSScriptRoot "training-common.ps1")
. (Join-Path $PSScriptRoot "runtime-preparation.ps1")
Assert-IsalaActionPreflight -ActionId "57"
Assert-Docker
Assert-IsalaRuntimePrepared | Out-Null
$ContainerWorkspace = Get-IsalaContainerWorkspace
Write-Host "Activating full-page table-region detector..." -ForegroundColor Cyan
docker compose --profile training run --rm --build training-collector `
    activate-table-region-model --workspace $ContainerWorkspace --config /app/config/app.yaml
if ($LASTEXITCODE -ne 0) { throw "Table-region model activation failed." }
Write-Host "Active table-region model updated." -ForegroundColor Green
