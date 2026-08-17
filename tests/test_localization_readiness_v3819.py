from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_current_localization_dataset_uses_latest_pointer() -> None:
    webui = (ROOT / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    assert 'def current_localization_dataset(' in webui
    assert '"localization_datasets" / "latest.txt"' in webui
    assert 'loc_dataset = current_localization_dataset(datasets)' in webui
    assert 'localization_dataset_readiness_state(localization_datasets)' in webui
    assert 'validation.get("dataset_id")' in webui
    assert 'paddlex_dataset_id == dataset_id' in webui


def test_successful_validation_writes_dataset_bound_ready_marker() -> None:
    script = (ROOT / "automation/powershell/validate-localization-dataset.ps1").read_text(encoding="utf-8")
    assert '$ReadyMarker = Join-Path $DatasetRoot "training_ready.json"' in script
    assert 'Remove-Item -LiteralPath $ReadyMarker' in script
    assert 'dataset_id = $DatasetId' in script
    assert 'manifest_sha256 = $ManifestHash' in script
    assert '[System.IO.File]::WriteAllText($ReadyMarker' in script


def test_training_preflight_reports_exact_dataset_and_validates_marker_ids() -> None:
    preflight = (ROOT / "automation/powershell/preflight.ps1").read_text(encoding="utf-8")
    assert '([string]$validation.dataset_id -eq $datasetId)' in preflight
    assert '$paddlexDatasetLeaf -eq $datasetId' in preflight
    assert 'dataset={0}; pointer={1}; app={2}; PaddleX={3}; split_current={4}; ready_marker={5}' in preflight
    assert 'Do not rely on validation from an older loc-* dataset.' in preflight


def test_step_four_shows_current_dataset_and_ready_marker() -> None:
    template = (ROOT / "application/src/isala_ocr/training/templates/process_step.html").read_text(encoding="utf-8")
    assert 'Huidige dataset' in template
    assert 'localization_dataset.dataset_id' in template
    assert 'Trainingsstatus' in template
    assert 'localization_ready_marker_valid' in template
