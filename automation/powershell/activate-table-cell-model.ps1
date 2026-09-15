param([string]$ModelId = "latest")
. (Join-Path $PSScriptRoot "training-common.ps1")
. (Join-Path $PSScriptRoot "runtime-preparation.ps1")
Assert-IsalaActionPreflight -ActionId "52"
Assert-Docker
Assert-IsalaRuntimePrepared | Out-Null
$ContainerWorkspace = Get-IsalaContainerWorkspace
Write-Host "Activating table-cell detector: $ModelId" -ForegroundColor Cyan
docker compose --profile training run --rm --build training-collector `
    activate-table-cell-model --workspace $ContainerWorkspace --config /app/config/app.yaml --model-id $ModelId
if ($LASTEXITCODE -ne 0) { throw "Table-cell model activation failed." }
Write-Host "Active table-cell model updated." -ForegroundColor Green
