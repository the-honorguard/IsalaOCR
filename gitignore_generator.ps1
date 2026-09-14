param(
    [string]$Root = ".",
    [int]$LargeFileMB = 20
)

$ErrorActionPreference = "Stop"

# ============================================================
# HELPERS - Windows PowerShell 5.1 compatible
# ============================================================

function Get-RelativePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BasePath,

        [Parameter(Mandatory = $true)]
        [string]$TargetPath
    )

    $baseFull = [System.IO.Path]::GetFullPath($BasePath)
    $targetFull = [System.IO.Path]::GetFullPath($TargetPath)

    if (-not $baseFull.EndsWith("\")) {
        $baseFull += "\"
    }

    $baseUri = New-Object System.Uri($baseFull)
    $targetUri = New-Object System.Uri($targetFull)

    $relativeUri = $baseUri.MakeRelativeUri($targetUri)
    $relativePath = [System.Uri]::UnescapeDataString($relativeUri.ToString())

    return ($relativePath -replace '/', '\')
}


function Convert-ToGitPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return ($Path -replace '\\', '/')
}


function Format-FileSize {
    param(
        [long]$Bytes
    )

    if ($Bytes -ge 1TB) {
        return "{0:N2} TB" -f ($Bytes / 1TB)
    }

    if ($Bytes -ge 1GB) {
        return "{0:N2} GB" -f ($Bytes / 1GB)
    }

    if ($Bytes -ge 1MB) {
        return "{0:N2} MB" -f ($Bytes / 1MB)
    }

    if ($Bytes -ge 1KB) {
        return "{0:N2} KB" -f ($Bytes / 1KB)
    }

    return "$Bytes bytes"
}


function Add-UniqueLine {
    param(
        [System.Collections.ArrayList]$List,
        [string]$Line
    )

    if ([string]::IsNullOrWhiteSpace($Line)) {
        return
    }

    if (-not $List.Contains($Line)) {
        [void]$List.Add($Line)
    }
}


function Test-ModelFile {
    param(
        [System.IO.FileInfo]$File
    )

    $extension = $File.Extension.ToLowerInvariant()
    $name = $File.Name.ToLowerInvariant()

    $ModelExtensions = @(
        ".pt",
        ".pth",
        ".onnx",
        ".pdparams",
        ".pdmodel",
        ".pdiparams",
        ".pdopt",
        ".pdstates",
        ".ckpt",
        ".safetensors",
        ".engine",
        ".tflite",
        ".pb",
        ".h5",
        ".keras",
        ".weights"
    )

    if ($ModelExtensions -contains $extension) {
        return $true
    }

    # Bekende modelbestandsnamen die niet altijd een herkenbare extensie hebben
    $KnownModelNames = @(
        "model",
        "model.bin",
        "pytorch_model.bin",
        "tf_model.h5",
        "saved_model.pb"
    )

    if ($KnownModelNames -contains $name) {
        return $true
    }

    return $false
}


function Test-ModelDirectoryName {
    param(
        [string]$Name
    )

    $nameLower = $Name.ToLowerInvariant()

    $ModelDirectoryNames = @(
        "model",
        "models",
        "weights",
        "weight",
        "checkpoint",
        "checkpoints",
        "best_accuracy",
        "best_model",
        "inference",
        "inference_model",
        "export",
        "exports",
        "official_models",
        "pretrained",
        "pretrained_models"
    )

    return ($ModelDirectoryNames -contains $nameLower)
}


# ============================================================
# INITIALISATIE
# ============================================================

$Root = (Resolve-Path $Root).Path

$GitIgnorePath = Join-Path $Root ".gitignore"
$ReportPath = Join-Path $Root "gitignore-scan-report.txt"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " IsalaOCR Git repository scanner" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Project: $Root"
Write-Host "Grote bestanden vanaf: $LargeFileMB MB"
Write-Host ""


# ============================================================
# ALLE BESTANDEN EN MAPPEN INVENTARISEREN
# ============================================================

Write-Host "Bestanden inventariseren..." -ForegroundColor Cyan

$AllFiles = @(
    Get-ChildItem `
        -Path $Root `
        -Recurse `
        -Force `
        -File `
        -ErrorAction SilentlyContinue |
    Where-Object {
        $_.FullName -notmatch '[\\/]\.git([\\/]|$)'
    }
)

Write-Host ("  {0:N0} bestanden gevonden" -f $AllFiles.Count) -ForegroundColor Green


Write-Host "Mappen inventariseren..." -ForegroundColor Cyan

$AllDirs = @(
    Get-ChildItem `
        -Path $Root `
        -Recurse `
        -Force `
        -Directory `
        -ErrorAction SilentlyContinue |
    Where-Object {
        $_.FullName -notmatch '[\\/]\.git([\\/]|$)'
    }
)

Write-Host ("  {0:N0} mappen gevonden" -f $AllDirs.Count) -ForegroundColor Green
Write-Host ""


# ============================================================
# MAPGROOTTES BEREKENEN
# ============================================================

Write-Host "Mapgroottes berekenen..." -ForegroundColor Cyan

$DirectorySizes = @{}

foreach ($file in $AllFiles) {

    $directory = $file.Directory

    while ($null -ne $directory) {

        $path = $directory.FullName

        if (-not $path.StartsWith(
            $Root,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            break
        }

        if (-not $DirectorySizes.ContainsKey($path)) {
            $DirectorySizes[$path] = [long]0
        }

        $DirectorySizes[$path] += [long]$file.Length

        if ($path -eq $Root) {
            break
        }

        $directory = $directory.Parent
    }
}

Write-Host "  Mapgroottes berekend" -ForegroundColor Green
Write-Host ""


# ============================================================
# MODELBESTANDEN AUTOMATISCH DETECTEREN
# ============================================================

Write-Host "Modellen detecteren..." -ForegroundColor Cyan

$ModelFiles = New-Object System.Collections.ArrayList
$ModelFileRules = New-Object System.Collections.ArrayList
$ModelDirectoryRules = New-Object System.Collections.ArrayList

foreach ($file in $AllFiles) {

    if (-not (Test-ModelFile -File $file)) {
        continue
    }

    [void]$ModelFiles.Add($file)

    # --------------------------------------------------------
    # Exact modelbestand toevoegen
    # --------------------------------------------------------

    $relativeFile = Get-RelativePath `
        -BasePath $Root `
        -TargetPath $file.FullName

    $relativeFile = Convert-ToGitPath $relativeFile

    Add-UniqueLine `
        -List $ModelFileRules `
        -Line $relativeFile


    # --------------------------------------------------------
    # Bepalen of de hele modeldirectory mag worden genegeerd
    # --------------------------------------------------------

    $currentDirectory = $file.Directory

    if ($null -eq $currentDirectory) {
        continue
    }

    $selectedModelDirectory = $null

    while ($null -ne $currentDirectory) {

        if ($currentDirectory.FullName -eq $Root) {
            break
        }

        $relativeDirectory = Get-RelativePath `
            -BasePath $Root `
            -TargetPath $currentDirectory.FullName

        $relativeDirectoryGit = Convert-ToGitPath $relativeDirectory

        $directoryNameLooksLikeModel = Test-ModelDirectoryName `
            -Name $currentDirectory.Name

        $isTrainingRun = (
            $relativeDirectoryGit -match '^training/workspace/runs/' -or
            $relativeDirectoryGit -match '^training/workspace/projects/.+/table_cell_runs/' -or
            $relativeDirectoryGit -match '/checkpoints?(/|$)' -or
            $relativeDirectoryGit -match '/models?(/|$)' -or
            $relativeDirectoryGit -match '/weights?(/|$)' -or
            $relativeDirectoryGit -match '/best_accuracy(/|$)' -or
            $relativeDirectoryGit -match '/best_model(/|$)' -or
            $relativeDirectoryGit -match '/official_models(/|$)'
        )

        if ($directoryNameLooksLikeModel -or $isTrainingRun) {
            $selectedModelDirectory = $currentDirectory
        }

        # Nooit automatisch boven deze grens klimmen.
        # Dus bijvoorbeeld NOOIT heel training/ negeren alleen omdat er
        # ergens diep daaronder een model staat.
        if (
            $relativeDirectoryGit -eq "training" -or
            $relativeDirectoryGit -eq "application" -or
            $relativeDirectoryGit -eq "frontend" -or
            $relativeDirectoryGit -eq "tests" -or
            $relativeDirectoryGit -eq "project"
        ) {
            break
        }

        $currentDirectory = $currentDirectory.Parent
    }

    if ($null -ne $selectedModelDirectory) {

        $relativeModelDir = Get-RelativePath `
            -BasePath $Root `
            -TargetPath $selectedModelDirectory.FullName

        $relativeModelDir = Convert-ToGitPath $relativeModelDir

        if (-not $relativeModelDir.EndsWith("/")) {
            $relativeModelDir += "/"
        }

        Add-UniqueLine `
            -List $ModelDirectoryRules `
            -Line $relativeModelDir
    }
}

$ModelFileRules = @(
    $ModelFileRules |
    Sort-Object -Unique
)

$ModelDirectoryRules = @(
    $ModelDirectoryRules |
    Sort-Object -Unique
)

Write-Host ("  {0:N0} modelbestanden gevonden" -f $ModelFiles.Count) -ForegroundColor Green
Write-Host ("  {0:N0} modeldirectories gevonden" -f $ModelDirectoryRules.Count) -ForegroundColor Green
Write-Host ""


# ============================================================
# GROTE BESTANDEN
# ============================================================

$LargeFiles = @(
    $AllFiles |
    Where-Object {
        $_.Length -ge ($LargeFileMB * 1MB)
    } |
    Sort-Object Length -Descending
)


# ============================================================
# TOTALE PROJECTGROOTTE
# ============================================================

$totalBytes = [long]0

foreach ($file in $AllFiles) {
    $totalBytes += [long]$file.Length
}


# ============================================================
# .GITIGNORE OPBOUWEN
# ============================================================

$GitIgnore = New-Object System.Collections.ArrayList

[void]$GitIgnore.Add("# ============================================================")
[void]$GitIgnore.Add("# IsalaOCR")
[void]$GitIgnore.Add("# Generated by gitignore_generator.ps1")
[void]$GitIgnore.Add("# ============================================================")
[void]$GitIgnore.Add("")


# ------------------------------------------------------------
# Python
# ------------------------------------------------------------

[void]$GitIgnore.Add("# Python")
[void]$GitIgnore.Add("__pycache__/")
[void]$GitIgnore.Add("*.py[cod]")
[void]$GitIgnore.Add("*`$py.class")
[void]$GitIgnore.Add(".pytest_cache/")
[void]$GitIgnore.Add(".mypy_cache/")
[void]$GitIgnore.Add(".ruff_cache/")
[void]$GitIgnore.Add(".coverage")
[void]$GitIgnore.Add("htmlcov/")
[void]$GitIgnore.Add("")


# ------------------------------------------------------------
# Virtual environments
# ------------------------------------------------------------

[void]$GitIgnore.Add("# Virtual environments")
[void]$GitIgnore.Add(".venv/")
[void]$GitIgnore.Add("venv/")
[void]$GitIgnore.Add("env/")
[void]$GitIgnore.Add("")


# ------------------------------------------------------------
# Environment / secrets
# ------------------------------------------------------------

[void]$GitIgnore.Add("# Environment / secrets")
[void]$GitIgnore.Add(".env")
[void]$GitIgnore.Add(".env.*")
[void]$GitIgnore.Add("!.env.example")
[void]$GitIgnore.Add("")


# ------------------------------------------------------------
# Windows / IDE
# ------------------------------------------------------------

[void]$GitIgnore.Add("# IDE / OS")
[void]$GitIgnore.Add(".idea/")
[void]$GitIgnore.Add(".vscode/")
[void]$GitIgnore.Add(".DS_Store")
[void]$GitIgnore.Add("Thumbs.db")
[void]$GitIgnore.Add("desktop.ini")
[void]$GitIgnore.Add("")


# ------------------------------------------------------------
# Build output
# ------------------------------------------------------------

[void]$GitIgnore.Add("# Build output")
[void]$GitIgnore.Add("build/")
[void]$GitIgnore.Add("dist/")
[void]$GitIgnore.Add("*.egg-info/")
[void]$GitIgnore.Add("node_modules/")
[void]$GitIgnore.Add("")


# ============================================================
# MODELVEILIGHEID - GLOBALE REGELS
#
# Hiermee wordt ieder nieuw model met zo'n extensie automatisch
# genegeerd, ook als het script later niet opnieuw wordt gedraaid.
# ============================================================

[void]$GitIgnore.Add("# ============================================================")
[void]$GitIgnore.Add("# ML / OCR model files - anywhere in repository")
[void]$GitIgnore.Add("# ============================================================")

$GlobalModelRules = @(
    "*.pt",
    "*.pth",
    "*.onnx",
    "*.pdparams",
    "*.pdmodel",
    "*.pdiparams",
    "*.pdopt",
    "*.pdstates",
    "*.ckpt",
    "*.safetensors",
    "*.engine",
    "*.tflite",
    "*.pb",
    "*.h5",
    "*.keras",
    "*.weights",
    "pytorch_model.bin"
)

foreach ($rule in $GlobalModelRules) {
    [void]$GitIgnore.Add($rule)
}

[void]$GitIgnore.Add("")


# ============================================================
# BEKENDE MODEL/CACHE DIRECTORIES
# ============================================================

[void]$GitIgnore.Add("# Model/cache directories")

$KnownModelDirectories = @(
    "models/",
    "model_cache/",
    "model-cache/",
    "weights/",
    "checkpoints/"
)

foreach ($rule in $KnownModelDirectories) {
    [void]$GitIgnore.Add($rule)
}

[void]$GitIgnore.Add("")


# ============================================================
# TRAINING WORKSPACE
#
# BELANGRIJK:
# training/ wordt NIET genegeerd.
# training/workspace/ wel.
#
# Zo blijft tooling/source code onder training/ gewoon in Git.
# ============================================================

[void]$GitIgnore.Add("# Training runtime data")
[void]$GitIgnore.Add("training/workspace/")
[void]$GitIgnore.Add("")


# ============================================================
# INPUT / OUTPUT / GENERATED DATA
# ============================================================

[void]$GitIgnore.Add("# Local input / generated output")
[void]$GitIgnore.Add("input/")
[void]$GitIgnore.Add("output/")
[void]$GitIgnore.Add("outputs/")
[void]$GitIgnore.Add("artifacts/")
[void]$GitIgnore.Add("crops/")
[void]$GitIgnore.Add("source_renders/")
[void]$GitIgnore.Add("detected_blocks/")
[void]$GitIgnore.Add("header_crops/")
[void]$GitIgnore.Add("mapped_crops/")
[void]$GitIgnore.Add("localization_datasets/")
[void]$GitIgnore.Add("table_cell_datasets/")
[void]$GitIgnore.Add("predictions/")
[void]$GitIgnore.Add("cache/")
[void]$GitIgnore.Add(".cache/")
[void]$GitIgnore.Add("tmp/")
[void]$GitIgnore.Add("temp/")
[void]$GitIgnore.Add("")

[void]$GitIgnore.Add("# Medical source data - never commit patient-derived inputs")
[void]$GitIgnore.Add("*.dcm")
[void]$GitIgnore.Add("*.dicom")
[void]$GitIgnore.Add("*.ima")
[void]$GitIgnore.Add("*.nii")
[void]$GitIgnore.Add("*.nii.gz")
[void]$GitIgnore.Add("*.nrrd")
[void]$GitIgnore.Add("*.mha")
[void]$GitIgnore.Add("*.mhd")
[void]$GitIgnore.Add("")


# ============================================================
# DATABASES
# ============================================================

[void]$GitIgnore.Add("# Local databases")
[void]$GitIgnore.Add("*.sqlite")
[void]$GitIgnore.Add("*.sqlite3")
[void]$GitIgnore.Add("*.db")
[void]$GitIgnore.Add("")


# ============================================================
# LOGS
# ============================================================

[void]$GitIgnore.Add("# Logs")
[void]$GitIgnore.Add("*.log")
[void]$GitIgnore.Add("logs/")
[void]$GitIgnore.Add("")


# ============================================================
# ARCHIEVEN
# ============================================================

[void]$GitIgnore.Add("# Archives / generated packages")
[void]$GitIgnore.Add("*.zip")
[void]$GitIgnore.Add("*.7z")
[void]$GitIgnore.Add("*.rar")
[void]$GitIgnore.Add("*.tar")
[void]$GitIgnore.Add("*.gz")
[void]$GitIgnore.Add("")


# ============================================================
# SCRIPT OUTPUT ZELF
# ============================================================

[void]$GitIgnore.Add("# Gitignore scanner output")
[void]$GitIgnore.Add("gitignore-scan-report.txt")
[void]$GitIgnore.Add(".gitignore.backup-*")
[void]$GitIgnore.Add("")


# ============================================================
# AUTOMATISCH GEDETECTEERDE MODELDIRECTORIES
# ============================================================

if ($ModelDirectoryRules.Count -gt 0) {

    [void]$GitIgnore.Add("# ============================================================")
    [void]$GitIgnore.Add("# Automatically detected model directories")
    [void]$GitIgnore.Add("# ============================================================")

    foreach ($rule in $ModelDirectoryRules) {

        if (-not $GitIgnore.Contains($rule)) {
            [void]$GitIgnore.Add($rule)
        }
    }

    [void]$GitIgnore.Add("")
}


# ============================================================
# EXACT GEDETECTEERDE MODELBESTANDEN
#
# Redundant naast *.pth etc., maar bewust:
# het rapport/.gitignore laat precies zien welke modellen tijdens
# de scan daadwerkelijk aanwezig waren.
# ============================================================

if ($ModelFileRules.Count -gt 0) {

    [void]$GitIgnore.Add("# ============================================================")
    [void]$GitIgnore.Add("# Model files detected during scan")
    [void]$GitIgnore.Add("# ============================================================")

    foreach ($rule in $ModelFileRules) {

        if (-not $GitIgnore.Contains($rule)) {
            [void]$GitIgnore.Add($rule)
        }
    }

    [void]$GitIgnore.Add("")
}


# ============================================================
# BESTAANDE .GITIGNORE BACK-UPPEN
# ============================================================

if (Test-Path $GitIgnorePath) {

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

    $backupPath = Join-Path `
        $Root `
        ".gitignore.backup-$timestamp"

    Copy-Item `
        -LiteralPath $GitIgnorePath `
        -Destination $backupPath

    Write-Host "Bestaande .gitignore geback-upt:" -ForegroundColor Yellow
    Write-Host "  $backupPath"
    Write-Host ""
}


# ============================================================
# .GITIGNORE SCHRIJVEN
# ============================================================

$GitIgnore |
    Set-Content `
        -LiteralPath $GitIgnorePath `
        -Encoding UTF8


# ============================================================
# RAPPORT OPBOUWEN
# ============================================================

$Report = New-Object System.Collections.ArrayList

[void]$Report.Add("ISALAOCR GITIGNORE SCAN REPORT")
[void]$Report.Add("============================================================")
[void]$Report.Add("")
[void]$Report.Add("Project:")
[void]$Report.Add($Root)
[void]$Report.Add("")
[void]$Report.Add("Scan:")
[void]$Report.Add((Get-Date).ToString("yyyy-MM-dd HH:mm:ss"))
[void]$Report.Add("")
[void]$Report.Add("Aantal bestanden:  $($AllFiles.Count)")
[void]$Report.Add("Aantal mappen:      $($AllDirs.Count)")
[void]$Report.Add("Projectgrootte:     $(Format-FileSize $totalBytes)")
[void]$Report.Add("Modelbestanden:     $($ModelFiles.Count)")
[void]$Report.Add("Modeldirectories:   $($ModelDirectoryRules.Count)")
[void]$Report.Add("Grote bestanden:    $($LargeFiles.Count)")
[void]$Report.Add("")


# ============================================================
# GROOTSTE MAPPEN
# ============================================================

[void]$Report.Add("")
[void]$Report.Add("============================================================")
[void]$Report.Add("GROOTSTE MAPPEN")
[void]$Report.Add("============================================================")
[void]$Report.Add("")

$DirectorySizeObjects = @()

foreach ($entry in $DirectorySizes.GetEnumerator()) {

    if ($entry.Key -eq $Root) {
        continue
    }

    $relative = Get-RelativePath `
        -BasePath $Root `
        -TargetPath $entry.Key

    $relative = Convert-ToGitPath $relative

    $DirectorySizeObjects += New-Object PSObject -Property @{
        Path  = $relative
        Bytes = [long]$entry.Value
    }
}

$DirectorySizeObjects = @(
    $DirectorySizeObjects |
    Sort-Object Bytes -Descending
)

foreach ($directory in ($DirectorySizeObjects | Select-Object -First 100)) {

    [void]$Report.Add(
        ("{0,-12} {1}" -f `
            (Format-FileSize $directory.Bytes),
            $directory.Path
        )
    )
}


# ============================================================
# GEDETECTEERDE MODELDIRECTORIES
# ============================================================

[void]$Report.Add("")
[void]$Report.Add("")
[void]$Report.Add("============================================================")
[void]$Report.Add("AUTOMATISCH GEDETECTEERDE MODELDIRECTORIES")
[void]$Report.Add("============================================================")
[void]$Report.Add("")

if ($ModelDirectoryRules.Count -eq 0) {

    [void]$Report.Add("Geen modeldirectories gedetecteerd.")

}
else {

    foreach ($rule in $ModelDirectoryRules) {
        [void]$Report.Add($rule)
    }
}


# ============================================================
# GEDETECTEERDE MODELBESTANDEN
# ============================================================

[void]$Report.Add("")
[void]$Report.Add("")
[void]$Report.Add("============================================================")
[void]$Report.Add("GEDETECTEERDE MODELBESTANDEN")
[void]$Report.Add("============================================================")
[void]$Report.Add("")

foreach ($file in ($ModelFiles | Sort-Object Length -Descending)) {

    $relative = Get-RelativePath `
        -BasePath $Root `
        -TargetPath $file.FullName

    $relative = Convert-ToGitPath $relative

    [void]$Report.Add(
        ("{0,-12} {1}" -f `
            (Format-FileSize $file.Length),
            $relative
        )
    )
}


# ============================================================
# GROTE BESTANDEN
# ============================================================

[void]$Report.Add("")
[void]$Report.Add("")
[void]$Report.Add("============================================================")
[void]$Report.Add("GROTE BESTANDEN >= $LargeFileMB MB")
[void]$Report.Add("============================================================")
[void]$Report.Add("")

if ($LargeFiles.Count -eq 0) {

    [void]$Report.Add("Geen grote bestanden gevonden.")

}
else {

    foreach ($file in $LargeFiles) {

        $relative = Get-RelativePath `
            -BasePath $Root `
            -TargetPath $file.FullName

        $relative = Convert-ToGitPath $relative

        [void]$Report.Add(
            ("{0,-12} {1}" -f `
                (Format-FileSize $file.Length),
                $relative
            )
        )
    }
}


# ============================================================
# GIT ADVIES
# ============================================================

[void]$Report.Add("")
[void]$Report.Add("")
[void]$Report.Add("============================================================")
[void]$Report.Add("VOLGENDE STAP")
[void]$Report.Add("============================================================")
[void]$Report.Add("")
[void]$Report.Add("Controleer eerst wat Git zou toevoegen:")
[void]$Report.Add("")
[void]$Report.Add("    git add -n .")
[void]$Report.Add("")
[void]$Report.Add("Daarna pas daadwerkelijk toevoegen:")
[void]$Report.Add("")
[void]$Report.Add("    git add .")
[void]$Report.Add("    git status")
[void]$Report.Add("")


# ============================================================
# RAPPORT SCHRIJVEN
# ============================================================

$Report |
    Set-Content `
        -LiteralPath $ReportPath `
        -Encoding UTF8


# ============================================================
# RESULTAAT
# ============================================================

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Scan voltooid" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""

Write-Host ".gitignore:" -ForegroundColor Cyan
Write-Host "  $GitIgnorePath"

Write-Host ""
Write-Host "Scanrapport:" -ForegroundColor Cyan
Write-Host "  $ReportPath"

Write-Host ""
Write-Host ("Projectgrootte:      {0}" -f (Format-FileSize $totalBytes))
Write-Host ("Modelbestanden:      {0}" -f $ModelFiles.Count)
Write-Host ("Modeldirectories:    {0}" -f $ModelDirectoryRules.Count)
Write-Host ("Grote bestanden:     {0}" -f $LargeFiles.Count)

Write-Host ""
Write-Host "Grootste 15 mappen:" -ForegroundColor Cyan

foreach ($directory in ($DirectorySizeObjects | Select-Object -First 15)) {

    Write-Host (
        "  {0,-12} {1}" -f `
            (Format-FileSize $directory.Bytes),
            $directory.Path
    )
}

Write-Host ""
Write-Host "Grootste 15 modellen:" -ForegroundColor Cyan

foreach ($file in ($ModelFiles | Sort-Object Length -Descending | Select-Object -First 15)) {

    $relative = Get-RelativePath `
        -BasePath $Root `
        -TargetPath $file.FullName

    $relative = Convert-ToGitPath $relative

    Write-Host (
        "  {0,-12} {1}" -f `
            (Format-FileSize $file.Length),
            $relative
    )
}

Write-Host ""
Write-Host "Controleer nu eerst met:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  git add -n ."
Write-Host ""
Write-Host "Dit is alleen een dry-run; er wordt nog niets toegevoegd." -ForegroundColor Yellow
Write-Host ""
