param(
    [ValidateSet("cpu","gpu")][string]$Device = "gpu",
    [int]$Epochs = 0
)
. (Join-Path $PSScriptRoot "training-common.ps1")
. (Join-Path $PSScriptRoot "runtime-preparation.ps1")
Assert-IsalaActionPreflight -ActionId $(if ($Device -eq "gpu") { "55" } else { "56" })
Assert-Docker
Assert-TrainingImagePrepared -Device $(if ($Device -eq "gpu") { "gpu-detection" } else { "cpu" }) | Out-Null
$ContainerWorkspace = Get-IsalaContainerWorkspace
$HostWorkspace = Get-IsalaHostProjectWorkspace
$Pointer = Join-Path $HostWorkspace "table_region_datasets\latest.txt"
if (-not (Test-Path -LiteralPath $Pointer -PathType Leaf)) { throw "Bouw eerst de tabelregio-dataset in Stap 2." }
$DatasetId = (Get-Content -LiteralPath $Pointer -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($DatasetId)) { throw "Tabelregio-dataset pointer is leeg." }
$ContainerDataset = "$ContainerWorkspace/table_region_datasets/$DatasetId"
$TrainingDevice = if ($Device -eq "gpu") { "gpu-detection" } else { "cpu" }
$Profile = if ($Device -eq "gpu") { "training-gpu-detection" } else { "training" }
$Service = if ($Device -eq "gpu") { "trainer-gpu-detection" } else { "trainer-cpu" }
$RunId = "table-region-run-{0}-PicoDet-S" -f (Get-Date -Format "yyyyMMddTHHmmss")
$HostRun = Join-Path $HostWorkspace ("table_region_runs\{0}" -f $RunId)
$ContainerRun = "$ContainerWorkspace/table_region_runs/$RunId"
New-Item -ItemType Directory -Force -Path $HostRun | Out-Null
Write-Host "Validating full-page table-region dataset..." -ForegroundColor Cyan
docker compose --profile $Profile run --rm --pull never --entrypoint python3 $Service `
    /opt/isala-training/localization_runner.py validate --dataset $ContainerDataset --output $ContainerRun/validation
if ($LASTEXITCODE -ne 0) { throw "Tabelregio-dataset validatie mislukt." }
$TrainArgs = @(
    "/opt/isala-training/localization_runner.py", "train",
    "--dataset", $ContainerDataset, "--output", $ContainerRun, "--device", $Device
)
if ($Epochs -gt 0) { $TrainArgs += @("--epochs", [string]$Epochs) }
Write-Host "Training aparte full-page tabelregio-detector ($Device)..." -ForegroundColor Cyan
docker compose --profile $Profile run --rm --pull never --entrypoint python3 $Service $TrainArgs
if ($LASTEXITCODE -ne 0) { throw "Tabelregio-detector training failed." }
$MetadataPath = Join-Path $HostRun "isala_localization_run.json"
if (-not (Test-Path -LiteralPath $MetadataPath -PathType Leaf)) { throw "Training completed without model metadata." }
$Metadata = Get-Content -LiteralPath $MetadataPath -Raw | ConvertFrom-Json
$ModelDir = [string]$Metadata.inference_dir
if ([string]::IsNullOrWhiteSpace($ModelDir)) { throw "Training metadata has no inference_dir." }
$ModelDir = $ModelDir.Replace($ContainerWorkspace.Replace('\','/'), $HostWorkspace.Replace('\','/'))
New-Item -ItemType Directory -Force -Path (Join-Path $HostWorkspace "table_region_models") | Out-Null
@{ run_id=$RunId; model_id="table-region-$RunId"; dataset_id=$DatasetId; inference_dir=$ModelDir; device=$Device; active=$false } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $HostRun "model.json") -Encoding UTF8
Write-Host "Tabelregio-detector getraind. Activatie/integratie in de detectierun blijft expliciet." -ForegroundColor Green
