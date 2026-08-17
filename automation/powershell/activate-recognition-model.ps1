param(
    [Parameter(Mandatory=$true)][string]$ModelId,
    [double]$MinimumExactMatch = 0.95,
    [switch]$Force
)
. (Join-Path $PSScriptRoot "training-common.ps1")
$ContainerRegistry = Get-IsalaContainerRegistry
Write-Host "[1/4] Activatievoorwaarden controleren..."
Assert-IsalaActionPreflight -ActionId "116"
Assert-Docker
Write-Host "[2/4] Modelmanager voorbereiden..."
$argsList = @(
    "activate-model", "--config", "/app/config/app.yaml",
    "--registry", $ContainerRegistry,
    "--model-root", "/models",
    "--model-id", $ModelId,
    "--minimum-exact-match", $MinimumExactMatch
)
if ($Force) { $argsList += "--force" }
Write-Host "[3/4] Model '$ModelId' activeren..."
docker compose --profile training run --rm --build model-manager @argsList
if ($LASTEXITCODE -ne 0) { throw "Model activation failed." }
Write-Host "[4/4] Activatie voltooid."
Write-Host "Het geselecteerde model staat actief in de modelmap van het huidige project en wordt bij de volgende OCR-run voor dit project gebruikt."
