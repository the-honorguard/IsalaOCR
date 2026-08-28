param(
    [string]$SourceId = "",
    [string]$Model = "auto"
)

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $ProjectRoot
try {
    Write-Host "Applying the current raster/cell mappings and building the output datablok..."
    $applyArgs = @{}
    if (-not [string]::IsNullOrWhiteSpace($SourceId)) { $applyArgs.SourceId = $SourceId }
    & (Join-Path $PSScriptRoot "apply-mappings.ps1") @applyArgs
    if ($LASTEXITCODE -ne 0) { throw "Applying the current raster/cell mappings failed." }

    Write-Host "Existing Recognition output was reused; no new OCR or crop files were created."
}
finally {
    Pop-Location
}
