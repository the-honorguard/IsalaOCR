# Device selection for the iterative table-cell training/inference loop.
#
# Auto is deliberately conservative: a host NVIDIA adapter is not enough.  The
# CUDA Paddle runtime must also start successfully through Docker before GPU is
# selected.  CPU remains a fully supported fallback for CPU-only servers.

. (Join-Path $PSScriptRoot "runtime-preparation.ps1")
Assert-IsalaRuntimePrepared | Out-Null

function Get-IsalaHostNvidiaState {
    $command = Get-Command "nvidia-smi" -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        return [pscustomobject]@{ Available = $false; Name = ""; Reason = "nvidia-smi niet gevonden" }
    }
    $filePath = if ($command.Source) { [string]$command.Source } else { "nvidia-smi" }
    $probe = Invoke-NativeProcessWithTimeout -FilePath $filePath `
        -Arguments @("--query-gpu=name", "--format=csv,noheader") -TimeoutSeconds 10
    if ($probe.TimedOut -or $probe.ExitCode -ne 0) {
        $detail = Get-IsalaProcessOutputText -Result $probe -Fallback "nvidia-smi gaf geen bruikbaar antwoord"
        return [pscustomobject]@{ Available = $false; Name = ""; Reason = $detail }
    }
    $name = ([string]$probe.StdOut).Trim().Split([Environment]::NewLine)[0].Trim()
    if ([string]::IsNullOrWhiteSpace($name)) { $name = "NVIDIA GPU" }
    return [pscustomobject]@{ Available = $true; Name = $name; Reason = "NVIDIA GPU gevonden" }
}

function Test-IsalaDockerPaddleGpu {
    $image = Get-TrainingImageName -Device "gpu-detection"
    if (-not (Test-TrainingImagePrepared -Device "gpu-detection")) {
        return [pscustomobject]@{ Available = $false; Name = ""; Reason = "GPU detection runtime is nog niet voorbereid" }
    }

    # Start-Process on Windows PowerShell 5.1 flattens ArgumentList into one
    # command line. A Python -c program containing spaces was therefore split
    # into multiple argv items and Auto falsely interpreted the resulting
    # SyntaxError as an unavailable GPU. Keep the probe deliberately whitespace
    # free so it remains one argument all the way through docker.exe.
    $code = "p=__import__('paddle');assert(p.is_compiled_with_cuda());assert(p.device.cuda.device_count()>0);print('ISALA_GPU_OK:'+p.device.cuda.get_device_name(0))"
    $probe = Invoke-DockerWithTimeout -Arguments @(
        "run", "--rm", "--gpus", "all", "--network", "none",
        "--entrypoint", "python3", $image, "-c", $code
    ) -TimeoutSeconds 45
    $output = Get-IsalaProcessOutputText -Result $probe -Fallback ""
    if (-not $probe.TimedOut -and $probe.ExitCode -eq 0 -and $output -match 'ISALA_GPU_OK:(?<name>[^\r\n]+)') {
        return [pscustomobject]@{ Available = $true; Name = ([string]$Matches.name).Trim(); Reason = "Docker/CUDA/Paddle GPU-probe geslaagd" }
    }
    $reason = if ($probe.TimedOut) { "Docker GPU-probe liep in een timeout" } elseif ($output) { $output } else { "Docker/CUDA/Paddle GPU-probe faalde" }
    return [pscustomobject]@{ Available = $false; Name = ""; Reason = $reason }
}

function Resolve-IsalaTableExecutionDevice {
    param(
        [ValidateSet("auto", "cpu", "gpu")]
        [string]$Requested = "auto",
        [switch]$PrepareGpuRuntime
    )

    $requestedNormalized = ([string]$Requested).Trim().ToLowerInvariant()
    if ($requestedNormalized -eq "cpu") {
        return [pscustomobject]@{
            Requested = "cpu"; Device = "cpu"; GpuName = "";
            Reason = "CPU handmatig gekozen"; AutoFallback = $false
        }
    }

    $hostGpu = Get-IsalaHostNvidiaState
    if (-not $hostGpu.Available) {
        if ($requestedNormalized -eq "gpu") {
            throw "GPU is geforceerd, maar er is geen bruikbare NVIDIA GPU gevonden: $($hostGpu.Reason)"
        }
        return [pscustomobject]@{
            Requested = "auto"; Device = "cpu"; GpuName = "";
            Reason = "Auto -> CPU: $($hostGpu.Reason)"; AutoFallback = $true
        }
    }

    if ($PrepareGpuRuntime -and -not (Test-TrainingImagePrepared -Device "gpu-detection")) {
        Write-Host "Auto/GPU: NVIDIA GPU gevonden; GPU detection runtime voorbereiden..." -ForegroundColor Cyan
        $oldNested = $env:ISALA_NESTED_PREFLIGHT_APPROVED
        try {
            $env:ISALA_NESTED_PREFLIGHT_APPROVED = "1"
            & (Join-Path $PSScriptRoot "prepare-training.ps1") `
                -Component "gpu-detection" -Phase full -PreflightActionId "50"
        }
        catch {
            if ($requestedNormalized -eq "gpu") { throw }
            return [pscustomobject]@{
                Requested = "auto"; Device = "cpu"; GpuName = [string]$hostGpu.Name;
                Reason = "Auto -> CPU: GPU runtime voorbereiden mislukte: $($_.Exception.Message)"; AutoFallback = $true
            }
        }
        finally {
            $env:ISALA_NESTED_PREFLIGHT_APPROVED = $oldNested
        }
    }

    $dockerGpu = Test-IsalaDockerPaddleGpu
    if ($dockerGpu.Available) {
        $name = if ([string]::IsNullOrWhiteSpace([string]$dockerGpu.Name)) { [string]$hostGpu.Name } else { [string]$dockerGpu.Name }
        return [pscustomobject]@{
            Requested = $requestedNormalized; Device = "gpu"; GpuName = $name;
            Reason = "GPU gekozen: Docker/CUDA/Paddle is bruikbaar"; AutoFallback = $false
        }
    }

    if ($requestedNormalized -eq "gpu") {
        throw "GPU is geforceerd, maar Docker/CUDA/Paddle is niet bruikbaar: $($dockerGpu.Reason)"
    }
    return [pscustomobject]@{
        Requested = "auto"; Device = "cpu"; GpuName = [string]$hostGpu.Name;
        Reason = "Auto -> CPU: $($dockerGpu.Reason)"; AutoFallback = $true
    }
}