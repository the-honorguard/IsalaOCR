param(
    [string]$SourceId = ""
)

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $ProjectRoot
try {
    . (Join-Path $PSScriptRoot "training-common.ps1")
    . (Join-Path $PSScriptRoot "runtime-preparation.ps1")
    Assert-IsalaActionPreflight -ActionId "21"
    Assert-Docker
    Assert-IsalaRuntimePrepared | Out-Null

    New-Item -ItemType Directory -Force -Path training\workspace, training\registry | Out-Null
    Write-Host "Applying confirmed field mappings and creating ROI crops..."

    $dockerArguments = @(
        "compose",
        "--profile", "training",
        "run", "--rm", "--pull", "never",
        "--entrypoint", "python",
        "training-collector",
        "-m", "isala_ocr.table_first_cli",
        "apply-mappings",
        "--workspace", "/training/workspace",
        "--config", "/app/config/app.yaml"
    )
    if (-not [string]::IsNullOrWhiteSpace($SourceId)) {
        $dockerArguments += @("--source-id", $SourceId)
    }
    & docker @dockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Applying mappings completed with errors. Open STDERR in the activity dock for the Python/Docker error."
    }
}
finally {
    Pop-Location
}
