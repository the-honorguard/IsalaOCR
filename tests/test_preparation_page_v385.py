from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
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
    return create_web_app(
        workspace,
        models_root=models,
        output_root=output,
        project_root=project,
        config_path=ROOT / "application" / "config" / "app.yaml",
    ), models


def test_page_one_centralizes_all_preparation_actions(tmp_path: Path) -> None:
    app, _ = _app(tmp_path)
    html = app.test_client().get("/process/detection-models").get_data(as_text=True)
    client = (ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "preparation-page.js").read_text(encoding="utf-8")
    assert "Alles voorbereiden" in client
    assert "actionId: '1'" in client
    assert "Onderhoud / opnieuw installeren" in html
    assert 'value="14"' in html
    assert "Inference OCR + tabelmodellen" in html
    # "Input controleren" moved out of the preparation page into the separate
    # "Inputselectie" step; it is no longer part of this page's content.


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
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "training_image_version": "3.8.4",
        "components": {
            "inference": {
                "title": "Inference OCR + tabelmodellen",
                "download": {"ready": True, "state": "ready", "detail": "aanwezig"},
                "install": {"ready": True, "state": "ready", "detail": "gevalideerd"},
            },
        },
    }), encoding="utf-8")

    html = app.test_client().get("/process/detection-models").get_data(as_text=True)
    assert "GEREED" in html
    assert "Je hoeft hier niets meer te installeren" in html
    assert "Training-image versie" not in html


def test_preparation_status_action_checks_exact_versioned_docker_tags() -> None:
    script = (ROOT / "automation" / "powershell" / "preparation-status.ps1").read_text(encoding="utf-8")
    assert 'Get-PreparationImageState -Image (Get-TrainingImageName -Device cpu)' in script
    assert 'Get-PreparationImageState -Image (Get-TrainingImageName -Device gpu)' in script
    assert 'Get-PreparationImageState -Image (Get-TrainingImageName -Device gpu-detection)' in script
    assert 'Get-DockerImageState -Image $Image' in script
    assert 'preparation_status.json' in script
