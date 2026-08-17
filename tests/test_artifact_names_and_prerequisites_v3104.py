from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "application/src/isala_ocr/training/webui.py"
WORKBENCH = ROOT / "frontend/src/localization-workbench.ts"
QUALITY = ROOT / "frontend/src/localization-quality.ts"
ARTIFACTS = ROOT / "frontend/src/localization-artifacts.ts"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_dataset_and_model_labels_include_project_date_and_time() -> None:
    workbench = _text(WORKBENCH)
    quality = _text(QUALITY)
    artifacts = _text(ARTIFACTS)
    for source in (workbench, quality, artifacts):
        assert 'month: "short"' in source
        assert 'hour: "2-digit"' in source
        assert 'minute: "2-digit"' in source
    assert "veld-dataset" in workbench
    assert "qdatasetName" in quality
    assert "qmodelName" in quality
    assert "datasetName" in artifacts
    assert "modelName" in artifacts
    assert "artifact-technical-id" in artifacts


def test_workbench_exposes_actionable_training_blockers() -> None:
    backend = _text(WEBUI)
    client = _text(WORKBENCH)
    for code in ("dataset_missing", "dataset_stale", "app_validation_missing", "paddlex_validation_missing"):
        assert code in backend
    assert '"blockers": blockers' in backend
    assert '"next_step": blockers[0]["next_step"]' in backend
    assert "Niet beschikbaar:" in client
    assert "Volgende stap:" in client
    assert "Detection Review" in client
    assert "Dataset valideren" in client


def test_quality_and_artifact_buttons_explain_why_they_are_disabled() -> None:
    quality = _text(QUALITY)
    artifacts = _text(ARTIFACTS)
    for source in (quality, artifacts):
        assert "Niet beschikbaar:" in source
        assert "achtergrondworker is offline" in source
    assert "Voer eerst een baseline- én een getrainde evaluatie uit" in quality
    assert "detection gate" in quality.lower()
    assert "Maak eerst de bijbehorende dataset de werkdataset" in artifacts


def test_quality_and_artifact_payloads_include_project_context() -> None:
    backend = _text(WEBUI)
    assert backend.count('"project_id": project_state.project_id') >= 3
    assert '"worker": worker_state()' in backend
