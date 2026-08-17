from pathlib import Path


def test_gpu_preflight_is_deferred_to_training_runtime() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "automation" / "powershell" / "preflight.ps1").read_text(encoding="utf-8")
    train_block = script.split('"train-gpu" {', 1)[1].split('"train-cpu" {', 1)[0]
    assert "Invoke-IsalaGpuRuntimeCheck" not in train_block
    assert "deferred to the trainer-gpu runtime" in train_block
    assert "runtime-check" not in train_block
