from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "src"))

from isala_ocr.training.webui import create_web_app


def _app(tmp_path: Path):
    workspace = tmp_path / "training" / "workspace"
    models = tmp_path / "models"
    output = tmp_path / "output"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.8.5", encoding="utf-8")
    return create_web_app(workspace, models_root=models, output_root=output, project_root=project), models


def test_page_one_centralizes_all_preparation_actions(tmp_path: Path) -> None:
    app, _ = _app(tmp_path)
    html = app.test_client().get("/process/detection-models").get_data(as_text=True)
    assert "Alles voorbereiden" in html
    assert "Status controleren" in html
    for action_id in ("14", "15", "16", "17", "18"):
        assert f'value="{action_id}"' in html
    assert "Zijn alle verwachte modellen en training-images aanwezig?" in html
    assert "Inference OCR + tabelmodellen" in html
    assert "GPU PaddleDetection / PicoDet-S" in html
    assert "Download / build" in html  # file-backed missing components
    assert "Controleren" in html  # Docker-backed unknown components are checked before building


def test_page_one_shows_green_checks_when_expected_artifacts_exist(tmp_path: Path) -> None:
    app, models = _app(tmp_path)
    paddlex = models / "paddlex"
    baseline = paddlex / "official_models" / "PP-OCRv6_medium_rec"
    baseline.mkdir(parents=True)
    (baseline / "inference.json").write_text("{}", encoding="utf-8")
    (baseline / "model.safetensors").write_bytes(b"weights")
    (paddlex / "official_models" / "det").mkdir(parents=True)
    (paddlex / "isala_ocr_model_manifest.json").write_text(json.dumps({
        "required_models": [
            {"role": "text_detection", "model": "det", "prepared": True},
            {"role": "table_structure", "model": "PP-StructureV3 table pipeline", "prepared": True},
        ]
    }), encoding="utf-8")
    (paddlex / "isala_localization_model_manifest.json").write_text(json.dumps({
        "status": "prepared", "model_name": "PicoDet-S"
    }), encoding="utf-8")
    training = models / "training"
    training.mkdir(parents=True)
    (training / "PP-OCRv6_medium_rec_pretrained.pdparams").write_bytes(b"x" * (1024 * 1024 + 1))
    (models / "preparation_status.json").write_text(json.dumps({
        "checked_at": "2026-08-10T10:30:00+02:00",
        "training_image_version": "3.8.4",
        "components": {
            "cpu_detection": {"image": "isalaocr-training-cpu:3.8.4", "image_present": True},
            "gpu_recognition": {"image": "isalaocr-training-gpu:3.8.4", "image_present": True},
            "gpu_detection": {"image": "isalaocr-training-gpu-detection:3.8.4", "image_present": True},
        },
    }), encoding="utf-8")

    html = app.test_client().get("/process/detection-models").get_data(as_text=True)
    assert "✓ ALLES AANWEZIG" in html
    assert html.count("Gereed") >= 5
    assert "3.8.4" in html


def test_preparation_status_action_checks_exact_versioned_docker_tags() -> None:
    script = (ROOT / "automation" / "powershell" / "preparation-status.ps1").read_text(encoding="utf-8")
    assert 'Get-TrainingImageName -Device "cpu"' not in script  # helper is called via Get-ImageState
    assert 'Get-ImageState -Device "cpu"' in script
    assert 'Get-ImageState -Device "gpu"' in script
    assert 'Get-ImageState -Device "gpu-detection"' in script
    assert '@("image","inspect","--format","{{.Id}}",$image)' in script
    assert 'preparation_status.json' in script
