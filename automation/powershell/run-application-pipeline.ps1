param(
    [string]$InputPath = "",
    [string]$TableModelId = "active",
    [string]$MappingProfileId = "",
    [string]$MinimumMappingConfidence = "0.90"
)

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $ProjectRoot
try {
    . (Join-Path $PSScriptRoot "training-common.ps1")
    . (Join-Path $PSScriptRoot "runtime-preparation.ps1")
    Assert-IsalaActionPreflight -ActionId "61"
    Assert-Docker
    Assert-IsalaRuntimePrepared | Out-Null
    if ([string]::IsNullOrWhiteSpace($InputPath)) { $InputPath = Get-IsalaContainerProjectInput }
    $dockerArguments = @(
        "compose", "--profile", "training", "run", "--rm", "--pull", "never",
        "--entrypoint", "python", "training-collector",
        "-m", "isala_ocr.table_first_cli", "run-application-pipeline",
        "--input", $InputPath, "--workspace", (Get-IsalaContainerWorkspace),
        "--config", "/app/config/app.yaml", "--table-model-id", $TableModelId,
        "--minimum-mapping-confidence", $MinimumMappingConfidence
    )
    if (-not [string]::IsNullOrWhiteSpace($MappingProfileId)) { $dockerArguments += @("--mapping-profile-id", $MappingProfileId) }
    Write-Host "Running the active DICOM application pipeline..." -ForegroundColor Cyan
    & docker @dockerArguments
    if ($LASTEXITCODE -ne 0) { throw "The complete application pipeline failed. Open the activity log for the exact stage and error." }
}
finally {
    Pop-Location
}
