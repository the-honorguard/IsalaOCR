. (Join-Path $PSScriptRoot "training-common.ps1")
$ContainerWorkspace = Get-IsalaContainerWorkspace
$HostWorkspace = Get-IsalaHostProjectWorkspace
Assert-IsalaActionPreflight -ActionId "5"
Assert-Docker
New-Item -ItemType Directory -Force -Path $HostWorkspace | Out-Null
Write-Host "Building Pipeline A COCO localization dataset from reviewed detection annotations..."
docker compose --profile training run --rm --build dataset-builder `
    build-localization-dataset --workspace $ContainerWorkspace --config /app/config/app.yaml
if ($LASTEXITCODE -ne 0) { throw "Localization dataset build failed." }
