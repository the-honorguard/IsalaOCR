$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

$requiredNewPaths = @(
    "application\pyproject.toml",
    "automation\powershell\launcher.ps1",
    "infrastructure\docker\compose.yaml",
    "project\VERSION"
)
$missingNewPaths = @($requiredNewPaths | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $ProjectRoot $_) -PathType Leaf)
})
if ($missingNewPaths.Count -gt 0) {
    throw "The v3.4 layout is incomplete; refusing to remove legacy files. Missing: $($missingNewPaths -join ', ')"
}

$removed = New-Object System.Collections.Generic.List[string]
$archived = New-Object System.Collections.Generic.List[string]
$archiveRoot = Join-Path $ProjectRoot "documentation\archive\legacy-root"
New-Item -ItemType Directory -Path $archiveRoot -Force | Out-Null

# Old one-click wrappers are replaced by START.cmd.
foreach ($file in @(Get-ChildItem -LiteralPath $ProjectRoot -File -Filter "*.cmd" -ErrorAction SilentlyContinue)) {
    if ($file.Name -eq "START.cmd") { continue }
    Remove-Item -LiteralPath $file.FullName -Force
    $removed.Add($file.Name)
}

# Preserve legacy documentation for auditability, but keep it out of the root.
$legacyDocuments = @(
    "README.md", "ARCHITECTURE.md", "CHANGELOG.md", "DOCKER_CACHE_UPDATE.md",
    "DYNAMIC_LOCATOR_TEST_REPORT.md", "INFERENCE_MODEL_PREP_FIX.md",
    "INPUT_PREFLIGHT_UPDATE.md", "MIGRATION.md", "PADDLEX_RUNTIME_CACHE_FIX.md",
    "SECURITY.md", "START_HERE.md", "TEST_REPORT.md", "TRAINING_PIPELINE.md",
    "UPGRADE_README.md", "DATABASE_MIGRATION_HOTFIX_README.txt",
    "DOCKER_PREFLIGHT_HOTFIX_README.txt"
)
$legacyDocuments += @(Get-ChildItem -LiteralPath $ProjectRoot -File -Filter "RELEASE_NOTES_*.md" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)
foreach ($name in ($legacyDocuments | Select-Object -Unique)) {
    $source = Join-Path $ProjectRoot $name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { continue }
    $destination = Join-Path $archiveRoot $name
    if (Test-Path -LiteralPath $destination) {
        Remove-Item -LiteralPath $source -Force
    } else {
        Move-Item -LiteralPath $source -Destination $destination
    }
    $archived.Add($name)
}

# Preserve ignore rules for an existing Git worktree without keeping another
# loose file in the project root. Git reads .git/info/exclude like a local
# .gitignore; the block is idempotent and is not committed.
$gitInfo = Join-Path $ProjectRoot ".git\info"
$ignoreTemplate = Join-Path $ProjectRoot "project\gitignore.template"
if ((Test-Path -LiteralPath $gitInfo -PathType Container) -and
    (Test-Path -LiteralPath $ignoreTemplate -PathType Leaf)) {
    $excludePath = Join-Path $gitInfo "exclude"
    $marker = "# BEGIN IsalaOCR managed excludes"
    $existing = if (Test-Path -LiteralPath $excludePath) { Get-Content -LiteralPath $excludePath -Raw } else { "" }
    if ($existing -notmatch [regex]::Escape($marker)) {
        $block = @(
            "",
            $marker,
            (Get-Content -LiteralPath $ignoreTemplate -Raw).TrimEnd(),
            "# END IsalaOCR managed excludes",
            ""
        ) -join [Environment]::NewLine
        Add-Content -LiteralPath $excludePath -Value $block -Encoding UTF8
    }
}

# These files are generated/source duplicates superseded by the grouped layout.
$legacyFiles = @(
    ".dockerignore", ".env.example",
    "Dockerfile", "Dockerfile.labeler", "Dockerfile.training", "docker-compose.yml",
    "pyproject.toml", "requirements-runtime.txt", "requirements-cpu.txt",
    "requirements-dev.txt", "VERSION", "TRAINING_IMAGE_VERSION", "PACKAGE_MANIFEST.json"
)
foreach ($name in $legacyFiles) {
    $path = Join-Path $ProjectRoot $name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Remove-Item -LiteralPath $path -Force
        $removed.Add($name)
    }
}

# Remove only known legacy code/cache directories. User data directories are never touched.
foreach ($name in @("scripts", "src", "config", "schemas", "training_runtime", ".pytest_cache")) {
    $path = Join-Path $ProjectRoot $name
    if (Test-Path -LiteralPath $path -PathType Container) {
        Remove-Item -LiteralPath $path -Recurse -Force
        $removed.Add($name + "\")
    }
}

if ($removed.Count -gt 0 -or $archived.Count -gt 0) {
    Write-Host "Legacy project layout cleaned." -ForegroundColor DarkCyan
    if ($removed.Count -gt 0) { Write-Host ("Removed superseded items: " + ($removed -join ", ")) -ForegroundColor DarkGray }
    if ($archived.Count -gt 0) { Write-Host ("Archived old documents: " + ($archived -join ", ")) -ForegroundColor DarkGray }
}
