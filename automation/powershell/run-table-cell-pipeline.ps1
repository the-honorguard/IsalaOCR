param(
    [ValidateSet("auto", "cpu", "gpu")]
    [string]$ExecutionDevice = "auto"
)

. (Join-Path $PSScriptRoot "training-common.ps1")
. (Join-Path $PSScriptRoot "table-execution-device.ps1")

$ErrorActionPreference = "Stop"
Assert-IsalaActionPreflight -ActionId "53"

# One complete table-model iteration. The individual scripts remain the source
# of truth; this wrapper only sequences them and stops immediately on failure.
# Canonical GT geometry is never changed here. When source-level GT review flags
# are still open, they are explicitly completed before the dataset snapshot is
# built so the normal iterative loop can be: run everything -> review -> repeat.
#
# ExecutionDevice:
#   auto = prefer a verified NVIDIA/CUDA/Paddle path, otherwise use CPU
#   gpu  = require a working GPU path; fail clearly when unavailable
#   cpu  = force the portable CPU path
$oldNested = $env:ISALA_NESTED_PREFLIGHT_APPROVED
$startedAt = (Get-Date).ToString("o")
$executionState = $null
$statePath = $null

function Write-TableExecutionState {
    param([Parameter(Mandatory = $true)]$Payload)
    if ([string]::IsNullOrWhiteSpace([string]$script:statePath)) { return }
    $Payload | Add-Member -MemberType NoteProperty -Name updated_at -Value ((Get-Date).ToString("o")) -Force
    $json = $Payload | ConvertTo-Json -Depth 8
    $temporary = $script:statePath + ".tmp"
    [System.IO.File]::WriteAllText($temporary, $json, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $script:statePath -Force
}

try {
    $env:ISALA_NESTED_PREFLIGHT_APPROVED = "1"
    $ContainerWorkspace = Get-IsalaContainerWorkspace
    $HostWorkspace = Get-IsalaHostProjectWorkspace
    $statePath = Join-Path $HostWorkspace "table_execution_state.json"

    $executionState = [pscustomobject]@{
        schema_version = 1
        requested_device = $ExecutionDevice
        resolved_device = "pending"
        training_backend = "pending"
        inference_backend = "pending"
        gpu_name = ""
        auto_fallback = $false
        selection_reason = "Nog niet bepaald"
        status = "running"
        started_at = $startedAt
        completed_at = ""
        model_id = ""
        run_id = ""
    }
    Write-TableExecutionState $executionState

    Write-Host "Alles laten draaien: open GT-bronnen afronden indien nodig..." -ForegroundColor Cyan
    $gtPython = "from isala_ocr.training.table_cell_ground_truth import list_ground_truth_sources,set_ground_truth_source_review_completed; import sys; w=sys.argv[1]; s=list_ground_truth_sources(w); o=[str(x.get('source_id') or '') for x in s if not bool(x.get('review_completed'))]; [set_ground_truth_source_review_completed(w,i,True) for i in o if i]; print('GT sources marked correct: %d' % len(o))"
    & docker compose --profile training run --rm --build --entrypoint python training-collector -c $gtPython $ContainerWorkspace
    if ($LASTEXITCODE -ne 0) { throw "Canonical GT completion failed." }

    Write-Host "Alles laten draaien: dataset bouwen..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "build-table-cell-dataset.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Table-cell dataset build failed." }

    Write-Host "Alles laten draaien: dataset valideren..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "validate-table-cell-dataset.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Table-cell dataset validation failed." }

    Write-Host ("Alles laten draaien: uitvoerbackend bepalen (gevraagd: {0})..." -f $ExecutionDevice) -ForegroundColor Cyan
    $deviceSelection = Resolve-IsalaTableExecutionDevice -Requested $ExecutionDevice -PrepareGpuRuntime
    $resolvedDevice = [string]$deviceSelection.Device
    $executionState.resolved_device = $resolvedDevice
    $executionState.training_backend = $resolvedDevice
    $executionState.inference_backend = $resolvedDevice
    $executionState.gpu_name = [string]$deviceSelection.GpuName
    $executionState.auto_fallback = [bool]$deviceSelection.AutoFallback
    $executionState.selection_reason = [string]$deviceSelection.Reason
    Write-TableExecutionState $executionState

    if ($resolvedDevice -eq "gpu") {
        Write-Host ("Uitvoermodus: GPU{0}" -f $(if ($executionState.gpu_name) { " · $($executionState.gpu_name)" } else { "" })) -ForegroundColor Green
    } else {
        Write-Host ("Uitvoermodus: CPU · {0}" -f $executionState.selection_reason) -ForegroundColor Yellow
    }

    Write-Host ("Alles laten draaien: {0}-training..." -f $resolvedDevice.ToUpperInvariant()) -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "train-table-cell-model.ps1") -Device $resolvedDevice
    if ($LASTEXITCODE -ne 0) { throw "Table-cell detector training failed on $resolvedDevice." }

    Write-Host "Alles laten draaien: model activeren..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "activate-table-cell-model.ps1") -ModelId latest
    if ($LASTEXITCODE -ne 0) { throw "Table-cell model activation failed." }

    $activePath = Join-Path $HostWorkspace "table_cell_models\active.json"
    if (-not (Test-Path -LiteralPath $activePath -PathType Leaf)) {
        throw "Active table-cell model pointer ontbreekt na activatie: $activePath"
    }
    $active = Get-Content -LiteralPath $activePath -Raw | ConvertFrom-Json
    $activeModelId = [string]$active.model_id
    $activeRunId = [string]$active.run_id
    if ([string]::IsNullOrWhiteSpace($activeModelId)) {
        throw "Active table-cell model bevat geen model_id."
    }
    $executionState.model_id = $activeModelId
    $executionState.run_id = $activeRunId
    Write-TableExecutionState $executionState

    Write-Host ("Alles laten draaien: nieuw actief model uitvoeren op {0} ({1})..." -f $resolvedDevice.ToUpperInvariant(), $activeModelId) -ForegroundColor Cyan
    $inferenceSucceeded = $false
    try {
        & (Join-Path $PSScriptRoot "collect-training-data.ps1") -TableModelId $activeModelId -Device $resolvedDevice
        $inferenceSucceeded = ($LASTEXITCODE -eq 0)
        if (-not $inferenceSucceeded) { throw "Nieuwe table-cell modelrun failed on $resolvedDevice." }
    }
    catch {
        if ($ExecutionDevice -eq "auto" -and $resolvedDevice -eq "gpu") {
            Write-Warning ("GPU-inference mislukte; Auto probeert dezelfde actieve modelrun opnieuw op CPU. Reden: {0}" -f $_.Exception.Message)
            $executionState.inference_backend = "cpu_fallback"
            $executionState.auto_fallback = $true
            $executionState.selection_reason = ([string]$executionState.selection_reason) + "; GPU-inference fallback naar CPU"
            Write-TableExecutionState $executionState
            & (Join-Path $PSScriptRoot "collect-training-data.ps1") -TableModelId $activeModelId -Device cpu
            if ($LASTEXITCODE -ne 0) { throw "Nieuwe table-cell modelrun failed op GPU en CPU-fallback." }
            $inferenceSucceeded = $true
        }
        else {
            throw
        }
    }
    if (-not $inferenceSucceeded) { throw "Nieuwe table-cell modelrun heeft geen succesvolle inference opgeleverd." }

    # Persist execution provenance next to both the active model and the training
    # run. This does not affect model bytes; it only makes later diagnostics and
    # the UI explicit about where training and inference actually ran.
    $executionState.status = "completed"
    $executionState.completed_at = (Get-Date).ToString("o")
    Write-TableExecutionState $executionState

    foreach ($metadataPath in @(
        $activePath,
        $(if ($activeRunId) { Join-Path $HostWorkspace ("table_cell_runs\{0}\table_cell_run.json" -f $activeRunId) } else { $null })
    )) {
        if ([string]::IsNullOrWhiteSpace([string]$metadataPath) -or -not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) { continue }
        try {
            $metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
            $metadata | Add-Member -MemberType NoteProperty -Name execution -Value ([pscustomobject]@{
                requested_device = $executionState.requested_device
                resolved_device = $executionState.resolved_device
                training_backend = $executionState.training_backend
                inference_backend = $executionState.inference_backend
                gpu_name = $executionState.gpu_name
                auto_fallback = $executionState.auto_fallback
                selection_reason = $executionState.selection_reason
            }) -Force
            $json = $metadata | ConvertTo-Json -Depth 12
            [System.IO.File]::WriteAllText($metadataPath, $json, [System.Text.UTF8Encoding]::new($false))
        }
        catch {
            Write-Warning ("Uitvoerbackend kon niet aan metadata worden toegevoegd: {0}" -f $_.Exception.Message)
        }
    }

    $summaryInference = if ($executionState.inference_backend -eq "cpu_fallback") { "CPU (fallback)" } else { $executionState.inference_backend.ToUpperInvariant() }
    Write-Host ("Alles afgerond. Training: {0}; inference: {1}. Open Stap 7 om alleen de afwijkingen te beoordelen." -f $executionState.training_backend.ToUpperInvariant(), $summaryInference) -ForegroundColor Green
}
catch {
    if ($null -ne $executionState) {
        $executionState.status = "failed"
        $executionState.completed_at = (Get-Date).ToString("o")
        $executionState | Add-Member -MemberType NoteProperty -Name error -Value $_.Exception.Message -Force
        try { Write-TableExecutionState $executionState } catch { }
    }
    throw
}
finally {
    $env:ISALA_NESTED_PREFLIGHT_APPROVED = $oldNested
}
