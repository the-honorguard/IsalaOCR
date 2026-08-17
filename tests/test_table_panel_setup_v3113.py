from __future__ import annotations

from pathlib import Path

import numpy as np

from isala_ocr.models import Box
from isala_ocr.training.table_panels import load_panel_profile, panel_boxes_for_image, save_panel_profile

ROOT = Path(__file__).resolve().parents[1]


def test_panel_profile_is_project_relative_and_resolution_independent(tmp_path: Path):
    profile = save_panel_profile(
        tmp_path,
        reference_source_id="source-a",
        reference_width=1000,
        reference_height=500,
        panels=[
            {"name": "LV results", "x1": 0.02, "y1": 0.05, "x2": 0.31, "y2": 0.46},
            {"name": "RV results", "x1": 0.02, "y1": 0.52, "x2": 0.31, "y2": 0.94},
        ],
    )
    assert len(profile["panels"]) == 2
    loaded = load_panel_profile(tmp_path)
    boxes = panel_boxes_for_image(loaded, 2000, 1000)
    assert boxes[0]["name"] == "LV results"
    assert boxes[0]["box"] == Box(40, 50, 620, 460)
    assert boxes[1]["box"] == Box(40, 520, 620, 940)


def test_manual_panel_pipeline_is_authoritative_in_config_and_ui():
    config = (ROOT / "application/config/app.yaml").read_text(encoding="utf-8")
    webui = (ROOT / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    template = (ROOT / "application/src/isala_ocr/training/templates/table_panel_setup.html").read_text(encoding="utf-8")
    collector = (ROOT / "application/src/isala_ocr/training/collector.py").read_text(encoding="utf-8")
    assert "panel_mode: manual" in config
    assert '"key": "panel-setup","index":2' in webui
    assert 'id="panel-draw"' in template
    assert 'id="panel-fit"' in template
    assert "if(inter<=0)return null" in template
    assert "never jump to another non-overlapping table" in template
    assert "Nog geen Paddle-suggestie overlapt dit zoekgebied" in template
    assert "panel_suggestions" in (ROOT / "application/src/isala_ocr/ocr/table_structure.py").read_text(encoding="utf-8")
    assert 'id="panel-save"' in template
    assert "detect_panels_with_benchmark" in collector
    assert "bootstrap_suggestion" in collector
    dockerfile = (ROOT / "infrastructure/docker/Dockerfile.labeler").read_text(encoding="utf-8")
    assert "training/table_panels.py" in dockerfile


def test_table_engine_benchmarks_each_manual_panel_independently(monkeypatch):
    from isala_ocr.ocr.table_structure import PPStructureTableEngine, TableCell, TableRegion

    engine = PPStructureTableEngine({}, {"preprocessing_variants": ["original", "invert_clahe"]})
    calls = []

    def fake_detect(image, *, source_id, fallback_tokens=()):
        calls.append((image.shape[:2], source_id))
        h, w = image.shape[:2]
        cells = tuple(
            TableCell("t", f"c{i}", i // 2, i % 2, Box(2 + (i % 2) * 20, 2 + (i // 2) * 12, 20 + (i % 2) * 20, 12 + (i // 2) * 12), "", 0.9)
            for i in range(6)
        )
        return [TableRegion("t", Box(1, 1, min(w, 45), min(h, 40)), 0.9, cells)]

    monkeypatch.setattr(engine, "_detect_once", fake_detect)
    image = np.zeros((200, 300, 3), dtype=np.uint8)
    panels = [
        {"panel_id": "lv", "name": "LV", "box": Box(0, 0, 120, 80)},
        {"panel_id": "rv", "name": "RV", "box": Box(0, 100, 120, 190)},
    ]
    regions, meta = engine.detect_panels_with_benchmark(image, source_id="src", panels=panels)
    assert len(meta["panels"]) == 2
    assert meta["panel_count"] == 2
    assert {item["panel_name"] for item in meta["panels"]} == {"LV", "RV"}
    assert len(calls) == 4  # 2 panels x 2 preprocessing variants
    assert any("src:lv" in source for _, source in calls)
    assert any("src:rv" in source for _, source in calls)
    assert len(regions) == 2


def test_panel_setup_api_persists_profile_and_marks_workflow_configured(tmp_path: Path):
    import pytest
    pytest.importorskip("flask")
    from isala_ocr.training.webui import create_web_app

    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.11.7", encoding="utf-8")
    app = create_web_app(
        tmp_path / "workspace",
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project,
        config_path=ROOT / "application/config/app.yaml",
    )
    client = app.test_client()
    response = client.post(
        "/api/table-panels",
        json={
            "reference_source_id": "example",
            "reference_width": 1000,
            "reference_height": 600,
            "panels": [
                {"name": "LV results", "x1": 0.02, "y1": 0.05, "x2": 0.32, "y2": 0.46},
                {"name": "RV results", "x1": 0.02, "y1": 0.52, "x2": 0.32, "y2": 0.94},
            ],
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert len(payload["profile"]["panels"]) == 2
    page = client.get("/process/panel-setup")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "2 panel(en) ingesteld" in html
    assert "Ga naar Stap 3" in html


def test_bootstrap_panel_suggestions_keep_second_table_from_nonwinning_variant():
    from isala_ocr.ocr.table_structure import (
        TableCell, TableRegion, _panel_suggestions_from_variant_results,
    )

    def region(table_id: str, box: Box, rows: int = 4) -> TableRegion:
        cells = []
        row_h = max(8, box.height // rows)
        col_w = max(12, box.width // 2)
        for r in range(rows):
            for c in range(2):
                x1 = box.x1 + c * col_w
                y1 = box.y1 + r * row_h
                cells.append(TableCell(table_id, f"{table_id}-{r}-{c}", r, c, Box(x1, y1, min(box.x2, x1+col_w), min(box.y2, y1+row_h)), "", 0.9))
        return TableRegion(table_id, box, 0.9, tuple(cells))

    upper = region("upper", Box(20, 20, 250, 190))
    lower = region("lower", Box(20, 260, 250, 450))
    # Imagine invert_clahe wins globally because its lower table is stronger, while
    # original is the only pass that found the upper table. Panel Setup must keep both.
    suggestions = _panel_suggestions_from_variant_results(
        {"original": [upper, lower], "invert_clahe": [lower]}, 600, 500
    )
    assert len(suggestions) == 2
    ys = sorted((item["y1"], item["y2"]) for item in suggestions)
    assert ys[0][0] <= 20 and ys[0][1] >= 190
    assert ys[1][0] <= 260 and ys[1][1] >= 450
    assert any("original" in item["variants"] for item in suggestions)
