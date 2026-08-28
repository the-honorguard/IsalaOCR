param(
    [string]$RunAction = "",
    [string]$ActionValue = ""
)

if (-not (Get-Command Invoke-IsalaPreflight -ErrorAction SilentlyContinue)) {
    . (Join-Path $PSScriptRoot "preflight.ps1")
}

$catalog = Get-IsalaActionCatalog
$script:CheckOnlyMode = $false

function Get-IsalaWorkflowActionDefinition {
    param([Parameter(Mandatory = $true)][string]$ActionId)
    if ($ActionId -eq "23") {
        # v3.16: Recognition-GT is intentionally independent from Application
        # Mapping. Keep this lightweight action local until the legacy preflight
        # catalog is fully retired/reworked.
        return @{ Name = "Prepare neutral Recognition Ground Truth"; Script = "prepare-recognition-gt.ps1"; Arguments = @{} }
    }
    if ($null -eq $catalog) { throw "The action catalog was not initialized." }
    return $catalog[[string]$ActionId]
}

function Invoke-IsalaRecognitionGtPreflight {
    $projectWorkspace = Get-IsalaHostProjectWorkspace
    $gtPath = Join-Path $projectWorkspace "table_cell_ground_truth.json"
    if (-not (Test-Path -LiteralPath $gtPath -PathType Leaf)) {
        throw "Canonical table-cell Ground Truth is missing: $gtPath. Complete Steps 3-4 first."
    }
    $renderRoot = Join-Path $projectWorkspace "source_renders"
    $renderCount = if (Test-Path -LiteralPath $renderRoot -PathType Container) { @(Get-ChildItem -LiteralPath $renderRoot -Filter '*.png' -File -ErrorAction SilentlyContinue).Count } else { 0 }
    if ($renderCount -lt 1) {
        throw "No source renders are available for Recognition GT. Run the table/GT flow first."
    }
    Assert-IsalaDetectionGateOpen
    Assert-Docker
}

function Invoke-IsalaMenuAction {
    param(
        [Parameter(Mandatory = $true)][string]$ActionId,
        [hashtable]$AdditionalArguments = @{}
    )

    $definition = Get-IsalaWorkflowActionDefinition -ActionId $ActionId
    if ($null -eq $definition) { throw "Unknown internal task identifier: $ActionId" }
    Write-Host ""
    Write-Host ("Checking prerequisites for task: {0}" -f $definition.Name) -ForegroundColor Cyan

    if ($ActionId -eq "23") {
        Invoke-IsalaRecognitionGtPreflight
    }
    else {
        $allowDockerFailure = ($ActionId -eq "5")
        try {
            $preflightOutput = @(Invoke-IsalaPreflight -ActionId $ActionId -EnsureDocker:(-not $allowDockerFailure) -AllowDockerFailure:$allowDockerFailure -SaveReport:$script:CheckOnlyMode)
            $check = @($preflightOutput | Where-Object {
                $null -ne $_ -and $null -ne $_.PSObject.Properties['Passed']
            } | Select-Object -Last 1)
            if ($check.Count -ne 1) {
                throw "The preflight did not return its final result object."
            }
            $check = $check[0]
        }
        catch {
            $diagnosticDirectory = Join-Path $ProjectRoot "training\workspace\diagnostics"
            New-Item -ItemType Directory -Path $diagnosticDirectory -Force -ErrorAction SilentlyContinue | Out-Null
            $diagnosticPath = Join-Path $diagnosticDirectory ("preflight-crash-action-{0}-{1}.txt" -f $ActionId, (Get-Date -Format "yyyyMMddTHHmmss"))
            $details = @(
                "Internal task ID: $ActionId",
                "Message: $($_.Exception.Message)",
                "Type: $($_.Exception.GetType().FullName)",
                "Position: $($_.InvocationInfo.PositionMessage)",
                "Script stack trace: $($_.ScriptStackTrace)"
            ) -join [Environment]::NewLine
            try { [IO.File]::WriteAllText($diagnosticPath, $details, [Text.UTF8Encoding]::new($false)) } catch { }
            throw ("Preflight implementation failed before the task started: {0}. Diagnostic: {1}" -f $_.Exception.Message, $diagnosticPath)
        }
        if (-not [bool]$check.Passed) {
            throw "Prerequisite check failed. Correct the failed checks before running this task."
        }
    }

    if ($script:CheckOnlyMode) {
        Write-Host "Check-only mode: the task was not executed." -ForegroundColor Yellow
        return
    }

    $arguments = @{}
    $defaultArguments = $definition["Arguments"]
    if ($null -ne $defaultArguments) {
        foreach ($key in @($defaultArguments.Keys)) { $arguments[$key] = $defaultArguments[$key] }
    }
    foreach ($key in $AdditionalArguments.Keys) { $arguments[$key] = $AdditionalArguments[$key] }

    $scriptPath = Join-Path $PSScriptRoot $definition.Script
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw "Task script is missing: $scriptPath"
    }

    $env:ISALA_PREFLIGHT_APPROVED = $ActionId
    try {
        & $scriptPath @arguments
    }
    finally {
        Remove-Item Env:ISALA_PREFLIGHT_APPROVED -ErrorAction SilentlyContinue
    }
}

$workflowSteps = [ordered]@{
    "1"  = @{ Name = "Voorbereiding"; ActionId = "1" }
    "2"  = @{ Name = "Tabelregio’s selecteren"; Url = "http://127.0.0.1:8088/process/panel-setup" }
    "3"  = @{ Name = "Tabelregio trainen & cellen detecteren"; Url = "http://127.0.0.1:8088/process/table-region-model" }
    "4"  = @{ Name = "Cel-GT beoordelen"; Url = "http://127.0.0.1:8088/detection-review" }
    "5"  = @{ Name = "Celdetector verbeteren"; Url = "http://127.0.0.1:8088/process/table-model" }
    "7"  = @{ Name = "Tabelstudio"; Url = "http://127.0.0.1:8088/process/table-quality" }
    "8"  = @{ Name = "Recognition-scope instellen"; Url = "http://127.0.0.1:8088/recognition-scope" }
    "9"  = @{ Name = "Recognition GT Studio"; Url = "http://127.0.0.1:8088/recognition-gt-review" }
    "10" = @{ Name = "Recognition Model Factory"; Url = "http://127.0.0.1:8088/process/recognition-dataset" }
    "11" = @{ Name = "Recognition Model Review"; Url = "http://127.0.0.1:8088/process/recognition-output-review" }
    "12" = @{ Name = "Application Mapping Studio"; ActionId = "20" }
    "13" = @{ Name = "Application mappings toepassen"; ActionId = "21" }
    "14" = @{ Name = "Application output uitlezen"; ActionId = "22" }
    "15" = @{ Name = "Application output beoordelen"; Url = "http://127.0.0.1:8088/review" }
    "F1" = @{ Name = "Fallback · losse box-detector dataset/trainen"; Url = "http://127.0.0.1:8088/process/localization-dataset" }
    "F2" = @{ Name = "Fallback · box-detector evalueren"; Url = "http://127.0.0.1:8088/process/localization-evaluate" }
    "F3" = @{ Name = "Fallback · box-detector activeren"; ActionId = "11" }
    "F4" = @{ Name = "Fallback · detecteren met actief box-model"; ActionId = "12" }
    "F5" = @{ Name = "Fallback · box-detector kwaliteitsrapport"; ActionId = "13" }
}

function Show-IsalaMenu {
    Clear-Host
    $versionFile = Join-Path $ProjectRoot "project\VERSION"
    $displayVersion = ([string](Get-Content -LiteralPath $versionFile -Raw -ErrorAction SilentlyContinue)).Trim()
    if ([string]::IsNullOrWhiteSpace($displayVersion)) { $displayVersion = "unknown" }
    Write-Host ("IsalaOCR Model Factory v{0}" -f $displayVersion) -ForegroundColor Cyan
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor DarkCyan
    Write-Host " MODEL FACTORY · GEOMETRIE" -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor DarkCyan
    foreach ($number in 1..6) {
        $key = [string]$number
        if ($number -eq 1) { Write-Host ("{0,2}. {1}" -f $key, $workflowSteps[$key].Name) -ForegroundColor Cyan } else { Write-Host ("{0,2}. {1}" -f $key, $workflowSteps[$key].Name) }
    }
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor DarkCyan
    Write-Host " MODEL FACTORY · RECOGNITION" -ForegroundColor Yellow
    Write-Host " crop -> exacte tekst; geen functionele mapping" -ForegroundColor DarkYellow
    Write-Host "============================================================" -ForegroundColor DarkCyan
    foreach ($number in 7..12) {
        $key = [string]$number
        Write-Host ("{0,2}. {1}" -f $key, $workflowSteps[$key].Name)
    }
    Write-Host ""
    Write-Host "------------------- EINDPRODUCT -----------------------------" -ForegroundColor Green
    Write-Host " MODEL BUNDLE · detector + recognitionmodel + metadata" -ForegroundColor Green
    Write-Host "------------------------------------------------------------" -ForegroundColor Green
    Write-Host ""
    Write-Host " FASE 2 · APPLICATION PROCESSING · OPTIONEEL" -ForegroundColor Magenta
    foreach ($key in @("A1","A2","A3","A4")) {
        Write-Host (" {0}. {1}" -f $key, $workflowSteps[$key].Name) -ForegroundColor Magenta
    }
    Write-Host ""
    Write-Host " GEPARKEERD - BOX DETECTOR FALLBACK" -ForegroundColor DarkGray
    foreach ($key in @("F1","F2","F3","F4","F5")) {
        Write-Host (" {0}. {1}" -f $key, $workflowSteps[$key].Name) -ForegroundColor DarkGray
    }
    Write-Host ""
    Write-Host " S. Systeemcontroles"
    Write-Host " M. Onderhoud / permissieherstel"
    Write-Host " C. Check-only modus aan/uit"
    Write-Host " 0. Afsluiten"
    Write-Host ""
}

function Invoke-PreparationMenu {
    Write-Host ""
    Write-Host "Stap 1 · Voorbereiding" -ForegroundColor Cyan
    Write-Host "Eén taak voert alle downloads, builds/installaties en controles uit." -ForegroundColor DarkCyan
    Invoke-IsalaMenuAction -ActionId "1"
}

function Invoke-WorkflowStep {
    param([Parameter(Mandatory = $true)][string]$StepNumber)
    $step = $workflowSteps[$StepNumber]
    if ($null -eq $step) { throw "Onbekende workflowstap: $StepNumber" }

    if ($StepNumber -eq "1") {
        Invoke-PreparationMenu
        return
    }
    if ($step.Url) {
        Start-Process ([string]$step.Url)
        return
    }
    if ($step.DeviceActions) {
        $device = ([string](Read-Host "Train op GPU of CPU? [G/C]")).Trim().ToUpperInvariant()
        $taskId = if ($device -eq "C") { [string]$step.DeviceActions.cpu } else { [string]$step.DeviceActions.gpu }
        Invoke-IsalaMenuAction -ActionId $taskId
        return
    }
    if ($step.DeviceChoice) {
        $device = ([string](Read-Host "Train op GPU of CPU? [G/C]")).Trim().ToUpperInvariant()
        $deviceValue = if ($device -eq "C") { "cpu" } else { "gpu" }
        Invoke-IsalaMenuAction -ActionId ([string]$step.ActionId) -AdditionalArguments @{ Device = $deviceValue }
        return
    }
    Invoke-IsalaMenuAction -ActionId ([string]$step.ActionId)
}

if ($RunAction) {
    $extra = @{}
    if ($RunAction -eq "2" -and $ActionValue -eq "__render_only__") {
        $extra.RenderOnly = $true
    }
    elseif ($RunAction -eq "2" -and $ActionValue) {
        $extra.TableModelId = $ActionValue
    }
    elseif ($RunAction -in @("20","21","22") -and $ActionValue) {
        $extra.SourceId = $ActionValue
    }
    elseif ($RunAction -eq "60" -and $ActionValue) {
        $extra.MappingProfileId = $ActionValue
    }
    elseif ($RunAction -eq "26" -and $ActionValue) {
        $extra.Device = $ActionValue
    }
    Invoke-IsalaMenuAction -ActionId $RunAction -AdditionalArguments $extra
    return
}

while ($true) {
    Show-IsalaMenu
    $choice = ([string](Read-Host "Selecteer stap")).Trim().ToUpperInvariant()
    try {
        if ($null -ne $workflowSteps[$choice]) {
            Invoke-WorkflowStep -StepNumber $choice
        }
        elseif ($choice -eq "S") {
            $null = Invoke-IsalaPreflight -AllActions -EnsureDocker -SaveReport
        }
        elseif ($choice -eq "M") {
            Invoke-IsalaPermissionRepair
        }
        elseif ($choice -eq "C") {
            $script:CheckOnlyMode = -not $script:CheckOnlyMode
            continue
        }
        elseif ($choice -eq "0") {
            break
        }
        else {
            Write-Warning "Onbekende keuze"
        }
    }
    catch {
        Write-Host ""
        Write-Host "Taak mislukt:" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
        if (-not [string]::IsNullOrWhiteSpace([string]$_.ScriptStackTrace)) {
            Write-Host ("Stack: " + [string]$_.ScriptStackTrace) -ForegroundColor DarkGray
        }
    }

    Write-Host ""
    Read-Host "Druk op Enter om terug te gaan naar het menu"
}
