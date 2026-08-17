from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_process_output_is_null_safe_for_windows_powershell() -> None:
    common = read("automation/powershell/training-common.ps1")
    assert "function Get-IsalaProcessOutputText" in common
    assert "if ($null -eq $Result) { return $Fallback }" in common
    assert "$stdout = [string]$Result.StdOut" in common
    assert "$stderr = [string]$Result.StdErr" in common


def test_gpu_preflight_does_not_launch_compose_process() -> None:
    preflight = read("automation/powershell/preflight.ps1")
    section = preflight.split("function Invoke-IsalaGpuRuntimeCheck", 1)[1].split(
        "function Add-IsalaCommonChecks", 1
    )[0]
    assert "Invoke-DockerWithTimeout" not in section
    assert "Start-Process" not in section
    assert "Deferred to trainer-gpu runtime" in section
def test_preflight_converts_internal_checker_exceptions_to_failed_results() -> None:
    preflight = read("automation/powershell/preflight.ps1")
    assert 'Name "Preflight implementation" -Status "FAIL"' in preflight
    assert "the checker itself failed before the task was executed" in preflight


def test_training_image_inspection_handles_missing_process_result() -> None:
    common = read("automation/powershell/training-common.ps1")
    section = common.split("function Get-DockerImageState", 1)[1].split("function Get-DockerImageId", 1)[0]
    assert "$null -ne $result" in section
    assert "-not $result.TimedOut" in section
    assert "if ($null -ne $result)" in section
    assert "Get-IsalaProcessOutputText -Result $lastResult" in section


def test_labeler_docker_error_output_uses_shared_null_safe_formatter() -> None:
    labeler = read("automation/powershell/labeler-common.ps1")
    assert "Get-IsalaProcessOutputText -Result $result" in labeler
    assert "$result.StdOut + [Environment]::NewLine" not in labeler
