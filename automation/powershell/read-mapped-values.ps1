param(
    [string]$SourceId = "",

    [ValidateNotNullOrEmpty()]
    [string]$Model = "auto"
)

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $ProjectRoot
try {
    . (Join-Path $PSScriptRoot "training-common.ps1")
    Assert-IsalaActionPreflight -ActionId "22"
Assert-IsalaDetectionGateOpen
    Assert-Docker

    Write-Host "Reading values from approved mapped ROI crops..."
    $dockerArguments = @(
        "compose", "--profile", "training", "run", "--rm", "--build",
        "training-collector", "read-mapped-values",
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
        throw "Mapped value recognition completed with errors. Review the console output."
    }
}
finally {
    Pop-Location
}
