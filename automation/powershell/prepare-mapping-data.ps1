param([string]$SourceId = "")
. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-IsalaActionPreflight -ActionId "20"
Assert-IsalaDetectionGateOpen
Assert-Docker
$ProjectInput = Get-IsalaContainerProjectInput
Write-Host "Pipeline B: creating semantic OCR blocks and mapping suggestions after the detection gate..."
$args = @("compose","--profile","training","run","--rm","--build","training-collector","collect-mapping","--input",$ProjectInput,"--workspace","/training/workspace","--config","/app/config/app.yaml")
& docker @args
if ($LASTEXITCODE -ne 0) { throw "Mapping preparation failed. The detection gate may be closed." }
