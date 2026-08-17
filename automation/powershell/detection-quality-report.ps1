. (Join-Path $PSScriptRoot "training-common.ps1")
$ContainerWorkspace = Get-IsalaContainerWorkspace
$HostWorkspace = Get-IsalaHostProjectWorkspace
Assert-IsalaActionPreflight -ActionId "13"
Assert-Docker
Write-Host "Creating Pipeline A detection quality report..."
docker compose --profile training run --rm --build training-collector `
    detection-quality-report --workspace $ContainerWorkspace --config /app/config/app.yaml
if ($LASTEXITCODE -ne 0) { throw "Detection quality report failed." }
