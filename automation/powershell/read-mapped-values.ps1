param(
    [string]$SourceId = "",

    [ValidateNotNullOrEmpty()]
    [string]$Model = "auto"
)

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $ProjectRoot
try {
    . (Join-Path $PSScriptRoot "training-common.ps1")
    . (Join-Path $PSScriptRoot "runtime-preparation.ps1")
    Assert-IsalaActionPreflight -ActionId "22"
    Assert-Docker
    Assert-IsalaRuntimePrepared | Out-Null

    Write-Host "Reading values from the current raster/cell mappings..."
    $dockerArguments = @(
        "compose", "--profile", "training", "run", "--rm", "--pull", "never",
        "--entrypoint", "python",
        "training-collector",
        "-m", "isala_ocr.table_first_cli",
        "read-mapped-values",
        "--workspace", "/training/workspace",
        "--config", "/app/config/app.yaml"
    )
    if (-not [string]::IsNullOrWhiteSpace($SourceId)) {
        $dockerArguments += @("--source-id", $SourceId)
    }
    if (-not [string]::IsNullOrWhiteSpace($Model) -and $Model -ne "auto") {
        $dockerArguments += @("--model", $Model)
    }
    & docker @dockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Mapped value recognition completed with errors. Open STDERR in the activity dock for the Python/Docker error."
    }
}
finally {
    Pop-Location
}
