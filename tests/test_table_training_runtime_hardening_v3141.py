from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_gpu_probe_survives_windows_powershell_argument_flattening() -> None:
    script = _text("automation/powershell/table-execution-device.ps1")
    probe_line = next(line for line in script.splitlines() if line.strip().startswith('$code = '))
    # Start-Process/ArgumentList on Windows PowerShell 5.1 can split an unquoted
    # Python -c program at spaces. The probe is intentionally whitespace-free.
    python_code = probe_line.split('"', 1)[1].rsplit('"', 1)[0]
    assert " " not in python_code
    assert "p.is_compiled_with_cuda()" in python_code
    assert "p.device.cuda.device_count()>0" in python_code
    assert "ISALA_GPU_OK:" in python_code


def test_table_checkpoint_resolution_is_windows_powershell_51_compatible() -> None:
    script = _text("automation/powershell/train-table-cell-model.ps1")
    assert "[System.IO.Path]::GetRelativePath(" not in script
    assert "GetFullPath" in script
    assert "Substring($workspacePrefix.Length)" in script
    assert "OrdinalIgnoreCase" in script


def test_strict_numeric_dataset_sanity_runs_during_validation_and_training() -> None:
    validator = _text("automation/training_runtime/table_cell_dataset_sanity.py")
    validation_ps = _text("automation/powershell/validate-table-cell-dataset.ps1")
    training_ps = _text("automation/powershell/train-table-cell-model.ps1")

    assert "math.isfinite" in validator
    assert "parse_constant=_reject_constant" in validator
    assert "allow_nan=False" in validator
    assert "bbox buiten image" in validator
    assert "image metadata mismatch" in validator
    assert "table_cell_dataset_sanity.py" in validation_ps
    assert "table_cell_dataset_sanity.py" in training_ps


def test_cpu_fallback_uses_conservative_rtdetr_settings() -> None:
    script = _text("automation/powershell/train-table-cell-model.ps1")
    assert '[Math]::Min([double]$LearningRate, 0.00003)' in script
    assert '$TrainArgs += @("--batch-size", "1")' in script
    assert "matrix contains invalid numeric entries" in script
