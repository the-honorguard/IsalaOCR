param(
    [string]$InputPath = "",
    # A single file's path relative to /input, or __batch__:<id> for a
    # proefpagina batch manifest in the project workspace. Both bypass the
    # mutable input_selection.json and take precedence over $InputPath.
    [string]$InputFile = "",
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
    $InputManifest = ""
    if ($InputFile -match '^__batch__:([a-f0-9]{32})$') {
        $batchId = $Matches[1]
        $InputManifest = "$(Get-IsalaContainerWorkspace)/test_pipeline_batches/$batchId.json"
        $InputPath = Get-IsalaContainerProjectInput
    }
    elseif (-not [string]::IsNullOrWhiteSpace($InputFile)) {
        if ($InputFile -match '(^|[\\/])\.\.([\\/]|$)' -or $InputFile.StartsWith("/") -or $InputFile -match '^[A-Za-z]:') {
            throw "Invalid input file selection: $InputFile"
        }
        $InputPath = "/input/$($InputFile.Replace('\','/'))"
    }
    elseif ([string]::IsNullOrWhiteSpace($InputPath)) { $InputPath = Get-IsalaContainerProjectInput }
    $dockerArguments = @(
        "compose", "--profile", "training", "run", "--rm", "--pull", "never",
        "--entrypoint", "python", "training-collector",
        "-m", "isala_ocr.table_first_cli", "run-application-pipeline",
        "--input", $InputPath, "--workspace", (Get-IsalaContainerWorkspace),
        "--config", "/app/config/app.yaml", "--table-model-id", $TableModelId,
        "--minimum-mapping-confidence", $MinimumMappingConfidence
    )
    if ($InputManifest) { $dockerArguments += @("--input-manifest", $InputManifest) }
    if (-not [string]::IsNullOrWhiteSpace($MappingProfileId)) { $dockerArguments += @("--mapping-profile-id", $MappingProfileId) }
    Write-Host "Running the active DICOM application pipeline..." -ForegroundColor Cyan
    & docker @dockerArguments
    $dockerExitCode = $LASTEXITCODE
    if ($dockerExitCode -eq 137) {
        throw "De inferencecontainer is gestopt met exitcode 137 (SIGKILL; mogelijk te weinig Docker-geheugen). Controleer Docker-events en het taaklog."
    }
    if ($dockerExitCode -ne 0) {
        throw "The complete application pipeline failed (Docker exit code $dockerExitCode). Open the activity log for the exact stage and error."
    }
}
finally {
    Pop-Location
}
