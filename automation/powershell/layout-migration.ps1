$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

# This script is intentionally audit-only. Startup must never delete, move or
# rewrite user/project files. Legacy layout cleanup is now a manual decision.
$requiredPaths = @(
    "application\pyproject.toml",
    "automation\powershell\launcher.ps1",
    "infrastructure\docker\compose.yaml",
    "project\VERSION"
)
$missing = @($requiredPaths | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $ProjectRoot $_) -PathType Leaf)
})
if ($missing.Count -gt 0) {
    Write-Warning ("Project layout check: required paths missing: " + ($missing -join ", "))
    return
}

$legacyFiles = @(
    ".dockerignore", ".env.example", "Dockerfile", "Dockerfile.labeler",
    "Dockerfile.training", "docker-compose.yml", "pyproject.toml",
    "requirements-runtime.txt", "requirements-cpu.txt", "requirements-dev.txt",
    "VERSION", "TRAINING_IMAGE_VERSION", "PACKAGE_MANIFEST.json"
)
$legacyDirectories = @("scripts", "src", "config", "schemas", "training_runtime", ".pytest_cache")
$legacyCmds = @(Get-ChildItem -LiteralPath $ProjectRoot -File -Filter "*.cmd" -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne "START.cmd" -and $_.Name -ne "run.cmd" } |
    Select-Object -ExpandProperty Name)
$presentFiles = @($legacyFiles | Where-Object { Test-Path -LiteralPath (Join-Path $ProjectRoot $_) -PathType Leaf })
$presentDirectories = @($legacyDirectories | Where-Object { Test-Path -LiteralPath (Join-Path $ProjectRoot $_) -PathType Container })

$findings = @($legacyCmds + $presentFiles + ($presentDirectories | ForEach-Object { "$_\" }))
if ($findings.Count -gt 0) {
    Write-Host "Legacy layout items detected (audit only; nothing was changed):" -ForegroundColor Yellow
    $findings | ForEach-Object { Write-Host ("  - " + $_) -ForegroundColor DarkGray }
}
