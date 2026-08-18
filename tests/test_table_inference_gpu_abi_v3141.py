from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_runtime_pins_numpy_and_pandas_for_paddleocr_abi() -> None:
    requirements = _text("application/requirements/runtime.txt")
    pyproject = _text("application/pyproject.toml")

    assert "numpy==1.26.4" in requirements
    assert "pandas>=2.2,<2.3" in requirements
    assert '"numpy==1.26.4"' in pyproject
    assert '"pandas>=2.2,<2.3"' in pyproject


def test_table_inference_image_has_build_time_numpy_pandas_abi_check() -> None:
    dockerfile = _text("infrastructure/docker/Dockerfile.table-inference")

    assert '"numpy==1.26.4"' in dockerfile
    assert '"pandas>=2.2,<2.3"' in dockerfile
    assert "import numpy" in dockerfile
    assert "import pandas" in dockerfile
    assert 'numpy.__version__ == "1.26.4"' in dockerfile
    assert "Docker build does not have access to libcuda.so.1" in dockerfile
    # The CUDA build boundary remains intact: the small image must inherit the
    # GPU Paddle wheel instead of replacing it with paddlepaddle CPU.
    assert "paddlepaddle==" not in dockerfile


def test_gpu_table_runtime_probe_checks_full_stack_before_inference() -> None:
    collector = _text("automation/powershell/collect-training-data.ps1")

    assert "ISALA_TABLE_GPU_OK:" in collector
    assert "__import__('numpy')" in collector
    assert "__import__('pandas')" in collector
    assert "__import__('paddle')" in collector
    assert "__import__('paddlex')" in collector
    assert "__import__('paddleocr')" in collector
    assert "p.is_compiled_with_cuda()" in collector
    assert "p.device.cuda.device_count()>0" in collector
    assert '"--gpus", "all"' in collector
    assert "[ISALA_TABLE_RUNTIME_BROKEN]" in collector


def test_broken_gpu_dependency_stack_is_not_masked_by_cpu_fallback() -> None:
    pipeline = _text("automation/powershell/run-table-cell-pipeline.ps1")

    assert '.Contains("[ISALA_TABLE_RUNTIME_BROKEN]")' in pipeline
    assert "CPU-fallback bewust overgeslagen" in pipeline
    # Ordinary GPU inference failures still retain the explicit Auto fallback.
    assert 'inference_backend = "cpu_fallback"' in pipeline
    assert "Auto probeert dezelfde actieve modelrun opnieuw op CPU" in pipeline
