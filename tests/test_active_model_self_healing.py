from pathlib import Path

from isala_ocr.ocr.recognition import PaddleRecognitionEngine


def test_infers_medium_model_name_from_active_inference_yaml(tmp_path: Path):
    model = tmp_path / "active-recognition"
    model.mkdir()
    (model / "inference.yml").write_text(
        "Global:\n  model_name: PP-OCRv6_medium_rec\n", encoding="utf-8"
    )
    assert PaddleRecognitionEngine._model_name_from_dir(model) == "PP-OCRv6_medium_rec"


def test_collect_script_uses_auto_model_and_safe_housekeeping():
    root = Path(__file__).resolve().parents[1]
    script = (root / "automation" / "powershell" / "collect-training-data.ps1").read_text(encoding="utf-8")
    assert '[string]$Model = "auto"' in script
    assert 'safe-housekeeping.ps1' in script
    assert '$Model -ne "auto"' in script


def test_safe_housekeeping_never_targets_datasets_runs_or_active_model():
    root = Path(__file__).resolve().parents[1]
    script = (root / "automation" / "powershell" / "safe-housekeeping.ps1").read_text(encoding="utf-8")
    assert "active-recognition.new" in script
    assert "active-recognition\")" not in script
    assert "Join-Path $ProjectRoot \"training\\workspace\\datasets\"" not in script
    assert "Join-Path $ProjectRoot \"training\\workspace\\runs\"" not in script
