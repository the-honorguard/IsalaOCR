from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_auto_device_probe_requires_real_cuda_paddle_runtime() -> None:
    script = _text("automation/powershell/table-execution-device.ps1")
    assert 'ValidateSet("auto", "cpu", "gpu")' in script
    assert "nvidia-smi" in script
    assert '"--gpus", "all"' in script
    assert "p.is_compiled_with_cuda()" in script
    assert "p.device.cuda.device_count()>0" in script
    assert 'Device = "cpu"' in script
    assert 'Device = "gpu"' in script


def test_full_round_uses_one_resolved_backend_for_train_and_inference() -> None:
    script = _text("automation/powershell/run-table-cell-pipeline.ps1")
    assert 'Resolve-IsalaTableExecutionDevice -Requested $ExecutionDevice -PrepareGpuRuntime' in script
    assert 'train-table-cell-model.ps1") -Device $resolvedDevice' in script
    assert 'collect-training-data.ps1") -TableModelId $activeModelId -Device $resolvedDevice' in script
    assert 'inference_backend = "cpu_fallback"' in script
    assert "table_execution_state.json" in script
    assert "execution_device" in script


def test_cpu_and_gpu_inference_paths_remain_available() -> None:
    script = _text("automation/powershell/collect-training-data.ps1")
    assert 'ValidateSet("auto", "cpu", "gpu")' in script
    assert '$ResolvedDevice -eq "gpu"' in script
    assert '"--gpus", "all"' in script
    assert '"training-collector"' in script
    assert '"--device", $ResolvedDevice' in script

    dockerfile = _text("infrastructure/docker/Dockerfile.table-inference")
    assert "ARG BASE_IMAGE=isalaocr-training-gpu-detection" in dockerfile
    assert "pydicom" in dockerfile
    assert "COPY application/src /app/src" in dockerfile
    # The base image already contains paddlepaddle-gpu. Never replace it with
    # the CPU wheel in the small inference layer.
    assert "paddlepaddle==" not in dockerfile
