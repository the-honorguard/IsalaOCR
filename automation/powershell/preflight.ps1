if (-not (Get-Command Get-TrainingImageVersion -ErrorAction SilentlyContinue)) {
    . (Join-Path $PSScriptRoot "training-common.ps1")
}

function New-IsalaCheckResult {
    param(
        [Parameter(Mandatory = $true)][string]$Scope,
        [Parameter(Mandatory = $true)][string]$Name,
        [ValidateSet("PASS","WARN","FAIL","SKIP")][string]$Status,
        [Parameter(Mandatory = $true)][string]$Message,
        [string]$Remediation = ""
    )
    return [pscustomobject]@{
        Scope = $Scope
        Name = $Name
        Status = $Status
        Message = $Message
        Remediation = $Remediation
    }
}

function Get-IsalaActionCatalog {
    return [ordered]@{
        "1"  = @{ Name = "Prepare ALL models and training images"; Script = "prepare-training.ps1"; Profile = "prepare" }
        "2"  = @{ Name = "Detect PP-Structure table regions/cells (table-first)"; Script = "collect-training-data.ps1"; Profile = "collect" }
        # Action 3 is the host-side entry point used by START.cmd to start the
        # local web interface. It must live in the same catalog as executable
        # pipeline actions because label-training-data.ps1 protects itself with
        # Assert-IsalaActionPreflight -ActionId "3".
        "3"  = @{ Name = "Start table-cell review / control web interface"; Script = "label-training-data.ps1"; Profile = "webui-start" }
        "5"  = @{ Name = "Build COCO localization dataset"; Script = "build-localization-dataset.ps1"; Profile = "localization-build" }
        "6"  = @{ Name = "Validate localization dataset"; Script = "validate-localization-dataset.ps1"; Profile = "localization-check" }
        "7"  = @{ Name = "Train field detector on NVIDIA GPU"; Script = "train-localization-model.ps1"; Profile = "localization-train-gpu"; Arguments = @{ Device = "gpu" } }
        "8"  = @{ Name = "Train field detector on CPU"; Script = "train-localization-model.ps1"; Profile = "localization-train-cpu"; Arguments = @{ Device = "cpu" } }
        "9"  = @{ Name = "Evaluate current field detector and confidence sweep"; Script = "evaluate-localization.ps1"; Profile = "localization-evaluate" }
        "10" = @{ Name = "Compare baseline vs trained field detector"; Script = "compare-localization.ps1"; Profile = "localization-compare" }
        "11" = @{ Name = "Register / activate field detector"; Script = "activate-localization-model.ps1"; Profile = "localization-activate" }
        "12" = @{ Name = "Re-run detection with active field detector"; Script = "redetect-localization.ps1"; Profile = "localization-redetect" }
        "13" = @{ Name = "Detection quality report"; Script = "detection-quality-report.ps1"; Profile = "localization-report" }
        "14" = @{ Name = "Install inference OCR / table models"; Script = "prepare-training.ps1"; Profile = "prepare-inference"; Arguments = @{ Component = "inference"; PreflightActionId = "14" } }
        "15" = @{ Name = "Install CPU detector / PicoDet-S stack"; Script = "prepare-training.ps1"; Profile = "prepare-cpu-detection"; Arguments = @{ Component = "cpu-detection"; PreflightActionId = "15" } }
        "16" = @{ Name = "Install GPU OCR recognition stack"; Script = "prepare-training.ps1"; Profile = "prepare-gpu-recognition"; Arguments = @{ Component = "gpu-recognition"; PreflightActionId = "16" } }
        "17" = @{ Name = "Install GPU PaddleDetection / PicoDet-S stack"; Script = "prepare-training.ps1"; Profile = "prepare-gpu-detection"; Arguments = @{ Component = "gpu-detection"; PreflightActionId = "17" } }
        "18" = @{ Name = "Install PP-OCRv6 pretrained training weight"; Script = "prepare-training.ps1"; Profile = "prepare-pretrained"; Arguments = @{ Component = "pretrained"; PreflightActionId = "18" } }
        "19" = @{ Name = "Refresh preparation status"; Script = "preparation-status.ps1"; Profile = "preparation-status" }
        # Granular preparation phases. Internal IDs only; the UI shows task names, never these numbers.
        "30" = @{ Name = "Download inference OCR / table model files"; Script = "prepare-training.ps1"; Profile = "prepare-inference-download"; Arguments = @{ Component = "inference"; Phase = "download"; PreflightActionId = "30" } }
        "31" = @{ Name = "Download CPU detector base files"; Script = "prepare-training.ps1"; Profile = "prepare-cpu-download"; Arguments = @{ Component = "cpu-detection"; Phase = "download"; PreflightActionId = "31" } }
        "32" = @{ Name = "Download GPU OCR base files"; Script = "prepare-training.ps1"; Profile = "prepare-gpu-rec-download"; Arguments = @{ Component = "gpu-recognition"; Phase = "download"; PreflightActionId = "32" } }
        "33" = @{ Name = "Download GPU detector base files"; Script = "prepare-training.ps1"; Profile = "prepare-gpu-det-download"; Arguments = @{ Component = "gpu-detection"; Phase = "download"; PreflightActionId = "33" } }
        "34" = @{ Name = "Download PP-OCRv6 pretrained weight"; Script = "prepare-training.ps1"; Profile = "prepare-pretrained-download"; Arguments = @{ Component = "pretrained"; Phase = "download"; PreflightActionId = "34" } }
        "35" = @{ Name = "Install inference OCR / table runtime"; Script = "prepare-training.ps1"; Profile = "prepare-inference-install"; Arguments = @{ Component = "inference"; Phase = "install"; PreflightActionId = "35" } }
        "36" = @{ Name = "Build CPU detector / PicoDet-S stack"; Script = "prepare-training.ps1"; Profile = "prepare-cpu-install"; Arguments = @{ Component = "cpu-detection"; Phase = "install"; PreflightActionId = "36" } }
        "37" = @{ Name = "Build GPU OCR-recognition stack"; Script = "prepare-training.ps1"; Profile = "prepare-gpu-rec-install"; Arguments = @{ Component = "gpu-recognition"; Phase = "install"; PreflightActionId = "37" } }
        "38" = @{ Name = "Build GPU PaddleDetection stack"; Script = "prepare-training.ps1"; Profile = "prepare-gpu-det-install"; Arguments = @{ Component = "gpu-detection"; Phase = "install"; PreflightActionId = "38" } }
        "39" = @{ Name = "Install PP-OCRv6 pretrained weight"; Script = "prepare-training.ps1"; Profile = "prepare-pretrained-install"; Arguments = @{ Component = "pretrained"; Phase = "install"; PreflightActionId = "39" } }
        "40" = @{ Name = "Download all preparation files in parallel"; Script = "prepare-training.ps1"; Profile = "prepare-all-download"; Arguments = @{ Component = "all"; Phase = "download"; PreflightActionId = "40" } }
        "41" = @{ Name = "Install/build all preparation components"; Script = "prepare-training.ps1"; Profile = "prepare-all-install"; Arguments = @{ Component = "all"; Phase = "install"; PreflightActionId = "41" } }
        "42" = @{ Name = "Check inference OCR / table installation"; Script = "prepare-training.ps1"; Profile = "prepare-inference-check"; Arguments = @{ Component = "inference"; Phase = "check"; PreflightActionId = "42" } }
        "43" = @{ Name = "Check CPU detector / PicoDet-S installation"; Script = "prepare-training.ps1"; Profile = "prepare-cpu-check"; Arguments = @{ Component = "cpu-detection"; Phase = "check"; PreflightActionId = "43" } }
        "44" = @{ Name = "Check GPU OCR-recognition installation"; Script = "prepare-training.ps1"; Profile = "prepare-gpu-rec-check"; Arguments = @{ Component = "gpu-recognition"; Phase = "check"; PreflightActionId = "44" } }
        "45" = @{ Name = "Check GPU PaddleDetection installation"; Script = "prepare-training.ps1"; Profile = "prepare-gpu-det-check"; Arguments = @{ Component = "gpu-detection"; Phase = "check"; PreflightActionId = "45" } }
        "46" = @{ Name = "Check PP-OCRv6 pretrained weight"; Script = "prepare-training.ps1"; Profile = "prepare-pretrained-check"; Arguments = @{ Component = "pretrained"; Phase = "check"; PreflightActionId = "46" } }
        "47" = @{ Name = "Check all preparation installations"; Script = "prepare-training.ps1"; Profile = "prepare-all-check"; Arguments = @{ Component = "all"; Phase = "check"; PreflightActionId = "47" } }
        "48" = @{ Name = "Build reviewed table-cell training dataset"; Script = "build-table-cell-dataset.ps1"; Profile = "table-cell-build" }
        "49" = @{ Name = "Validate reviewed table-cell training dataset"; Script = "validate-table-cell-dataset.ps1"; Profile = "table-cell-check" }
        "50" = @{ Name = "Fine-tune wireless table-cell detector on GPU"; Script = "train-table-cell-model.ps1"; Profile = "table-cell-train"; Arguments = @{ Device = "gpu" } }
        "51" = @{ Name = "Fine-tune wireless table-cell detector on CPU"; Script = "train-table-cell-model.ps1"; Profile = "table-cell-train"; Arguments = @{ Device = "cpu" } }
        "52" = @{ Name = "Activate trained wireless table-cell detector"; Script = "activate-table-cell-model.ps1"; Profile = "table-cell-activate" }
        "53" = @{ Name = "Build, validate, train and activate table-cell detector"; Script = "run-table-cell-pipeline.ps1"; Profile = "table-cell-full" }
        "20" = @{ Name = "Prepare Mapping Studio data after geometry gate"; Script = "prepare-mapping-data.ps1"; Profile = "mapping-prepare" }
        "21" = @{ Name = "Apply confirmed mappings / create final crops"; Script = "apply-mappings.ps1"; Profile = "mapping-apply" }
        "22" = @{ Name = "Read values from approved mapped crops"; Script = "read-mapped-values.ps1"; Profile = "value-read" }
        "24" = @{ Name = "Build recognition dataset"; Script = "build-training-dataset.ps1"; Profile = "dataset-build" }
        "25" = @{ Name = "Validate recognition dataset"; Script = "check-training-dataset.ps1"; Profile = "dataset-check" }
        "26" = @{ Name = "Train recognition model"; Script = "train-recognition-model.ps1"; Profile = "recognition-train"; Arguments = @{ Device = "gpu" } }
        "27" = @{ Name = "Evaluate and compare recognition model"; Script = "evaluate-recognition-pipeline.ps1"; Profile = "recognition-evaluate" }
        "28" = @{ Name = "Register / activate recognition model"; Script = "register-activate-recognition.ps1"; Profile = "recognition-register" }
        # Legacy aliases for jobs created by <=3.6.x. They are intentionally not shown in the menu.
        "107" = @{ Name = "Legacy recognition dataset build"; Script = "build-training-dataset.ps1"; Profile = "dataset-build" }
        "108" = @{ Name = "Legacy recognition dataset validate"; Script = "check-training-dataset.ps1"; Profile = "dataset-check" }
        "109" = @{ Name = "Legacy recognition baseline"; Script = "evaluate-recognition-model.ps1"; Profile = "baseline"; Arguments = @{ Kind = "baseline"; PreflightActionId = "109" } }
        "110" = @{ Name = "Legacy recognition GPU train"; Script = "train-recognition-model.ps1"; Profile = "train-gpu"; Arguments = @{ Device = "gpu"; PreflightActionId = "110" } }
        "111" = @{ Name = "Legacy recognition CPU train"; Script = "train-recognition-model.ps1"; Profile = "train-cpu"; Arguments = @{ Device = "cpu"; PreflightActionId = "111" } }
        "112" = @{ Name = "Legacy recognition export"; Script = "export-recognition-model.ps1"; Profile = "export" }
        "113" = @{ Name = "Legacy recognition custom eval"; Script = "evaluate-recognition-model.ps1"; Profile = "custom"; Arguments = @{ Kind = "custom"; PreflightActionId = "113" } }
        "114" = @{ Name = "Legacy recognition compare"; Script = "compare-models.ps1"; Profile = "compare" }
        "115" = @{ Name = "Legacy recognition register"; Script = "register-recognition-model.ps1"; Profile = "register" }
        "116" = @{ Name = "Legacy recognition activate"; Script = "activate-recognition-model.ps1"; Profile = "activate" }
    }
}

function Test-IsalaHostDirectoryWritable {
    param([Parameter(Mandatory = $true)][string]$Path)
    $probe = $null
    try {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
        $probe = Join-Path $Path (".isalaocr-host-probe-{0}-{1}" -f $PID, [Guid]::NewGuid().ToString("N"))
        [IO.File]::WriteAllText($probe, "ok", [Text.UTF8Encoding]::new($false))
        Remove-Item -LiteralPath $probe -Force
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($probe) { Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue }
    }
}

function Get-IsalaInputFileCount {
    $inputRoot = Get-IsalaHostProjectInput
    if (-not (Test-Path -LiteralPath $inputRoot -PathType Container)) { return 0 }
    $ignored = @('.ini','.yaml','.yml','.json','.txt','.log','.gitkeep')
    return @(
        Get-ChildItem -LiteralPath $inputRoot -Recurse -File -Force -ErrorAction SilentlyContinue |
            Where-Object { $ignored -notcontains $_.Extension.ToLowerInvariant() -and $_.Name -ne '.gitkeep' }
    ).Count
}

function Get-IsalaDatasetPreflightState {
    param([switch]$RequireDictionary)
    try {
        $resolution = Get-LatestDatasetResolution
        if (-not $resolution.Found) {
            return [pscustomobject]@{
                Ready = $false
                Status = "FAIL"
                Message = $(if ($resolution.PointerProblem) { $resolution.PointerProblem + " No complete dataset directory was found." } else { "No complete dataset directory was found." })
                Remediation = "Open Stap 17 · Recognition-dataset bouwen after Pipeline A is complete and mappings/ROI/value reviews are approved."
                Dataset = $null
            }
        }

        $dataset = $resolution.Dataset
        if ($RequireDictionary -and -not $dataset.DictionaryReady) {
            return [pscustomobject]@{
                Ready = $false
                Status = "FAIL"
                Message = ("Dataset {0} is present, but dict.txt has not yet been synchronized." -f $dataset.Id)
                Remediation = "Open Stap 18 · Recognition-dataset valideren to validate/synchronize the recognition dataset and dictionary."
                Dataset = $null
            }
        }

        $warnings = New-Object System.Collections.Generic.List[string]
        if ($resolution.Source -eq "fallback") {
            $warnings.Add($resolution.PointerProblem)
            $warnings.Add(("A complete fallback dataset was found: {0}. The pointer will be repaired when the task starts." -f $dataset.Id))
        }
        if ($dataset.OptionalMissingFiles.Count -gt 0) {
            $warnings.Add(("Optional audit files are missing: {0}. Character validation is derived directly from train/val/test labels." -f ($dataset.OptionalMissingFiles -join ', ')))
        }

        return [pscustomobject]@{
            Ready = $true
            Status = $(if ($warnings.Count -gt 0) { "WARN" } else { "PASS" })
            Message = $(if ($warnings.Count -gt 0) { ("Dataset {0} is usable. {1}" -f $dataset.Id, ($warnings -join ' ')) } else { ("Dataset {0} contains train.txt, val.txt, test.txt and manifest.json." -f $dataset.Id) })
            Remediation = $(if ($resolution.Source -eq "fallback") { "No rebuild is required; start the task to repair latest.txt automatically." } else { "" })
            Dataset = $dataset
        }
    }
    catch {
        return [pscustomobject]@{
            Ready = $false
            Status = "FAIL"
            Message = $_.Exception.Message
            Remediation = "Inspect training\workspace\datasets and the latest.txt pointer."
            Dataset = $null
        }
    }
}

function Test-IsalaDatasetReady {
    param([switch]$RequireDictionary)
    return (Get-IsalaDatasetPreflightState -RequireDictionary:$RequireDictionary).Ready
}

function Add-IsalaDatasetCheckResult {
    param(
        [Parameter(Mandatory = $true)][System.Collections.ArrayList]$Results,
        [Parameter(Mandatory = $true)][string]$Scope,
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$RequireDictionary
    )
    $state = Get-IsalaDatasetPreflightState -RequireDictionary:$RequireDictionary
    [void]$Results.Add((New-IsalaCheckResult -Scope $Scope -Name $Name -Status $state.Status -Message $state.Message -Remediation $state.Remediation))
    return $state
}

function Test-IsalaLatestRunReady {
    try {
        $run = Get-LatestRunDirectory
        return (Test-Path -LiteralPath $run -PathType Container)
    }
    catch { return $false }
}

function Test-IsalaExportReady {
    try {
        $run = Get-LatestRunDirectory
        $null = Get-InferenceDirectory $run
        return $true
    }
    catch { return $false }
}

function Test-IsalaEvaluationReady {
    param([ValidateSet("baseline","custom")][string]$Kind)
    try {
        $null = Get-LatestEvaluationFile $Kind
        return $true
    }
    catch { return $false }
}

function Get-IsalaTrainingWeightPath {
    return (Join-Path $ProjectRoot "models\training\PP-OCRv6_medium_rec_pretrained.pdparams")
}

function Test-IsalaTrainingWeightReady {
    $path = Get-IsalaTrainingWeightPath
    try {
        return (Test-Path -LiteralPath $path -PathType Leaf) -and
            ((Get-Item -LiteralPath $path -ErrorAction Stop).Length -gt 1MB)
    }
    catch { return $false }
}

function Test-IsalaPretrainHostConnectivity {
    $hostName = "paddle-model-ecology.bj.bcebos.com"
    $client = $null
    try {
        $addresses = [System.Net.Dns]::GetHostAddresses($hostName)
        if ($null -eq $addresses -or $addresses.Count -eq 0) { return $false }
        $client = New-Object System.Net.Sockets.TcpClient
        $task = $client.ConnectAsync($hostName, 443)
        if (-not $task.Wait(10000)) { return $false }
        return $client.Connected
    }
    catch { return $false }
    finally { if ($client) { $client.Dispose() } }
}

function Invoke-IsalaContainerPermissionCheck {
    if (-not (Test-TrainingImagePrepared -Device cpu)) {
        return New-IsalaCheckResult -Scope "Permissions" -Name "Container bind mounts" -Status "SKIP" `
            -Message "The reusable CPU training image is not present yet." `
            -Remediation "Open Stap 1 · Voorbereiding and choose Alles voorbereiden. The permission check will then run inside UID/GID 10001:10001."
    }
    $result = Invoke-DockerWithTimeout -Arguments @(
        'compose','--profile','doctor','run','--rm','--pull','never',
        'workspace-doctor','check','--json'
    ) -TimeoutSeconds 90
    if ($null -ne $result -and -not $result.TimedOut -and $result.ExitCode -eq 0) {
        return New-IsalaCheckResult -Scope "Permissions" -Name "Container bind mounts" -Status "PASS" `
            -Message "Input is readable and output/models/training are writable as UID/GID 10001:10001."
    }
    $details = Get-IsalaProcessOutputText -Result $result -Fallback "The workspace doctor returned no output or process result."
    if ($null -ne $result -and $result.TimedOut) {
        $details = "The workspace doctor exceeded its 90-second timeout. " + $details
    }
    return New-IsalaCheckResult -Scope "Permissions" -Name "Container bind mounts" -Status "FAIL" `
        -Message $details -Remediation "Open Onderhoud, repair workspace permissions, then rerun the full check."
}

function Invoke-IsalaGpuRuntimeCheck {
    # Runtime CUDA validation is intentionally performed by paddlex_runner.py in
    # the actual trainer-gpu container. Keeping it out of Windows PowerShell 5.1
    # avoids Windows PowerShell process-object bugs while retaining fail-fast
    # behaviour before the first training epoch.
    if (-not (Test-TrainingImagePrepared -Device gpu)) {
        return New-IsalaCheckResult -Scope "GPU" -Name "PaddlePaddle CUDA runtime" -Status "FAIL" `
            -Message "The reusable GPU training image is missing." -Remediation "Open Stap 1 · Voorbereiding and choose Alles voorbereiden."
    }
    return New-IsalaCheckResult -Scope "GPU" -Name "PaddlePaddle CUDA runtime" -Status "PASS" `
        -Message "Deferred to trainer-gpu runtime; training will stop before epoch 1 if CUDA is unavailable."
}

function Add-IsalaCommonChecks {
    param(
        [System.Collections.ArrayList]$Results,
        [switch]$EnsureDocker,
        [switch]$AllowDockerFailure
    )

    $requiredFiles = @(
        "START.cmd",
        "project\VERSION",
        "project\TRAINING_IMAGE_VERSION",
        "application\pyproject.toml",
        "application\config\app.yaml",
        "infrastructure\docker\compose.yaml",
        "automation\powershell\training-menu.ps1",
        "automation\powershell\preflight.ps1",
        "automation\powershell\webui-worker.ps1",
        "application\src\isala_ocr\training\webui.py",
        "application\src\isala_ocr\training\webui_server.py",
        "automation\training_runtime\workspace_doctor.py"
    )
    $missing = @($requiredFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $ProjectRoot $_) -PathType Leaf) })
    if ($missing.Count -eq 0) {
        [void]$Results.Add((New-IsalaCheckResult -Scope "Project" -Name "Required files" -Status "PASS" -Message "All required project files are present."))
    } else {
        [void]$Results.Add((New-IsalaCheckResult -Scope "Project" -Name "Required files" -Status "FAIL" -Message ("Missing: " + ($missing -join ', ')) -Remediation "Reinstall the complete release ZIP."))
    }

    $actionScripts = @((Get-IsalaActionCatalog).Values | ForEach-Object { $_.Script } | Select-Object -Unique)
    $missingActionScripts = @($actionScripts | Where-Object { -not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $_) -PathType Leaf) })
    if ($missingActionScripts.Count -eq 0) {
        [void]$Results.Add((New-IsalaCheckResult -Scope "Project" -Name "All action scripts" -Status "PASS" -Message ("{0} unique action scripts are present." -f $actionScripts.Count)))
    } else {
        [void]$Results.Add((New-IsalaCheckResult -Scope "Project" -Name "All action scripts" -Status "FAIL" -Message ("Missing: " + ($missingActionScripts -join ', ')) -Remediation "Reinstall the complete release ZIP."))
    }

    $rootFiles = @(Get-ChildItem -LiteralPath $ProjectRoot -File -Force -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)
    $allowedRootFiles = @("START.cmd", ".gitignore", ".gitattributes")
    $unexpected = @($rootFiles | Where-Object { $allowedRootFiles -notcontains $_ })
    if ($unexpected.Count -eq 0) {
        [void]$Results.Add((New-IsalaCheckResult -Scope "Project" -Name "Clean project root" -Status "PASS" -Message "Only START.cmd and standard Git metadata files are present in the project root."))
    } else {
        [void]$Results.Add((New-IsalaCheckResult -Scope "Project" -Name "Clean project root" -Status "WARN" -Message ("Unexpected root files: " + ($unexpected -join ', ')) -Remediation "Move operational files into the supplied subdirectories."))
    }

    if ($PSVersionTable.PSVersion.Major -ge 5) {
        [void]$Results.Add((New-IsalaCheckResult -Scope "Host" -Name "PowerShell" -Status "PASS" -Message ("PowerShell {0}" -f $PSVersionTable.PSVersion)))
    } else {
        [void]$Results.Add((New-IsalaCheckResult -Scope "Host" -Name "PowerShell" -Status "FAIL" -Message "PowerShell 5.1 or newer is required."))
    }

    foreach ($relative in @("output","models","models\training","training","training\workspace","training\workspace\webui\jobs","training\registry")) {
        $path = Join-Path $ProjectRoot $relative
        if (Test-IsalaHostDirectoryWritable -Path $path) {
            [void]$Results.Add((New-IsalaCheckResult -Scope "Permissions" -Name $relative -Status "PASS" -Message "Writable from Windows."))
        } else {
            [void]$Results.Add((New-IsalaCheckResult -Scope "Permissions" -Name $relative -Status "FAIL" -Message "Not writable from Windows." -Remediation "Check NTFS permissions and read-only attributes."))
        }
    }

    foreach ($projectPathInfo in @(
        @{ Name = "Project workspace"; Path = (Get-IsalaHostProjectWorkspace) },
        @{ Name = "Project runs"; Path = (Join-Path (Get-IsalaHostProjectWorkspace) "runs") },
        @{ Name = "Project registry"; Path = (Get-IsalaHostProjectRegistry) }
    )) {
        $path = [string]$projectPathInfo.Path
        New-Item -ItemType Directory -Path $path -Force | Out-Null
        if (Test-IsalaHostDirectoryWritable -Path $path) {
            [void]$Results.Add((New-IsalaCheckResult -Scope "Permissions" -Name ([string]$projectPathInfo.Name) -Status "PASS" -Message ("{0} | project={1}" -f $path,(Get-IsalaActiveProjectId))))
        } else {
            [void]$Results.Add((New-IsalaCheckResult -Scope "Permissions" -Name ([string]$projectPathInfo.Name) -Status "FAIL" -Message $path -Remediation "Check project workspace permissions."))
        }
    }

    $driveRoot = [IO.Path]::GetPathRoot($ProjectRoot)
    $driveName = if ($driveRoot -and $driveRoot.Length -ge 1) { $driveRoot.Substring(0, 1) } else { "" }
    $drive = if ($driveName) { Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue } else { $null }
    if ($drive) {
        $freeGb = [Math]::Round($drive.Free / 1GB, 1)
        $status = if ($freeGb -lt 15) { "FAIL" } elseif ($freeGb -lt 40) { "WARN" } else { "PASS" }
        [void]$Results.Add((New-IsalaCheckResult -Scope "Storage" -Name "Project drive free space" -Status $status -Message ("{0} GB free on {1}" -f $freeGb, $drive.Root) -Remediation "Keep Docker data on a drive with sufficient free space."))
    }

    if (-not (Get-Command 'docker.exe' -ErrorAction SilentlyContinue)) {
        $dockerStatus = if ($AllowDockerFailure) { "WARN" } else { "FAIL" }
        [void]$Results.Add((New-IsalaCheckResult -Scope "Docker" -Name "Docker CLI" -Status $dockerStatus -Message "docker.exe was not found." -Remediation "Install Docker Desktop or add it to PATH."))
        return
    }
    [void]$Results.Add((New-IsalaCheckResult -Scope "Docker" -Name "Docker CLI" -Status "PASS" -Message "docker.exe is available."))

    if ($EnsureDocker) {
        try {
            Assert-Docker
            [void]$Results.Add((New-IsalaCheckResult -Scope "Docker" -Name "Docker Engine" -Status "PASS" -Message "Docker Desktop Linux engine is ready."))
        } catch {
            $dockerStatus = if ($AllowDockerFailure) { "WARN" } else { "FAIL" }
            [void]$Results.Add((New-IsalaCheckResult -Scope "Docker" -Name "Docker Engine" -Status $dockerStatus -Message $_.Exception.Message -Remediation "Restart Docker Desktop; if needed run wsl --shutdown."))
            return
        }
    } else {
        $docker = Invoke-DockerWithTimeout -Arguments @('version') -TimeoutSeconds 20
        if (Test-DockerEngineResult $docker) {
            [void]$Results.Add((New-IsalaCheckResult -Scope "Docker" -Name "Docker Engine" -Status "PASS" -Message "Docker Desktop Linux engine is ready."))
        } else {
            $dockerStatus = if ($AllowDockerFailure) { "WARN" } else { "FAIL" }
            [void]$Results.Add((New-IsalaCheckResult -Scope "Docker" -Name "Docker Engine" -Status $dockerStatus -Message "Docker Desktop is not ready." -Remediation "Start or restart Docker Desktop."))
            return
        }
    }

    $compose = Invoke-DockerWithTimeout -Arguments @('compose','config','--quiet') -TimeoutSeconds 45
    if ($null -ne $compose -and -not $compose.TimedOut -and $compose.ExitCode -eq 0) {
        [void]$Results.Add((New-IsalaCheckResult -Scope "Docker" -Name "Compose configuration" -Status "PASS" -Message "compose.yaml is valid."))
    } else {
        $details = Get-IsalaProcessOutputText -Result $compose -Fallback "docker compose config failed without diagnostic output."
        [void]$Results.Add((New-IsalaCheckResult -Scope "Docker" -Name "Compose configuration" -Status "FAIL" -Message $details -Remediation "Reinstall the release or correct compose.yaml."))
    }
}

function Add-IsalaActionChecks {
    param(
        [System.Collections.ArrayList]$Results,
        [Parameter(Mandatory = $true)][string]$ActionId,
        [switch]$IncludeContainerChecks
    )
    $catalog = Get-IsalaActionCatalog
    if (-not $catalog.Contains($ActionId)) { throw "Unknown action ID: $ActionId" }
    $profile = $catalog[$ActionId].Profile
    $scope = "Taak: $($catalog[$ActionId].Name)"
    $ProjectWorkspace = Get-IsalaHostProjectWorkspace
    $ProjectRegistry = Get-IsalaHostProjectRegistry

    switch ($profile) {
        "prepare" {
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Preparation targets" -Status "PASS" -Message "Model and training caches may be created or reused."))
            if (Test-IsalaTrainingWeightReady) {
                [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Pretrained weight" -Status "PASS" -Message ((Get-IsalaTrainingWeightPath) + " is already cached; network access is not required for this artifact.")))
            }
            else {
                $reachable = Test-IsalaPretrainHostConnectivity
                [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Pretrained-weight source" -Status $(if ($reachable) {"PASS"} else {"FAIL"}) -Message $(if ($reachable) {"Official model host resolves and accepts TCP 443 from Windows. Docker connectivity is verified again with the model-prep container before download."} else {"Official model host is not reachable on TCP 443 and the pretrained weight is not cached."}) -Remediation "Restore internet access, DNS or proxy settings, then rerun Alles voorbereiden in Stap 1 · Voorbereiding."))
            }
        }
        "prepare-inference" {
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Inference/table cache" -Status "PASS" -Message "PP-OCRv6 and table/inference models may be downloaded or reused independently."))
        }
        "prepare-cpu-detection" {
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "CPU detector image" -Status "PASS" -Message "CPU PaddleDetection/PicoDet image and baseline cache may be built or reused independently."))
        }
        "prepare-gpu-recognition" {
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "GPU recognition image" -Status "PASS" -Message "Recognition-only GPU image may be built without PaddleDetection."))
        }
        "prepare-gpu-detection" {
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "GPU detector image" -Status "PASS" -Message "Dedicated PaddleDetection/PicoDet GPU image may be built independently."))
        }
        "preparation-status" {
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Preparation status" -Status "PASS" -Message "Model files and versioned Docker image tags will be checked without downloading or rebuilding anything."))
        }
        "prepare-pretrained" {
            $cpu = Test-TrainingImagePrepared -Device cpu
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "CPU validation image" -Status $(if ($cpu) {"PASS"} else {"FAIL"}) -Message (Get-TrainingImageName -Device cpu) -Remediation "Open Stap 1 · Voorbereiding and install CPU detector / PicoDet-S first."))
            if (Test-IsalaTrainingWeightReady) {
                [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Pretrained weight" -Status "PASS" -Message ((Get-IsalaTrainingWeightPath) + " is already cached.")))
            }
            else {
                $reachable = Test-IsalaPretrainHostConnectivity
                [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Pretrained-weight source" -Status $(if ($reachable) {"PASS"} else {"FAIL"}) -Message $(if ($reachable) {"Official model host is reachable."} else {"Official model host is not reachable and the weight is not cached."}) -Remediation "Restore internet access, then install PP-OCRv6 pretrained gewicht again in Stap 1 · Voorbereiding."))
            }
        }
        { $_ -match '^prepare-(all-(download|install|check)|.+-(download|install|check))$' } {
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Preparation phase" -Status "PASS" -Message "This preparation phase can be executed independently; dependencies are verified again by the phase script."))
        }
        "webui-start" {
            $server = Join-Path $ProjectRoot "application\src\isala_ocr\training\webui_server.py"
            $worker = Join-Path $PSScriptRoot "webui-worker.ps1"
            $serverReady = Test-Path -LiteralPath $server -PathType Leaf
            $workerReady = Test-Path -LiteralPath $worker -PathType Leaf
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Web interface server" -Status $(if ($serverReady) {"PASS"} else {"FAIL"}) -Message $server -Remediation "Reinstall the complete release ZIP."))
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "PowerShell worker" -Status $(if ($workerReady) {"PASS"} else {"FAIL"}) -Message $worker -Remediation "Reinstall the complete release ZIP."))
        }
        "collect" {
            $count = Get-IsalaInputFileCount
            $status = if ($count -gt 0) { "PASS" } else { "FAIL" }
            $projectInput = Get-IsalaHostProjectInput
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Project input files" -Status $status -Message ("{0} processable input files found in {1}." -f $count,$projectInput) -Remediation ("Place this project's DICOM/images under '{0}'." -f $projectInput)))
            $manifest = Join-Path $ProjectRoot "models\paddlex\isala_ocr_model_manifest.json"
            $status = if (Test-Path -LiteralPath $manifest -PathType Leaf) { "PASS" } else { "FAIL" }
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Inference model cache" -Status $status -Message $manifest -Remediation "Open Stap 1 · Voorbereiding and install Inference OCR + tabelmodellen, or choose Alles voorbereiden."))
        }
        "table-cell-build" {
            $database = Join-Path $ProjectWorkspace "samples.sqlite3"
            $ready = Test-Path -LiteralPath $database -PathType Leaf
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Completed table reviews" -Status $(if ($ready) {"PASS"} else {"FAIL"}) -Message $database -Remediation "Run table detection and complete the table-cell review first."))
        }
        "table-cell-check" {
            $pointer = Join-Path $ProjectWorkspace "table_cell_datasets\latest.txt"
            $ready = Test-Path -LiteralPath $pointer -PathType Leaf
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Table-cell dataset" -Status $(if ($ready) {"PASS"} else {"FAIL"}) -Message $pointer -Remediation "Build the table-cell dataset first."))
        }
        "table-cell-train" {
            $pointer = Join-Path $ProjectWorkspace "table_cell_datasets\latest.txt"
            $ready = Test-Path -LiteralPath $pointer -PathType Leaf
            $message = $pointer
            if ($ready) {
                try {
                    $datasetId = ([string](Get-Content -LiteralPath $pointer -Raw)).Trim()
                    $validationPath = Join-Path $ProjectWorkspace ("table_cell_datasets\{0}\validation.json" -f $datasetId)
                    $validation = if (Test-Path -LiteralPath $validationPath) { Get-Content -LiteralPath $validationPath -Raw | ConvertFrom-Json } else { $null }
                    $ready = ($null -ne $validation -and [bool]$validation.valid)
                    $message = $validationPath
                } catch { $ready = $false }
            }
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Validated table-cell dataset" -Status $(if ($ready) {"PASS"} else {"FAIL"}) -Message $message -Remediation "Build and validate the table-cell dataset first. The training action prepares its GPU/CPU runtime automatically when necessary."))
        }
        "table-cell-activate" {
            $pointer = Join-Path $ProjectWorkspace "table_cell_models\latest.txt"
            $ready = Test-Path -LiteralPath $pointer -PathType Leaf
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Trained table-cell model" -Status $(if ($ready) {"PASS"} else {"FAIL"}) -Message $pointer -Remediation "Train the wireless table-cell detector first."))
        }
        "localization-build" {
            $database = Join-Path $ProjectWorkspace "samples.sqlite3"
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Detection review database" -Status $(if (Test-Path $database) {"PASS"} else {"FAIL"}) -Message $database -Remediation "Run Stap 2 · Tabelstructuur detecteren and review the cells in Stap 3 · Tabelcellen reviewen."))
            $renders = Join-Path $ProjectWorkspace "source_renders"
            $count = if (Test-Path $renders) { @(Get-ChildItem $renders -Filter '*.png' -File -ErrorAction SilentlyContinue).Count } else { 0 }
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Full source renders" -Status $(if ($count -gt 0) {"PASS"} else {"FAIL"}) -Message ("{0} source render(s)." -f $count) -Remediation "Run Stap 2 · Tabelstructuur detecteren."))
        }
        "localization-check" {
            $pointer = Join-Path $ProjectWorkspace "localization_datasets\latest.txt"
            $ready = Test-Path -LiteralPath $pointer -PathType Leaf
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Localization dataset pointer" -Status $(if ($ready) {"PASS"} else {"FAIL"}) -Message $pointer -Remediation "Open de geparkeerde fallbackpagina Losse box-detector trainen en bouw de localization-dataset."))
        }
        { $_ -in @("localization-train-gpu","localization-train-cpu") } {
            $pointer = Join-Path $ProjectWorkspace "localization_datasets\latest.txt"
            $datasetReady = Test-Path -LiteralPath $pointer -PathType Leaf
            $validationReady = $false
            $paddlexValidationReady = $false
            $splitManifestReady = $false
            $trainingReadyMarker = $false
            $datasetId = ""
            $validationPath = ""
            $paddlexValidationPath = ""
            if ($datasetReady) {
                try {
                    $datasetId = ([string](Get-Content -LiteralPath $pointer -Raw -ErrorAction Stop)).Trim()
                    if (-not [string]::IsNullOrWhiteSpace($datasetId)) {
                        $datasetRoot = Join-Path $ProjectWorkspace ("localization_datasets\{0}" -f $datasetId)
                        $validationPath = Join-Path $datasetRoot "validation.json"
                        if (Test-Path -LiteralPath $validationPath -PathType Leaf) {
                            $validation = Get-Content -LiteralPath $validationPath -Raw | ConvertFrom-Json
                            $validationReady = (([string]$validation.status -eq "ok") -and ([string]$validation.dataset_id -eq $datasetId))
                        }
                        $paddlexValidationPath = Join-Path $datasetRoot "paddlex_validation\isala_paddlex_validation.json"
                        if (Test-Path -LiteralPath $paddlexValidationPath -PathType Leaf) {
                            $paddlexValidation = Get-Content -LiteralPath $paddlexValidationPath -Raw | ConvertFrom-Json
                            $paddlexStatusReady = (([string]$paddlexValidation.status -eq "ok") -or (($null -ne $paddlexValidation.ok) -and [bool]$paddlexValidation.ok))
                            $paddlexDatasetLeaf = ""
                            try { $paddlexDatasetLeaf = Split-Path -Leaf ([string]$paddlexValidation.dataset).TrimEnd('\','/') } catch { }
                            $paddlexValidationReady = $paddlexStatusReady -and ($paddlexDatasetLeaf -eq $datasetId)
                        }
                        $manifestPath = Join-Path $datasetRoot "manifest.json"
                        if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
                            $datasetManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
                            if ($null -ne $datasetManifest.source_splits) {
                                $splitManifestReady = @($datasetManifest.source_splits.PSObject.Properties).Count -gt 0
                            }
                        }
                        $readyMarkerPath = Join-Path $datasetRoot "training_ready.json"
                        if (Test-Path -LiteralPath $readyMarkerPath -PathType Leaf) {
                            $readyMarker = Get-Content -LiteralPath $readyMarkerPath -Raw | ConvertFrom-Json
                            $trainingReadyMarker = (([string]$readyMarker.status -eq "ok") -and [bool]$readyMarker.ready -and ([string]$readyMarker.dataset_id -eq $datasetId))
                        }
                    }
                } catch {
                    $validationReady = $false
                    $paddlexValidationReady = $false
                    $splitManifestReady = $false
                    $trainingReadyMarker = $false
                }
            }
            $splitPendingPath = Join-Path $ProjectWorkspace "localization_split_pending.flag"
            $splitCurrent = $splitManifestReady -and -not (Test-Path -LiteralPath $splitPendingPath -PathType Leaf)
            # Legacy datasets validated before v3.8.19 remain eligible when both
            # concrete validation reports are valid. New validations also write a
            # canonical training_ready.json marker to remove ambiguity.
            $allValidated = $datasetReady -and $validationReady -and $paddlexValidationReady -and $splitCurrent
            $stateMessage = ("dataset={0}; pointer={1}; app={2}; PaddleX={3}; split_current={4}; ready_marker={5}" -f $(if($datasetId){$datasetId}else{"<none>"}),$datasetReady,$validationReady,$paddlexValidationReady,$splitCurrent,$trainingReadyMarker)
            $remediation = if (-not $datasetReady) {
                "Open de geparkeerde fallbackpagina Losse box-detector trainen en bouw een dataset."
            } elseif (-not $validationReady -or -not $paddlexValidationReady) {
                ("Open de geparkeerde fallbackpagina Losse box-detector trainen en valideer de HUIDIGE dataset '{0}'. Do not rely on validation from an older loc-* dataset." -f $datasetId)
            } elseif (-not $splitCurrent) {
                "De split is gewijzigd. Bouw en valideer de dataset opnieuw via de geparkeerde box-detectorfallback."
            } else { "Open de geparkeerde fallbackpagina Losse box-detector trainen." }
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Validated localization dataset" -Status $(if ($allValidated) {"PASS"} else {"FAIL"}) -Message $stateMessage -Remediation $remediation))
            $device = if ($profile -eq "localization-train-gpu") { "gpu-detection" } else { "cpu" }
            $imageReady = Test-TrainingImagePrepared -Device $device
            $prepareTask = if ($device -eq "gpu-detection") { "GPU PaddleDetection / PicoDet-S" } else { "CPU detector / PicoDet-S" }
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name ("{0} training image" -f $device.ToUpperInvariant()) -Status $(if ($imageReady) {"PASS"} else {"FAIL"}) -Message (Get-TrainingImageName -Device $device) -Remediation ("Open Stap 1 · Voorbereiding and install {0}, or choose Alles voorbereiden." -f $prepareTask)))
        }
        "localization-baseline" {
            $database = Join-Path $ProjectWorkspace "samples.sqlite3"
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Reviewed localization ground truth" -Status $(if (Test-Path $database) {"PASS"} else {"FAIL"}) -Message $database -Remediation "Review detection candidates first."))
        }
        "localization-compare" {
            $root = Join-Path $ProjectWorkspace "localization_evaluations"
            $count = if (Test-Path $root) { @(Get-ChildItem $root -Directory -Filter 'loc-eval-*' -ErrorAction SilentlyContinue).Count } else { 0 }
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Localization evaluations" -Status $(if ($count -ge 2) {"PASS"} else {"FAIL"}) -Message ("{0} evaluation run(s)." -f $count) -Remediation "Gebruik de geparkeerde fallbackpagina Box-detector evalueren nadat de fallback-detector is getraind."))
        }
        "localization-activate" {
            $selectionPath = Join-Path $ProjectWorkspace "localization_artifact_selection.json"
            $selectedReady = $false
            $selectedMessage = $selectionPath
            if (Test-Path -LiteralPath $selectionPath -PathType Leaf) {
                try {
                    $selected = Get-Content -LiteralPath $selectionPath -Raw | ConvertFrom-Json
                    $selectedModelId = [string]$selected.model.model_id
                    $selectedModelPath = [string]$selected.model.path
                    $selectedReady = -not [string]::IsNullOrWhiteSpace($selectedModelId) -and -not [string]::IsNullOrWhiteSpace($selectedModelPath)
                    if ($selectedReady) { $selectedMessage = ("selected={0}; path={1}" -f $selectedModelId,$selectedModelPath) }
                } catch { $selectedReady = $false }
            }
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Selected field detector" -Status $(if ($selectedReady) {"PASS"} else {"FAIL"}) -Message $selectedMessage -Remediation "Open de geparkeerde fallbackpagina Box-detector evalueren of Projecten & modellen en selecteer de detector die je wilt activeren."))
        }
        "localization-redetect" {
            $active = Join-Path $ProjectWorkspace "localization_models\active.json"
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Active field detector" -Status $(if (Test-Path $active) {"PASS"} else {"FAIL"}) -Message $active -Remediation "Activeer de detector via de geparkeerde fallback nadat de detector-kwaliteitspoort slaagt."))
        }
        "localization-report" {
            $database = Join-Path $ProjectWorkspace "samples.sqlite3"
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Localization database" -Status $(if (Test-Path $database) {"PASS"} else {"FAIL"}) -Message $database -Remediation "Run detection and review first."))
        }
        "mapping-prepare" {
            $database = Join-Path $ProjectWorkspace "samples.sqlite3"
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Detection-gate database" -Status $(if (Test-Path $database) {"PASS"} else {"FAIL"}) -Message $database -Remediation "Finish Pipeline A first. The CLI performs the authoritative gate check."))
        }
        "mapping-apply" {
            $database = Join-Path $ProjectWorkspace "samples.sqlite3"
            $status = if (Test-Path -LiteralPath $database -PathType Leaf) { "PASS" } else { "FAIL" }
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Mapping database" -Status $status -Message $database -Remediation "Run generic detection and confirm mappings first."))
            $renders = Join-Path $ProjectWorkspace "source_renders"
            $renderCount = if (Test-Path -LiteralPath $renders -PathType Container) { @(Get-ChildItem -LiteralPath $renders -Filter '*.png' -File -ErrorAction SilentlyContinue).Count } else { 0 }
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Source renders" -Status $(if ($renderCount -gt 0) { "PASS" } else { "FAIL" }) -Message ("{0} render(s) available." -f $renderCount) -Remediation "Run Stap 2 · Tabelstructuur detecteren first."))
        }
        "value-read" {
            $database = Join-Path $ProjectWorkspace "samples.sqlite3"
            $status = if (Test-Path -LiteralPath $database -PathType Leaf) { "PASS" } else { "FAIL" }
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "ROI review database" -Status $status -Message $database -Remediation "Apply mappings and approve ROI crops first."))
            $manifest = Join-Path $ProjectRoot "models\paddlex\isala_ocr_model_manifest.json"
            $status = if (Test-Path -LiteralPath $manifest -PathType Leaf) { "PASS" } else { "FAIL" }
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Inference model cache" -Status $status -Message $manifest -Remediation "Open Stap 1 · Voorbereiding and choose Alles voorbereiden."))
        }
        "label" {
            $database = Join-Path $ProjectWorkspace "samples.sqlite3"
            $status = if (Test-Path -LiteralPath $database -PathType Leaf) { "PASS" } else { "FAIL" }
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Label database" -Status $status -Message $database -Remediation "Run Stap 2 · Tabelstructuur detecteren first."))
        }
        "dataset-build" {
            $database = Join-Path $ProjectWorkspace "samples.sqlite3"
            $status = if (Test-Path -LiteralPath $database -PathType Leaf) { "PASS" } else { "FAIL" }
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Reviewed labels database" -Status $status -Message $database -Remediation "Collect and review labels first."))
        }
        "dataset-check" {
            $null = Add-IsalaDatasetCheckResult -Results $Results -Scope $scope -Name "Latest dataset"
            $cpu = Test-TrainingImagePrepared -Device cpu
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "CPU training image" -Status $(if ($cpu) {"PASS"} else {"FAIL"}) -Message (Get-TrainingImageName -Device cpu) -Remediation "Open Stap 1 · Voorbereiding and install CPU detector / PicoDet-S, or choose Alles voorbereiden."))
        }
        "baseline" {
            $null = Add-IsalaDatasetCheckResult -Results $Results -Scope $scope -Name "Untouched test dataset"
            $model = Join-Path $ProjectRoot "models\paddlex\official_models\PP-OCRv6_medium_rec"
            $ready = (Test-Path -LiteralPath $model -PathType Container) -and (@(Get-ChildItem $model -File -ErrorAction SilentlyContinue).Count -gt 0)
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Official baseline model" -Status $(if ($ready) {"PASS"} else {"FAIL"}) -Message $model -Remediation "Open Stap 1 · Voorbereiding and choose Alles voorbereiden."))
        }
        "train-gpu" {
            $datasetState = Add-IsalaDatasetCheckResult -Results $Results -Scope $scope -Name "Training dataset" -RequireDictionary
            $weight = Get-IsalaTrainingWeightPath
            $weightReady = Test-IsalaTrainingWeightReady
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Pretrained weights" -Status $(if ($weightReady) {"PASS"} else {"FAIL"}) -Message $weight -Remediation "Open Stap 1 · Voorbereiding and install PP-OCRv6 pretrained gewicht, or choose Alles voorbereiden."))
            $gpu = Test-TrainingImagePrepared -Device gpu
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "GPU training image" -Status $(if ($gpu) {"PASS"} else {"FAIL"}) -Message (Get-TrainingImageName -Device gpu) -Remediation "Open Stap 1 · Voorbereiding and install GPU OCR-recognition, or choose Alles voorbereiden."))

            # Do not start an expensive container runtime probe when a preceding
            # dataset, dictionary, weight or image prerequisite already blocks
            # training. This keeps the report deterministic and prevents a GPU
            # probe problem from hiding the actionable prerequisite failure.
            if ($IncludeContainerChecks -and $datasetState.Ready -and $weightReady -and $gpu) {
                # Do not launch a second Compose container from the PowerShell 5.1
                # preflight. On some Docker Desktop installations Start-Process
                # returns an incomplete process object for GPU-enabled Compose runs,
                # which caused the checker itself to terminate with a null-expression
                # error. The actual training command performs the authoritative CUDA
                # runtime verification inside trainer-gpu before any epoch starts.
                [void]$Results.Add((New-IsalaCheckResult -Scope "GPU" -Name "PaddlePaddle CUDA runtime" -Status "PASS" `
                    -Message "GPU image is present. CUDA verification is deferred to the trainer-gpu runtime immediately before training."))
            }
            elseif ($IncludeContainerChecks) {
                [void]$Results.Add((New-IsalaCheckResult -Scope "GPU" -Name "PaddlePaddle CUDA runtime" -Status "SKIP" `
                    -Message "GPU runtime verification skipped because an earlier training prerequisite failed." `
                    -Remediation "Resolve the failed dataset, dictionary, weight or image check, then rerun Stap 19 · Recognition-model trainen."))
            }
        }
        "train-cpu" {
            $null = Add-IsalaDatasetCheckResult -Results $Results -Scope $scope -Name "Training dataset" -RequireDictionary
            $weight = Get-IsalaTrainingWeightPath
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Pretrained weights" -Status $(if (Test-IsalaTrainingWeightReady) {"PASS"} else {"FAIL"}) -Message $weight -Remediation "Open Stap 1 · Voorbereiding and choose Alles voorbereiden."))
            $cpu = Test-TrainingImagePrepared -Device cpu
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "CPU training image" -Status $(if ($cpu) {"PASS"} else {"FAIL"}) -Message (Get-TrainingImageName -Device cpu) -Remediation "Open Stap 1 · Voorbereiding and install CPU detector / PicoDet-S, or choose Alles voorbereiden."))
        }
        "export" {
            $run = Test-IsalaLatestRunReady
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Training run" -Status $(if ($run) {"PASS"} else {"FAIL"}) -Message "Latest run directory." -Remediation "Run Stap 19 · Recognition-model trainen."))
            $gpu = Test-TrainingImagePrepared -Device gpu
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Default export image" -Status $(if ($gpu) {"PASS"} else {"FAIL"}) -Message (Get-TrainingImageName -Device gpu) -Remediation "Open Stap 1 · Voorbereiding and choose Alles voorbereiden, or use the legacy CPU export path explicitly."))
        }
        "custom" {
            $export = Test-IsalaExportReady
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Custom inference model" -Status $(if ($export) {"PASS"} else {"FAIL"}) -Message "Exported model under latest run." -Remediation "Run Stap 19 · Recognition-model trainen/exporteren."))
        }
        "compare" {
            foreach ($kind in @("baseline","custom")) {
                $ready = Test-IsalaEvaluationReady -Kind $kind
                [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name ("{0} evaluation" -f $kind) -Status $(if ($ready) {"PASS"} else {"FAIL"}) -Message "evaluation.json" -Remediation $(if ($kind -eq "baseline") {"Run Stap 20 · Recognition-model evalueren."} else {"Run Stap 20 · Recognition-model evalueren."})))
            }
        }
        "register" {
            $custom = Test-IsalaEvaluationReady -Kind custom
            $export = Test-IsalaExportReady
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Custom evaluation" -Status $(if ($custom) {"PASS"} else {"FAIL"}) -Message "Latest custom evaluation." -Remediation "Run Stap 20 · Recognition-model evalueren."))
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Exported custom model" -Status $(if ($export) {"PASS"} else {"FAIL"}) -Message "Latest exported inference model." -Remediation "Run Stap 19 · Recognition-model trainen/exporteren."))
        }
        "activate" {
            $registry = Join-Path $ProjectRegistry "models"
            $count = if (Test-Path $registry) { @(Get-ChildItem $registry -Directory -ErrorAction SilentlyContinue).Count } else { 0 }
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Registered models" -Status $(if ($count -gt 0) {"PASS"} else {"FAIL"}) -Message ("{0} registered model(s)." -f $count) -Remediation "Run Stap 20 · Recognition-model activeren."))
        }
        "recognition-train" {
            $null = Add-IsalaDatasetCheckResult -Results $Results -Scope $scope -Name "Recognition dataset" -RequireDictionary
            $gpu = Test-TrainingImagePrepared -Device gpu
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "GPU training image" -Status $(if ($gpu) {"PASS"} else {"FAIL"}) -Message (Get-TrainingImageName -Device gpu) -Remediation "Open Stap 1 · Voorbereiding and install GPU OCR-recognition, or choose Alles voorbereiden."))
        }
        "recognition-evaluate" {
            $null = Add-IsalaDatasetCheckResult -Results $Results -Scope $scope -Name "Recognition test dataset"
        }
        "recognition-register" {
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Recognition evaluation/export" -Status "PASS" -Message "Stap 20 · Recognition-model activeren validates the latest custom evaluation and export before activation."))
        }
        default {
            [void]$Results.Add((New-IsalaCheckResult -Scope $scope -Name "Task prerequisites" -Status "PASS" -Message "No additional data prerequisites."))
        }
    }
}

function Write-IsalaCheckResults {
    param([Parameter(Mandatory = $true)]$Results)
    Write-Host ""
    Write-Host "IsalaOCR prerequisite check" -ForegroundColor Cyan
    Write-Host ""
    foreach ($item in $Results) {
        $color = switch ($item.Status) { "PASS" {"Green"} "WARN" {"Yellow"} "FAIL" {"Red"} default {"DarkGray"} }
        Write-Host ("[{0}] {1} / {2}: {3}" -f $item.Status, $item.Scope, $item.Name, $item.Message) -ForegroundColor $color
        if ($item.Status -in @("WARN","FAIL") -and $item.Remediation) {
            Write-Host ("      Fix: {0}" -f $item.Remediation) -ForegroundColor DarkYellow
        }
    }
    $fail = @($Results | Where-Object Status -eq "FAIL").Count
    $warn = @($Results | Where-Object Status -eq "WARN").Count
    $pass = @($Results | Where-Object Status -eq "PASS").Count
    Write-Host ""
    Write-Host ("Summary: {0} passed, {1} warnings, {2} failed." -f $pass, $warn, $fail) -ForegroundColor $(if ($fail -gt 0) {"Red"} elseif ($warn -gt 0) {"Yellow"} else {"Green"})
}

function Save-IsalaCheckReport {
    param([Parameter(Mandatory = $true)]$Results, [string]$Name = "system-check")
    try {
        $directory = Join-Path $ProjectRoot "training\workspace\diagnostics"
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
        $stamp = Get-Date -Format "yyyyMMddTHHmmss"
        $path = Join-Path $directory ("{0}-{1}.json" -f $Name, $stamp)
        $payload = [ordered]@{
            generated_at = (Get-Date).ToString("o")
            project_version = (Get-Content (Join-Path $ProjectMetadataRoot "VERSION") -Raw).Trim()
            project_root = $ProjectRoot
            results = @($Results)
        }
        $payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $path -Encoding UTF8
        Write-Host "Report: $path" -ForegroundColor DarkGray
        return $path
    }
    catch {
        Write-Warning "The check completed, but its JSON report could not be saved: $($_.Exception.Message)"
        return $null
    }
}

function Invoke-IsalaPreflight {
    param(
        [string]$ActionId = "",
        [switch]$AllActions,
        [switch]$EnsureDocker,
        [switch]$AllowDockerFailure,
        [switch]$SaveReport
    )
    $results = New-Object System.Collections.ArrayList
    try {
        Add-IsalaCommonChecks -Results $results -EnsureDocker:$EnsureDocker -AllowDockerFailure:$AllowDockerFailure
    }
    catch {
        [void]$results.Add((New-IsalaCheckResult -Scope "System" -Name "Common preflight implementation" -Status "FAIL" `
            -Message $_.Exception.Message -Remediation "Install the latest complete release; the common checker failed before any task was executed."))
    }

    $dockerFailed = @($results | Where-Object { $_.Scope -eq "Docker" -and $_.Status -eq "FAIL" }).Count -gt 0
    $commonFailed = @($results | Where-Object { $_.Scope -eq "System" -and $_.Status -eq "FAIL" }).Count -gt 0
    if (-not $dockerFailed -and -not $commonFailed) {
        if ($AllActions) {
            foreach ($id in (Get-IsalaActionCatalog).Keys) {
                try {
                    Add-IsalaActionChecks -Results $results -ActionId $id -IncludeContainerChecks
                }
                catch {
                    [void]$results.Add((New-IsalaCheckResult -Scope "Taakcontrole" -Name "Preflight implementation" -Status "FAIL" `
                        -Message $_.Exception.Message -Remediation "Install the latest complete release; the checker itself failed before the task was executed."))
                }
            }
            try {
                [void]$results.Add((Invoke-IsalaContainerPermissionCheck))
            }
            catch {
                [void]$results.Add((New-IsalaCheckResult -Scope "Permissions" -Name "Container bind mounts" -Status "FAIL" `
                    -Message $_.Exception.Message -Remediation "Install the latest complete release or inspect the Docker workspace-doctor service."))
            }
        } elseif ($ActionId) {
            try {
                Add-IsalaActionChecks -Results $results -ActionId $ActionId -IncludeContainerChecks
            }
            catch {
                [void]$results.Add((New-IsalaCheckResult -Scope "Taakcontrole" -Name "Preflight implementation" -Status "FAIL" `
                    -Message $_.Exception.Message -Remediation "Install the latest complete release; the checker itself failed before the task was executed."))
            }
            if ($ActionId -in @("1","2","3","5","6","7","8","11","12","14","15","16","17","18","20","21","22","24","25","26","27","28","30","31","32","33","34","35","36","37","38","39","40","41","42","43","44","45","46","47","48","49","50","51","52")) {
                try {
                    [void]$results.Add((Invoke-IsalaContainerPermissionCheck))
                }
                catch {
                    [void]$results.Add((New-IsalaCheckResult -Scope "Permissions" -Name "Container bind mounts" -Status "FAIL" `
                        -Message $_.Exception.Message -Remediation "Install the latest complete release or inspect the Docker workspace-doctor service."))
                }
            }
        }
    }

    Write-IsalaCheckResults -Results $results
    if ($SaveReport) {
        $reportName = if ($AllActions) { "system-check" } else { "action-$ActionId-check" }
        Save-IsalaCheckReport -Results $results -Name $reportName | Out-Null
    }
    return [pscustomobject]@{
        Results = @($results)
        Passed = (@($results | Where-Object Status -eq "FAIL").Count -eq 0)
        WarningCount = @($results | Where-Object Status -eq "WARN").Count
        FailureCount = @($results | Where-Object Status -eq "FAIL").Count
    }
}

function Invoke-IsalaPermissionRepair {
    Write-Host "Repairing IsalaOCR writable directories..." -ForegroundColor Cyan
    foreach ($relative in @("output","models\training","training\workspace","training\registry")) {
        $path = Join-Path $ProjectRoot $relative
        New-Item -ItemType Directory -Path $path -Force | Out-Null
        try { attrib -R "$path\*" /S /D 2>$null | Out-Null } catch { }
    }
    foreach ($path in @((Get-IsalaHostProjectWorkspace), (Get-IsalaHostProjectRegistry), (Join-Path $ProjectRoot ("models\projects\{0}\active-recognition" -f (Get-IsalaActiveProjectId))))) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
        try { attrib -R "$path\*" /S /D 2>$null | Out-Null } catch { }
    }
    Assert-Docker
    if (-not (Test-TrainingImagePrepared -Device cpu)) {
        throw "The CPU training image is missing. Open Stap 1 · Voorbereiding and choose Alles voorbereiden before container-side permission repair."
    }
    & docker compose --profile doctor run --rm --pull never workspace-repair repair --json
    if ($LASTEXITCODE -ne 0) { throw "Container-side permission repair failed." }
    $verification = Invoke-IsalaPreflight -ActionId "1" -EnsureDocker -SaveReport
    if (-not $verification.Passed) { throw "Repair completed, but permission verification still contains failures." }
    Write-Host "Permissions repaired and verified." -ForegroundColor Green
}
