from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("flask")
cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from isala_ocr.config import load_config
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.mapping import ensure_default_field_definitions
from isala_ocr.training.projects import resolve_project_workspace
from isala_ocr.training.table_panels import save_panel_profile
from isala_ocr.training.webui import create_web_app

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "shared-table-id-source"
# Both physical tables share this SAME table_id, reproducing a real report:
# a left-ventricle block and a right-ventricle block can be assigned the
# identical canonical table_id, even though they sit nowhere near each other
# on the image.
SHARED_TABLE_ID = "canonical-shared-id"
IMAGE_WIDTH, IMAGE_HEIGHT = 600, 900


def _block(block_id: str, *, role: str, text: str, x1: int, y1: int, column_index: int, row_index: int) -> dict:
    return {
        "block_id": block_id, "block_type": "table_cell", "role": role, "text": text,
        "normalized_text": text.lower(), "confidence": 0.95,
        "x1": x1, "y1": y1, "x2": x1 + 60, "y2": y1 + 20,
        "line_index": row_index, "sequence_index": row_index,
        "table_id": SHARED_TABLE_ID, "row_index": row_index, "column_index": column_index,
    }


def _relation(relation_id: str, *, label_block_id: str, value_block_id: str, context_text: str, row_index: int) -> dict:
    return {
        "relation_id": relation_id, "label_block_id": label_block_id, "value_block_id": value_block_id,
        "unit_block_id": "", "relation_type": "table_cell", "confidence": 0.95, "rank": 1,
        "context_text": context_text, "table_id": SHARED_TABLE_ID, "row_index": row_index, "value_column_index": 1,
    }


def _make_app(tmp_path: Path):
    workspace = tmp_path / "training" / "workspace"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.16.0")
    resolved_workspace = resolve_project_workspace(workspace)
    database = TrainingDatabase(resolved_workspace / "samples.sqlite3")
    config = load_config(ROOT / "application" / "config" / "app.yaml")
    ensure_default_field_definitions(database, config.profile)

    render_dir = resolved_workspace / "source_renders"
    render_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(render_dir / f"{SOURCE_ID}.png"), np.full((IMAGE_HEIGHT, IMAGE_WIDTH, 3), 255, dtype="uint8"))

    # Left-ventricle block near the top (y ~ 50-150), right-ventricle block
    # far below (y ~ 700-800) - same table_id, geometrically unrelated.
    blocks = [
        _block("label-lv", role="label", text="Ejection Fraction", x1=10, y1=50, column_index=0, row_index=0),
        _block("value-lv", role="value", text="63 %", x1=100, y1=50, column_index=1, row_index=0),
        _block("label-rv", role="label", text="Ejection Fraction", x1=10, y1=700, column_index=0, row_index=13),
        _block("value-rv", role="value", text="53 %", x1=100, y1=700, column_index=1, row_index=13),
    ]
    relations = [
        _relation("relation-lv", label_block_id="label-lv", value_block_id="value-lv", context_text="Left ventricle Volume Result", row_index=0),
        _relation("relation-rv", label_block_id="label-rv", value_block_id="value-rv", context_text="Right ventricle Volume Result", row_index=13),
    ]
    database.replace_generic_detection(
        {
            "source_id": SOURCE_ID, "image_width": IMAGE_WIDTH, "image_height": IMAGE_HEIGHT,
            "render_path": f"source_renders/{SOURCE_ID}.png", "detector_version": "test", "token_count": len(blocks),
        },
        blocks, relations,
    )
    save_panel_profile(
        resolved_workspace,
        panels=[
            {"panel_id": "left", "name": "Links", "x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 0.5},
            {"panel_id": "right", "name": "Rechts", "x1": 0.0, "y1": 0.5, "x2": 1.0, "y2": 1.0},
        ],
        reference_source_id=SOURCE_ID, reference_width=IMAGE_WIDTH, reference_height=IMAGE_HEIGHT,
    )

    app = create_web_app(
        workspace, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project,
    )
    return app


def test_crop_and_overlays_are_scoped_to_this_panel_not_the_shared_table_id(tmp_path: Path) -> None:
    """Regression: two geometrically unrelated tables sharing one table_id
    must never be combined into a single stretched crop with misplaced
    overlay boxes - only the current relation's own panel counts."""
    app = _make_app(tmp_path)
    with app.test_request_context(f"/mapping-labels/{SOURCE_ID}/queue/relation-lv"):
        body = app.view_functions["label_mapping_queue_item"](SOURCE_ID, "relation-lv")

    # Exactly one row's worth of overlays (this panel only): 2 boxes (label+value).
    assert body.count('class="mapping-overlay-box') == 2
    # The crop's image URL must be keyed by the resolved panel, not the raw
    # (shared, unreliable) table_id.
    assert f"/mapping-labels/{SOURCE_ID}/table-image/left" in body
    assert f"/mapping-labels/{SOURCE_ID}/table-image/{SHARED_TABLE_ID}" not in body


def test_table_image_route_crops_only_this_panels_region(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    with app.test_request_context(f"/mapping-labels/{SOURCE_ID}/table-image/left"):
        response = app.view_functions["label_mapping_table_image"](SOURCE_ID, "left")
    assert response.status_code == 200
    decoded = cv2.imdecode(np.frombuffer(response.get_data(), dtype="uint8"), cv2.IMREAD_COLOR)
    # A crop scoped correctly to just the LV row is small; the old,
    # table_id-based bug would stretch this to cover y=50..800 (~750px tall).
    assert decoded.shape[0] < 200
