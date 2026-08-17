from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def test_gpu_preflight_is_deferred_to_training_runtime() -> None:
    preflight = read("automation/powershell/preflight.ps1")
    section = preflight.split("function Invoke-IsalaGpuRuntimeCheck", 1)[1].split(
        "function Add-IsalaCommonChecks", 1
    )[0]
    assert "Deferred to trainer-gpu runtime" in section
    assert "runtime-check" not in section

def test_gpu_runtime_verification_is_skipped_after_blocking_prerequisite() -> None:
    preflight = read("automation/powershell/preflight.ps1")
    section = preflight.split('"train-gpu" {', 1)[1].split('"train-cpu" {', 1)[0]
    assert "$datasetState.Ready -and $weightReady -and $gpu" in section
    assert "GPU runtime verification skipped" in section
    assert "deferred to the trainer-gpu runtime" in section
