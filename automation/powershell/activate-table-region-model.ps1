. (Join-Path $PSScriptRoot "training-common.ps1")
Assert-IsalaActionPreflight -ActionId "57"
$HostWorkspace = Get-IsalaHostProjectWorkspace
$RunsRoot = Join-Path $HostWorkspace "table_region_runs"
$candidate = Get-ChildItem -LiteralPath $RunsRoot -Directory -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "model.json") } |
    Select-Object -First 1
if ($null -eq $candidate) { throw "Geen getraind tabelregio-model gevonden." }
$model = Get-Content -LiteralPath (Join-Path $candidate.FullName "model.json") -Raw | ConvertFrom-Json
$evaluationPath = Join-Path $candidate.FullName "evaluation_artifacts\test_evaluation.json"
if (-not (Test-Path -LiteralPath $evaluationPath -PathType Leaf)) {
    throw "Model heeft geen onafhankelijke test-evaluatie. Train de tabelregio opnieuw voordat je activeert."
}
$evaluation = Get-Content -LiteralPath $evaluationPath -Raw | ConvertFrom-Json
if (-not [bool]$evaluation.passed) {
    throw "Model faalt de onafhankelijke tabelregio-test (recall=$($evaluation.recall_at_iou_0_50), precision=$($evaluation.precision_at_iou_0_50))."
}
$relativeInference = $model.inference_dir
if ([string]::IsNullOrWhiteSpace([string]$relativeInference)) { throw "Training metadata heeft geen inference_dir." }
if ([IO.Path]::IsPathRooted([string]$relativeInference)) {
    $workspaceFull = [System.IO.Path]::GetFullPath($HostWorkspace).TrimEnd('\','/')
    $inferenceFull = [System.IO.Path]::GetFullPath([string]$relativeInference)
    $workspacePrefix = $workspaceFull + [System.IO.Path]::DirectorySeparatorChar
    if (-not $inferenceFull.StartsWith($workspacePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Tabelregio-model staat buiten de projectworkspace: $inferenceFull"
    }
    $relativeInference = $inferenceFull.Substring($workspacePrefix.Length).Replace('\','/')
}
$model.inference_dir = [string]$relativeInference
$model.test_evaluation = $evaluation
$model.active = $true
$ActiveDirectory = Join-Path $HostWorkspace "table_region_models"
New-Item -ItemType Directory -Force -Path $ActiveDirectory | Out-Null
$model | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ActiveDirectory "active.json") -Encoding UTF8
Write-Host "Actief tabelregio-model: $($model.model_id)" -ForegroundColor Green
