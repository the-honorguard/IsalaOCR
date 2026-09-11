from pathlib import Path

import cv2
import numpy as np

from isala_ocr.training.db import TrainingDatabase

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html"
CSS = ROOT / "application/src/isala_ocr/training/static/app.css"
WEBUI = ROOT / "application/src/isala_ocr/training/webui.py"


def _source(workspace: Path, db: TrainingDatabase) -> None:
    render = workspace / "source_renders" / "source.png"
    render.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(render), np.zeros((120, 320, 3), dtype=np.uint8))
    db.replace_localization_detection(
        {
            "source_id": "source",
            "image_width": 320,
            "image_height": 120,
            "render_path": render.relative_to(workspace).as_posix(),
            "detector_version": "table-first-test",
            "token_count": 0,
        },
        [],
        [],
    )


def test_manual_detection_annotation_can_be_resized_persistently(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    _source(workspace, db)
    item = db.add_detection_annotation(source_id="source", box=(20, 20, 90, 45))

    updated = db.update_manual_detection_annotation(item["annotation_id"], box=(25, 18, 105, 48))

    assert [updated[k] for k in ("x1", "y1", "x2", "y2")] == [25, 18, 105, 48]
    annotations = db.list_detection_annotations("source")
    assert len(annotations) == 1
    assert [annotations[0][k] for k in ("x1", "y1", "x2", "y2")] == [25, 18, 105, 48]


def test_reviewer_exposes_manual_edit_delete_and_top_marker_layer() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    assert 'id="dock-delete-manual"' in source
    assert 'id="review-marker-layer"' in source
    assert "function selectManual(" in source
    assert "function saveManualGeometry()" in source
    assert "method:'PATCH'" in source
    assert "bindBoxGeometry(box,{manual:true})" in source
    assert "addSelectionMarker(box" in source
    assert "data-original=\"{{ item.x1 }},{{ item.y1 }},{{ item.x2 }},{{ item.y2 }}\"" in source


def test_selection_markers_are_above_overlapping_boxes() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert ".review-marker-layer" in css
    assert "z-index:90" in css
    assert ".review-selection-marker" in css
    assert "pointer-events:auto" in css
    assert ".review-box>.box-index{display:none}" in css


def test_table_first_structure_review_rule_is_explicit() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "rijen en kolommen" in source
    assert "losse celacties zijn alleen nodig bij een echte uitzondering" in source
    assert "+ Ontbrekende cel" in source


def test_manual_update_api_exists() -> None:
    # This route now lives in routes_detection_review.py (split out of webui.py).
    source = WEBUI.parent.joinpath("routes_detection_review.py").read_text(encoding="utf-8")
    assert '@app.patch("/api/detection-review/<source_id>/manual/<annotation_id>")' in source
    assert "database.update_manual_detection_annotation" in source
