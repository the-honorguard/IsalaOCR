param(
    [ValidateSet("auto", "cpu", "gpu")]
    [string]$ExecutionDevice = "auto",
    [ValidateSet("standard","active")][string]$StartFrom = "standard",
    # Forwarded to build-table-cell-dataset.ps1; 0 keeps the built-in
    # hard-example replay defaults (see table_hard_negative_policy.py).
    [double]$ReplayBudgetRatio = 0,
    [int]$ReplayMaxWeight = 0
)

. (Join-Path $PSScriptRoot "training-common.ps1")
. (Join-Path $PSScriptRoot "table-execution-device.ps1")

$ErrorActionPreference = "Stop"
$startedAt = (Get-Date).ToString("o")
$projectId = Get-IsalaActiveProjectId
$Step5DiagnosticsRoot = Join-Path $ProjectRoot "diagnostics\step5"
$Step5TranscriptPath = Join-Path $Step5DiagnosticsRoot "latest.txt"
$Step5SummaryPath = Join-Path $Step5DiagnosticsRoot "latest.json"
$step5TranscriptStarted = $false
$oldNested = $env:ISALA_NESTED_PREFLIGHT_APPROVED
$executionState = $null
$statePath = $null

New-Item -ItemType Directory -Force -Path $Step5DiagnosticsRoot | Out-Null
try {
    Start-Transcript -LiteralPath $Step5TranscriptPath -Force | Out-Null
    $step5TranscriptStarted = $true
}
catch {
    Write-Warning ("Stap 5 transcript kon niet worden gestart: {0}" -f $_.Exception.Message)
}

$step5Summary = [ordered]@{
    schema_version = 1
    project_id = $projectId
    status = "running"
    started_at = $startedAt
    completed_at = ""
    requested_device = $ExecutionDevice
    resolved_device = ""
    training_backend = ""
    inference_backend = ""
    gpu_name = ""
    dataset_id = ""
    dataset = $null
    validation = $null
    hard_example_replay = $null
    model_id = ""
    run_id = ""
    training_run = $null
    model_validation = $null
    error = ""
}

function Write-Step5DiagnosticsSummary {
    $json = $script:step5Summary | ConvertTo-Json -Depth 16
    $temporary = $script:Step5SummaryPath + ".tmp"
    [System.IO.File]::WriteAllText($temporary, $json, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $script:Step5SummaryPath -Force
}

function Write-TableExecutionState {
    param([Parameter(Mandatory = $true)]$Payload)
    if ([string]::IsNullOrWhiteSpace([string]$script:statePath)) { return }
    $Payload | Add-Member -MemberType NoteProperty -Name updated_at -Value ((Get-Date).ToString("o")) -Force
    $json = $Payload | ConvertTo-Json -Depth 8
    $temporary = $script:statePath + ".tmp"
    [System.IO.File]::WriteAllText($temporary, $json, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $script:statePath -Force
}

function Wait-IsalaComparisonReviewQueue {
    param([int]$TimeoutSeconds = 60)
    $queuePath = Join-Path $ProjectRoot "training\workspace\webui\comparison_review_queue.json"
    if (-not (Test-Path -LiteralPath $queuePath -PathType Leaf)) { return }
    $deadline = (Get-Date).AddSeconds([Math]::Max(5, $TimeoutSeconds))
    $announced = $false
    $lastProgress = Get-Date
    while ($true) {
        try {
            $queue = Get-Content -LiteralPath $queuePath -Raw | ConvertFrom-Json
            $projectItems = @($queue.items | Where-Object { [string]$_.project_id -eq $projectId })
            $failed = @($projectItems | Where-Object { [string]$_.status -eq "failed" })
            if ($failed.Count -gt 0) {
                $last = $failed[-1]
                throw ("{0} reviewwachtrij-item(s) zijn mislukt; laatste fout: {1}. Gebruik 'Opnieuw proberen' in de webinterface voordat Stap 5 verdergaat." -f $failed.Count, [string]$last.last_error)
            }
            $pending = @($projectItems | Where-Object { [string]$_.status -in @("pending", "processing") })
            if ($pending.Count -eq 0) {
                if ($announced) { Write-Host "Review-opslag is volledig verwerkt; dataset snapshot kan veilig worden gemaakt." -ForegroundColor Green }
                return
            }
            if (-not $announced) {
                Write-Host ("Stap 5 wacht eerst op {0} nog niet verwerkte Stap-6 beoordeling(en)..." -f $pending.Count) -ForegroundColor Cyan
                $announced = $true
                $lastProgress = Get-Date
            }
            elseif (((Get-Date) - $lastProgress).TotalSeconds -ge 5) {
                Write-Host ("Nog {0} reviewwachtrij-item(s) te verwerken..." -f $pending.Count) -ForegroundColor DarkCyan
                $lastProgress = Get-Date
            }
        }
        catch {
            if ($_.Exception.Message -like "*reviewwachtrij-item(s) zijn mislukt*") { throw }
            # The queue writer replaces the JSON atomically. A very short read
            # race should not make Step 5 fail; retry until the same timeout.
        }
        if ((Get-Date) -ge $deadline) {
            throw "Reviewwachtrij was na $TimeoutSeconds seconden nog niet leeg. Stap 5 stopt om geen dataset met nog niet opgeslagen beoordelingen te bouwen."
        }
        Start-Sleep -Milliseconds 250
    }
}

try {
    Write-Host ("Stap 5 diagnostiek wordt bijgehouden in {0} en {1}" -f $Step5TranscriptPath, $Step5SummaryPath) -ForegroundColor DarkCyan
    Write-Step5DiagnosticsSummary
    Assert-IsalaActionPreflight -ActionId "53"

    # The web worker intentionally keeps launcher arguments generic. Read the
    # execution preference directly from the currently running action-53 job so
    # the browser can submit Auto/CPU/GPU without coupling the worker to this action.
    if ($ExecutionDevice -eq "auto") {
        try {
            $runningJobs = Join-Path $ProjectRoot "training\workspace\webui\jobs\running"
            $job = Get-ChildItem -LiteralPath $runningJobs -Filter "*.json" -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTimeUtc -Descending |
                ForEach-Object {
                    try {
                        $candidate = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
                        if ([string]$candidate.action_id -eq "53" -and [string]$candidate.project_id -eq $projectId) { $candidate }
                    } catch { }
                } | Select-Object -First 1
            if ($null -ne $job -and $null -ne $job.options) {
                $requestedFromJob = ([string]$job.options.execution_device).Trim().ToLowerInvariant()
                if ($requestedFromJob -in @("auto", "cpu", "gpu")) {
                    $ExecutionDevice = $requestedFromJob
                    $step5Summary.requested_device = $ExecutionDevice
                    Write-Step5DiagnosticsSummary
                }
                $requestedStart = ([string]$job.options.start_from).Trim().ToLowerInvariant()
                if ($requestedStart -in @("standard", "active")) { $StartFrom = $requestedStart }
            }
        }
        catch {
            Write-Warning ("Uitvoermodus uit webtaak kon niet worden gelezen; Auto blijft actief: {0}" -f $_.Exception.Message)
        }
    }

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

    # Review clicks are persisted by a backend FIFO. Navigation no longer waits
    # for those writes, so Step 5 establishes a barrier before snapshotting GT +
    # feedback. This guarantees that the just-completed Step-6 decisions are in
    # reviews.json before the dataset/replay plan is built.
    Wait-IsalaComparisonReviewQueue -TimeoutSeconds 60

    Write-Host "Alles laten draaien: open GT-bronnen afronden indien nodig..." -ForegroundColor Cyan
    $gtPython = "from isala_ocr.training.table_cell_ground_truth import list_ground_truth_sources,set_ground_truth_source_review_completed; import sys; w=sys.argv[1]; s=list_ground_truth_sources(w); o=[str(x.get('source_id') or '') for x in s if not bool(x.get('review_completed'))]; [set_ground_truth_source_review_completed(w,i,True) for i in o if i]; print('GT sources marked correct: %d' % len(o))"
    & docker compose --profile training run --rm --build --entrypoint python training-collector -c $gtPython $ContainerWorkspace
    if ($LASTEXITCODE -ne 0) { throw "Canonical GT completion failed." }

    Write-Host "Alles laten draaien: dataset bouwen..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "build-table-cell-dataset.ps1") `
        -ReplayBudgetRatio $ReplayBudgetRatio -ReplayMaxWeight $ReplayMaxWeight
    if ($LASTEXITCODE -ne 0) { throw "Table-cell dataset build failed." }

    $datasetPointer = Join-Path $HostWorkspace "table_cell_datasets\latest.txt"
    if (Test-Path -LiteralPath $datasetPointer -PathType Leaf) {
        $datasetId = (Get-Content -LiteralPath $datasetPointer -Raw).Trim()
        $step5Summary.dataset_id = $datasetId
        $manifestPath = Join-Path $HostWorkspace ("table_cell_datasets\{0}\manifest.json" -f $datasetId)
        if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
            $step5Summary.dataset = [ordered]@{
                source_count = [int]$manifest.source_count
                panel_count = [int]$manifest.panel_count
                annotation_count = [int]$manifest.annotation_count
                training_image_count = [int]$manifest.training_image_count
                training_annotation_count = [int]$manifest.training_annotation_count
                splits = $manifest.splits
                training_feedback = $manifest.training_feedback
            }
            $step5Summary.hard_example_replay = $manifest.hard_example_replay
        }
        Write-Step5DiagnosticsSummary
    }

    Write-Host "Alles laten draaien: dataset valideren..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "validate-table-cell-dataset.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Table-cell dataset validation failed." }
    if (-not [string]::IsNullOrWhiteSpace([string]$step5Summary.dataset_id)) {
        $validationPath = Join-Path $HostWorkspace ("table_cell_datasets\{0}\validation.json" -f $step5Summary.dataset_id)
        if (Test-Path -LiteralPath $validationPath -PathType Leaf) {
            $validation = Get-Content -LiteralPath $validationPath -Raw | ConvertFrom-Json
            $step5Summary.validation = [ordered]@{
                valid = [bool]$validation.valid
                errors = @($validation.errors)
                warnings = @($validation.warnings)
                splits = $validation.splits
                numeric_sanity = $validation.numeric_sanity
            }
            Write-Step5DiagnosticsSummary
        }
    }

    Write-Host ("Alles laten draaien: uitvoerbackend bepalen (gevraagd: {0})..." -f $ExecutionDevice) -ForegroundColor Cyan
    $deviceSelection = Resolve-IsalaTableExecutionDevice -Requested $ExecutionDevice -PrepareGpuRuntime
    $resolvedDevice = [string]$deviceSelection.Device
    $executionState.resolved_device = $resolvedDevice
    $executionState.training_backend = $resolvedDevice
    $executionState.inference_backend = $resolvedDevice
    $executionState.gpu_name = [string]$deviceSelection.GpuName
    $executionState.auto_fallback = [bool]$deviceSelection.AutoFallback
    $executionState.selection_reason = [string]$deviceSelection.Reason
    $step5Summary.resolved_device = $resolvedDevice
    $step5Summary.training_backend = $resolvedDevice
    $step5Summary.inference_backend = $resolvedDevice
    $step5Summary.gpu_name = [string]$deviceSelection.GpuName
    Write-TableExecutionState $executionState
    Write-Step5DiagnosticsSummary

    if ($resolvedDevice -eq "gpu") {
        Write-Host ("Uitvoermodus: GPU{0}" -f $(if ($executionState.gpu_name) { " · $($executionState.gpu_name)" } else { "" })) -ForegroundColor Green
    } else {
        Write-Host ("Uitvoermodus: CPU · {0}" -f $executionState.selection_reason) -ForegroundColor Yellow
    }

    Write-Host ("Alles laten draaien: {0}-training..." -f $resolvedDevice.ToUpperInvariant()) -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "train-table-cell-model.ps1") -Device $resolvedDevice -StartFrom $StartFrom
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
    $step5Summary.model_id = $activeModelId
    $step5Summary.run_id = $activeRunId
    Write-TableExecutionState $executionState

    if (-not [string]::IsNullOrWhiteSpace($activeRunId)) {
        $runRoot = Join-Path $HostWorkspace ("table_cell_runs\{0}" -f $activeRunId)
        $runMetadataPath = Join-Path $runRoot "table_cell_run.json"
        $runValidationPath = Join-Path $runRoot "validation_evaluation.json"
        if (Test-Path -LiteralPath $runMetadataPath -PathType Leaf) {
            $runMetadata = Get-Content -LiteralPath $runMetadataPath -Raw | ConvertFrom-Json
            $step5Summary.training_run = [ordered]@{
                training_mode = [string]$runMetadata.training_mode
                parent_model_id = [string]$runMetadata.parent_model_id
                epochs = $runMetadata.epochs
                batch_size = $runMetadata.batch_size
                learning_rate = $runMetadata.learning_rate
                base_train_images = $runMetadata.base_train_images
                hard_example_replay_draws = $runMetadata.hard_example_replay_draws
                hard_example_replay_panels = $runMetadata.hard_example_replay_panels
                hard_example_replay_runtime = $runMetadata.hard_example_replay_runtime
                started_at = [string]$runMetadata.started_at
                completed_at = [string]$runMetadata.completed_at
            }
        }
        if (Test-Path -LiteralPath $runValidationPath -PathType Leaf) {
            $step5Summary.model_validation = Get-Content -LiteralPath $runValidationPath -Raw | ConvertFrom-Json
        }
        Write-Step5DiagnosticsSummary
    }

    Write-Host ("Alles laten draaien: nieuw actief model uitvoeren op {0} ({1})..." -f $resolvedDevice.ToUpperInvariant(), $activeModelId) -ForegroundColor Cyan
    $inferenceSucceeded = $false
    try {
        & (Join-Path $PSScriptRoot "collect-training-data.ps1") -TableModelId $activeModelId -Device $resolvedDevice
        $inferenceSucceeded = ($LASTEXITCODE -eq 0)
        if (-not $inferenceSucceeded) { throw "Nieuwe table-cell modelrun failed on $resolvedDevice." }
    }
    catch {
        $inferenceError = [string]$_.Exception.Message
        if ($inferenceError.Contains("[ISALA_TABLE_RUNTIME_BROKEN]")) {
            # A dependency/ABI/image startup defect is deterministic and affects
            # the inference stack itself. Falling back to CPU would hide the
            # broken environment instead of providing a meaningful recovery.
            throw ("GPU table-inference runtime is ongeldig; CPU-fallback bewust overgeslagen. {0}" -f $inferenceError)
        }
        if ($ExecutionDevice -eq "auto" -and $resolvedDevice -eq "gpu") {
            Write-Warning ("GPU-inference mislukte; Auto probeert dezelfde actieve modelrun opnieuw op CPU. Reden: {0}" -f $inferenceError)
            $executionState.inference_backend = "cpu_fallback"
            $executionState.auto_fallback = $true
            $executionState.selection_reason = ([string]$executionState.selection_reason) + "; GPU-inference fallback naar CPU"
            $step5Summary.inference_backend = "cpu_fallback"
            Write-TableExecutionState $executionState
            Write-Step5DiagnosticsSummary
            & (Join-Path $PSScriptRoot "collect-training-data.ps1") -TableModelId $activeModelId -Device cpu
            if ($LASTEXITCODE -ne 0) { throw "Nieuwe table-cell modelrun failed op GPU en CPU-fallback." }
            $inferenceSucceeded = $true
        }
        else {
            throw
        }
    }
    if (-not $inferenceSucceeded) { throw "Nieuwe table-cell modelrun heeft geen succesvolle inference opgeleverd." }

    $executionState.status = "completed"
    $executionState.completed_at = (Get-Date).ToString("o")
    $step5Summary.status = "completed"
    $step5Summary.completed_at = $executionState.completed_at
    $step5Summary.inference_backend = [string]$executionState.inference_backend
    Write-TableExecutionState $executionState
    Write-Step5DiagnosticsSummary

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
    Write-Host ("Alles afgerond. Training: {0}; inference: {1}. Open Stap 6 om alleen de afwijkingen te beoordelen." -f $executionState.training_backend.ToUpperInvariant(), $summaryInference) -ForegroundColor Green
    Write-Host "Voor diagnose/push: diagnostics/step5/latest.txt + diagnostics/step5/latest.json" -ForegroundColor DarkCyan
}
catch {
    $errorMessage = $_.Exception.Message
    if ($null -ne $executionState) {
        $executionState.status = "failed"
        $executionState.completed_at = (Get-Date).ToString("o")
        $executionState | Add-Member -MemberType NoteProperty -Name error -Value $errorMessage -Force
        try { Write-TableExecutionState $executionState } catch { }
    }
    $step5Summary.status = "failed"
    $step5Summary.completed_at = (Get-Date).ToString("o")
    $step5Summary.error = $errorMessage
    try { Write-Step5DiagnosticsSummary } catch { }
    throw
}
finally {
    $env:ISALA_NESTED_PREFLIGHT_APPROVED = $oldNested
    try { Write-Step5DiagnosticsSummary } catch { }
    if ($step5TranscriptStarted) {
        try { Stop-Transcript | Out-Null } catch { }
    }
}
