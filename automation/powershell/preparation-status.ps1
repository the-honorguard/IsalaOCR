$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "training-common.ps1")

$modelsRoot = Join-Path $ProjectRoot "models"
$paddlexRoot = Join-Path $modelsRoot "paddlex"
$trainingRoot = Join-Path $modelsRoot "training"
$checksRoot = Join-Path $modelsRoot "preparation_checks"
$statusPath = Join-Path $modelsRoot "preparation_status.json"
New-Item -ItemType Directory -Force -Path $modelsRoot,$paddlexRoot,$trainingRoot,$checksRoot | Out-Null

$CpuBaseImage = if (-not [string]::IsNullOrWhiteSpace($env:PADDLEX_CPU_IMAGE)) { $env:PADDLEX_CPU_IMAGE } else { "ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlex/paddlex:paddlex3.3.11-paddlepaddle3.2.0-cpu" }
$GpuBaseImage = if (-not [string]::IsNullOrWhiteSpace($env:PADDLEX_GPU_IMAGE)) { $env:PADDLEX_GPU_IMAGE } else { "ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlex/paddlex:paddlex3.3.11-paddlepaddle3.2.0-gpu-cuda11.8-cudnn8.9-trt8.6" }

function Test-FileReady {
    param([Parameter(Mandatory=$true)][string]$Path,[long]$MinimumBytes=1)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try { return ((Get-Item -LiteralPath $Path).Length -ge $MinimumBytes) } catch { return $false }
}
function Get-PreparationImageState {
    param([Parameter(Mandatory=$true)][string]$Image)
    $state = Get-DockerImageState -Image $Image -RetryCount 2 -RetryDelayMilliseconds 250
    return [ordered]@{ image=$Image; present=[bool]$state.Present; id=[string]$state.Id; detail=[string]$state.Detail }
}
function Read-Marker {
    param([Parameter(Mandatory=$true)][string]$Name)
    $path=Join-Path $checksRoot ($Name+".json")
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    try { return (Get-Content -LiteralPath $path -Raw | ConvertFrom-Json) } catch { return $null }
}
function PhaseState {
    param([bool]$Ready,[string]$Detail,[string[]]$Expected=@(),[string]$State="")
    if ([string]::IsNullOrWhiteSpace($State)) { $State = if($Ready){"ready"}else{"missing"} }
    return [ordered]@{ ready=$Ready; state=$State; detail=$Detail; expected=$Expected }
}

# Actual file/model presence.
$inferenceManifest = Join-Path $paddlexRoot "isala_ocr_model_manifest.json"
$localizationManifest = Join-Path $paddlexRoot "isala_localization_model_manifest.json"
$baselineDir = Join-Path $paddlexRoot "official_models\PP-OCRv6_medium_rec"
$baselineMetadataReady = @("inference.json","inference.pdmodel","model.safetensors") | ForEach-Object { Join-Path $baselineDir $_ } | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
$baselineWeightsReady = @(Get-ChildItem -LiteralPath $baselineDir -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "*.pdiparams" -or $_.Name -like "*.safetensors" })
$inferenceReady = (Test-FileReady -Path $inferenceManifest) -and $baselineMetadataReady.Count -gt 0 -and $baselineWeightsReady.Count -gt 0
if ($inferenceReady) {
    try {
        $manifestData = Get-Content -LiteralPath $inferenceManifest -Raw | ConvertFrom-Json
        $required = @($manifestData.required_models)
        if ($required.Count -gt 0) {
            $inferenceReady = (@($required | Where-Object { -not [bool]$_.prepared }).Count -eq 0)
            foreach ($item in $required) {
                $modelName=([string]$item.model).Trim()
                if (-not $inferenceReady) { break }
                if ([string]::IsNullOrWhiteSpace($modelName) -or $modelName -match '(?i)pipeline') { continue }
                if (-not (Test-Path -LiteralPath (Join-Path (Join-Path $paddlexRoot "official_models") $modelName) -PathType Container)) { $inferenceReady=$false; break }
            }
        }
    } catch { $inferenceReady=$false }
}
$localizationReady = Test-FileReady -Path $localizationManifest
if ($localizationReady) {
    try { $loc=Get-Content -LiteralPath $localizationManifest -Raw|ConvertFrom-Json; $localizationReady=([string]$loc.status -eq "prepared" -and [string]$loc.model_name -eq "PicoDet-S") } catch { $localizationReady=$false }
}
$weightPath=Join-Path $trainingRoot "PP-OCRv6_medium_rec_pretrained.pdparams"
$weightReady=Test-FileReady -Path $weightPath -MinimumBytes 1MB
$picodetWeightPath=Join-Path $trainingRoot "PicoDet-S_pretrained.pdparams"
$picodetWeightReady=Test-FileReady -Path $picodetWeightPath -MinimumBytes 1MB

$cpuBase=Get-PreparationImageState -Image $CpuBaseImage
$gpuBase=Get-PreparationImageState -Image $GpuBaseImage
$cpuImage=Get-PreparationImageState -Image (Get-TrainingImageName -Device cpu)
$gpuImage=Get-PreparationImageState -Image (Get-TrainingImageName -Device gpu)
$gpuDetectionImage=Get-PreparationImageState -Image (Get-TrainingImageName -Device gpu-detection)

$inferenceMarker=Read-Marker "inference"
$cpuMarker=Read-Marker "cpu_detection"
$gpuMarker=Read-Marker "gpu_recognition"
$gpuDetectionMarker=Read-Marker "gpu_detection"
$pretrainedMarker=Read-Marker "pretrained"

$inferenceManifestStamp = if (Test-Path -LiteralPath $inferenceManifest -PathType Leaf) { (Get-Item -LiteralPath $inferenceManifest).LastWriteTimeUtc.ToString("o") } else { "" }
$localizationManifestStamp = if (Test-Path -LiteralPath $localizationManifest -PathType Leaf) { (Get-Item -LiteralPath $localizationManifest).LastWriteTimeUtc.ToString("o") } else { "" }
$weightStamp = if ($weightReady) { (Get-Item -LiteralPath $weightPath).LastWriteTimeUtc.ToString("o") } else { "" }
$weightBytes = if ($weightReady) { [long](Get-Item -LiteralPath $weightPath).Length } else { [long]0 }

$inferenceInstalled = $inferenceReady -and $null -ne $inferenceMarker -and [string]$inferenceMarker.manifest_last_write_utc -eq $inferenceManifestStamp
$cpuInstalled = $cpuImage.present -and $localizationReady -and $null -ne $cpuMarker -and [string]$cpuMarker.image_id -eq [string]$cpuImage.id -and [string]$cpuMarker.localization_manifest_last_write_utc -eq $localizationManifestStamp
$gpuInstalled = $gpuImage.present -and $null -ne $gpuMarker -and [string]$gpuMarker.image_id -eq [string]$gpuImage.id
$gpuDetectionInstalled = $gpuDetectionImage.present -and $null -ne $gpuDetectionMarker -and [string]$gpuDetectionMarker.image_id -eq [string]$gpuDetectionImage.id
$pretrainedInstalled = $weightReady -and $null -ne $pretrainedMarker -and [long]$pretrainedMarker.bytes -eq $weightBytes -and [string]$pretrainedMarker.last_write_utc -eq $weightStamp

function InstalledPhase {
    param([bool]$ArtifactPresent,[bool]$Validated,[string]$ReadyDetail,[string]$UncheckedDetail,[string[]]$Expected)
    if ($Validated) { return PhaseState -Ready $true -Detail $ReadyDetail -Expected $Expected }
    if ($ArtifactPresent) { return PhaseState -Ready $false -State "unknown" -Detail $UncheckedDetail -Expected $Expected }
    return PhaseState -Ready $false -State "missing" -Detail "Installatie/build ontbreekt." -Expected $Expected
}

$components=[ordered]@{
    inference=[ordered]@{
        full_action_id="14"; download_action_id="30"; install_action_id="35"; check_action_id="42"
        title="Inference OCR + tabelmodellen"; description="PP-OCRv6 en PP-Structure modelcache voor offline inferentie."
        files=@("PP-OCRv6 detectie + recognition","PP-StructureV3 layout/table/cell models","PP-OCRv6 medium baseline")
        download=(PhaseState -Ready $inferenceReady -Detail $(if($inferenceReady){"Alle vereiste modelbestanden aanwezig."}else{"Modelcache of manifest incompleet."}) -Expected @("models/paddlex/official_models/*","models/paddlex/isala_ocr_model_manifest.json"))
        install=(InstalledPhase -ArtifactPresent $inferenceReady -Validated $inferenceInstalled -ReadyDetail "Offline runtime-validatie geslaagd." -UncheckedDetail "Bestanden aanwezig; offline runtime nog niet gevalideerd." -Expected @("offline model-prep smoke test"))
    }
    cpu_detection=[ordered]@{
        full_action_id="15"; download_action_id="31"; install_action_id="36"; check_action_id="43"
        title="CPU detector / PicoDet-S"; description="CPU training stack en PicoDet-S localization-baseline."
        files=@($CpuBaseImage,"PicoDet-S modelcache","PicoDet-S_pretrained.pdparams")
        download=(PhaseState -Ready ($cpuBase.present -and $picodetWeightReady) -Detail $(if($cpuBase.present -and $picodetWeightReady){"CPU base-image + PicoDet-S trainingsgewicht aanwezig."}elseif(-not $cpuBase.present){"CPU PaddleX base-image ontbreekt."}else{"PicoDet-S trainingsgewicht ontbreekt."}) -Expected @($CpuBaseImage,"models/training/PicoDet-S_pretrained.pdparams"))
        install=(InstalledPhase -ArtifactPresent $cpuImage.present -Validated $cpuInstalled -ReadyDetail "CPU runtime + PicoDet-S validatie geslaagd." -UncheckedDetail $(if($cpuImage.present){"CPU image aanwezig; validatie ontbreekt of is verouderd."}else{"CPU image ontbreekt."}) -Expected @($cpuImage.image,"models/paddlex/isala_localization_model_manifest.json"))
    }
    gpu_recognition=[ordered]@{
        full_action_id="16"; download_action_id="32"; install_action_id="37"; check_action_id="44"
        title="GPU OCR-recognition"; description="NVIDIA recognition-training image zonder PaddleDetection."
        files=@($GpuBaseImage,"PaddlePaddle GPU 3.2.2 + PaddleX 3.7.2")
        download=(PhaseState -Ready $gpuBase.present -Detail $(if($gpuBase.present){"Gedeelde GPU base-image aanwezig."}else{"GPU base-image ontbreekt."}) -Expected @($GpuBaseImage))
        install=(InstalledPhase -ArtifactPresent $gpuImage.present -Validated $gpuInstalled -ReadyDetail "GPU Paddle/CUDA runtime-validatie geslaagd." -UncheckedDetail $(if($gpuImage.present){"GPU recognition image aanwezig; runtime nog niet gevalideerd."}else{"GPU recognition image ontbreekt."}) -Expected @($gpuImage.image))
    }
    gpu_detection=[ordered]@{
        full_action_id="17"; download_action_id="33"; install_action_id="38"; check_action_id="45"
        title="GPU PaddleDetection / PicoDet-S"; description="NVIDIA detector-image met PaddleDetection."
        files=@($GpuBaseImage,"PaddleDetection source/dependencies","PaddlePaddle GPU 3.2.2","PicoDet-S_pretrained.pdparams")
        download=(PhaseState -Ready ($gpuBase.present -and $picodetWeightReady) -Detail $(if($gpuBase.present -and $picodetWeightReady){"GPU base-image + PicoDet-S trainingsgewicht aanwezig."}elseif(-not $gpuBase.present){"GPU base-image ontbreekt."}else{"PicoDet-S trainingsgewicht ontbreekt."}) -Expected @($GpuBaseImage,"models/training/PicoDet-S_pretrained.pdparams"))
        install=(InstalledPhase -ArtifactPresent $gpuDetectionImage.present -Validated $gpuDetectionInstalled -ReadyDetail "GPU PaddleDetection runtime-validatie geslaagd." -UncheckedDetail $(if($gpuDetectionImage.present){"Detector-image aanwezig; PaddleDetection runtimecheck ontbreekt of faalde."}else{"GPU detector-image ontbreekt."}) -Expected @($gpuDetectionImage.image))
    }
    pretrained=[ordered]@{
        full_action_id="18"; download_action_id="34"; install_action_id="39"; check_action_id="46"
        title="PP-OCRv6 pretrained gewicht"; description="Officieel medium recognition-gewicht voor fine-tuning."
        files=@("PP-OCRv6_medium_rec_pretrained.pdparams")
        download=(PhaseState -Ready $weightReady -Detail $(if($weightReady){("Gewicht aanwezig ({0:N1} MiB)." -f ((Get-Item $weightPath).Length/1MB))}else{"Gewicht ontbreekt of is te klein."}) -Expected @("models/training/PP-OCRv6_medium_rec_pretrained.pdparams"))
        install=(InstalledPhase -ArtifactPresent $weightReady -Validated $pretrainedInstalled -ReadyDetail "Offline trainingsbronvalidatie geslaagd." -UncheckedDetail "Gewicht aanwezig; offline trainingsvalidatie nog niet uitgevoerd." -Expected @("training_prepare_manifest.json / offline source discovery"))
    }
}

$allDownloadsReady=(@($components.Values|Where-Object{-not [bool]$_.download.ready}).Count -eq 0)
$allInstallsReady=(@($components.Values|Where-Object{-not [bool]$_.install.ready}).Count -eq 0)

# Inventory is intentionally calculated here, not in the frequently-polled web API.
# This keeps recursive filesystem traversal on the host-side preparation refresh path.
$paddlexFiles = @(Get-ChildItem -LiteralPath $paddlexRoot -Recurse -File -ErrorAction SilentlyContinue)
$trainingFiles = @(Get-ChildItem -LiteralPath $trainingRoot -Recurse -File -ErrorAction SilentlyContinue)
$paddlexBytes = [long](($paddlexFiles | Measure-Object -Property Length -Sum).Sum)
$trainingBytes = [long](($trainingFiles | Measure-Object -Property Length -Sum).Sum)
$inventory = [ordered]@{
    model_file_count = $paddlexFiles.Count
    weight_file_count = $trainingFiles.Count
    model_bytes = ($paddlexBytes + $trainingBytes)
    paddlex_bytes = $paddlexBytes
    training_bytes = $trainingBytes
}

$payload=[ordered]@{
    schema_version="2.0"; checked_at=(Get-Date).ToString("o"); training_image_version=Get-TrainingImageVersion
    all_downloads_ready=$allDownloadsReady; all_installs_ready=$allInstallsReady; all_ready=($allDownloadsReady -and $allInstallsReady)
    inventory=$inventory
    base_images=[ordered]@{cpu=$cpuBase;gpu=$gpuBase}; components=$components
}
[System.IO.File]::WriteAllText($statusPath,($payload|ConvertTo-Json -Depth 12),[System.Text.UTF8Encoding]::new($false))
Write-Host ("Preparation status: downloads={0}, installs={1}" -f $(if($allDownloadsReady){"READY"}else{"INCOMPLETE"}),$(if($allInstallsReady){"READY"}else{"INCOMPLETE"})) -ForegroundColor $(if($payload.all_ready){"Green"}else{"Yellow"})
Write-Host "Status written to: $statusPath"
