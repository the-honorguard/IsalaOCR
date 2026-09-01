from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "src"))

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.webui import create_web_app


def fallback_sample() -> dict:
    return {
        "sample_id": "source_rv_stroke_volume",
        "source_id": "source",
        "profile": "philips_cmr_volume_result_v1",
        "field_key": "rv_stroke_volume",
        "field_label": "Right ventricle Stroke Volume",
        "crop_path": "crops/original/source/rv_stroke_volume.png",
        "raw_ocr": "70,0 ml",
        "raw_confidence": 0.89,
        "raw_variant": "test",
        "image_width": 1636,
        "image_height": 836,
        "roi_x1": 188,
        "roi_y1": 611,
        "roi_x2": 327,
        "roi_y2": 640,
        "extraction_method": "fixed_fallback",
        "locator_confidence": 0.62,
        "locator_label_text": "Slagvolume",
        "locator_version": "test",
        "locator_label_x1": 10,
        "locator_label_y1": 610,
        "locator_label_x2": 120,
        "locator_label_y2": 635,
        "header_crop_path": "header_crops/source/rv_stroke_volume.png",
        "header_crop_sha256": "headerhash",
        "crop_sha256": "valuehash",
    }


def make_app(tmp_path: Path):
    workspace = tmp_path / "training" / "workspace"
    database = TrainingDatabase(workspace / "samples.sqlite3")
    database.upsert_sample(fallback_sample())
    crop = workspace / "crops" / "original" / "source" / "rv_stroke_volume.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(b"not-a-real-png-but-present")
    header = workspace / "header_crops" / "source" / "rv_stroke_volume.png"
    header.parent.mkdir(parents=True, exist_ok=True)
    header.write_bytes(b"not-a-real-png-but-present")
    render = workspace / "source_renders" / "source.png"
    render.parent.mkdir(parents=True, exist_ok=True)
    render.write_bytes(b"not-a-real-png-but-present")
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.6.4", encoding="utf-8")
    app = create_web_app(
        workspace,
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project,
        config_path=ROOT / "application" / "config" / "app.yaml",
    )
    return app


def test_detection_list_shows_crop_and_actionable_fallback(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    response = app.test_client().get("/documents/source")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'src="/crop/source_rv_stroke_volume"' in text
    assert "Fallback" in text
    assert "Waarom fallback?" in text
    assert "Slagvolume" in text
    assert "Verwachte header" in text
    assert "Generiek opnieuw detecteren" in text
    assert "ROI beoordelen" in text
    assert "overlay-fallback" in text


def test_legacy_fallback_points_to_generic_redetection(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    response = app.test_client().get("/documents/source")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Generiek opnieuw detecteren" in text
    assert 'href="/process/detect"' in text
    assert "/process/header-normalization" not in text
