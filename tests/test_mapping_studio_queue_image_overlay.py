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
from isala_ocr.training.routes_mapping_studio import _overlay_box_style, _table_crop_box
from isala_ocr.training.webui import create_web_app

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "queue-image-source"
TABLE_ID = "queue-image-table"
IMAGE_WIDTH, IMAGE_HEIGHT = 400, 300


def _relation(relation_id: str, *, label_box, value_box, row_index: int) -> dict:
    lx1, ly1, lx2, ly2 = label_box
    vx1, vy1, vx2, vy2 = value_box
    return {
        "relation_id": relation_id, "table_id": TABLE_ID, "row_index": row_index, "value_column_index": 1,
        "label_x1": lx1, "label_y1": ly1, "label_x2": lx2, "label_y2": ly2,
        "value_x1": vx1, "value_y1": vy1, "value_x2": vx2, "value_y2": vy2,
    }


def test_table_crop_box_covers_every_relation_with_padding():
    relations = [
        _relation("a", label_box=(10, 10, 60, 30), value_box=(70, 10, 120, 30), row_index=0),
        _relation("b", label_box=(10, 40, 60, 60), value_box=(70, 40, 120, 60), row_index=1),
    ]
    box = _table_crop_box(relations, IMAGE_WIDTH, IMAGE_HEIGHT, padding=5)
    assert box == (5, 5, 125, 65)


def test_table_crop_box_clamps_to_image_bounds():
    relations = [_relation("a", label_box=(0, 0, 20, 20), value_box=(IMAGE_WIDTH - 5, IMAGE_HEIGHT - 5, IMAGE_WIDTH, IMAGE_HEIGHT), row_index=0)]
    box = _table_crop_box(relations, IMAGE_WIDTH, IMAGE_HEIGHT, padding=50)
    assert box == (0, 0, IMAGE_WIDTH, IMAGE_HEIGHT)


def test_table_crop_box_none_without_geometry():
    assert _table_crop_box([{"relation_id": "a"}], IMAGE_WIDTH, IMAGE_HEIGHT) is None


def test_overlay_box_style_is_percentage_of_crop():
    crop = (0, 0, 200, 100)
    style = _overlay_box_style((20, 10, 60, 30), crop)
    assert style == {"left": 10.0, "top": 10.0, "width": 20.0, "height": 20.0}


def _seed_source_with_render(database: TrainingDatabase, workspace: Path, source_id: str) -> None:
    render_dir = workspace / "source_renders"
    render_dir.mkdir(parents=True, exist_ok=True)
    image = np.full((IMAGE_HEIGHT, IMAGE_WIDTH, 3), 255, dtype="uint8")
    cv2.imwrite(str(render_dir / f"{source_id}.png"), image)

    def block(block_id: str, *, role: str, text: str, column_index: int, row_index: int) -> dict:
        x1 = 20 if column_index == 0 else 120
        y1 = row_index * 30
        return {
            "block_id": block_id, "block_type": "table_cell", "role": role, "text": text,
            "normalized_text": text.lower(), "confidence": 0.95,
            "x1": x1, "y1": y1, "x2": x1 + 60, "y2": y1 + 20,
            "line_index": row_index, "sequence_index": row_index,
            "table_id": TABLE_ID, "row_index": row_index, "column_index": column_index,
        }

    blocks, relations = [], []
    for row_index, (tag, label_text) in enumerate([("ef", "Ejectiefractie"), ("co", "Cardiac Output")]):
        label_id, value_id, relation_id = f"label-{tag}", f"value-{tag}", f"relation-{tag}"
        blocks.append(block(label_id, role="label", text=label_text, column_index=0, row_index=row_index))
        blocks.append(block(value_id, role="value", text="40 %", column_index=1, row_index=row_index))
        relations.append({
            "relation_id": relation_id, "label_block_id": label_id, "value_block_id": value_id,
            "unit_block_id": "", "relation_type": "table_cell", "confidence": 0.95, "rank": 1,
            "context_text": "", "table_id": TABLE_ID, "row_index": row_index, "value_column_index": 1,
        })
    database.replace_generic_detection(
        {
            "source_id": source_id, "image_width": IMAGE_WIDTH, "image_height": IMAGE_HEIGHT,
            "render_path": f"source_renders/{source_id}.png", "detector_version": "test", "token_count": len(blocks),
        },
        blocks, relations,
    )


def _make_app(tmp_path: Path):
    workspace = tmp_path / "training" / "workspace"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.16.0")
    resolved_workspace = resolve_project_workspace(workspace)
    database = TrainingDatabase(resolved_workspace / "samples.sqlite3")
    config = load_config(ROOT / "application" / "config" / "app.yaml")
    ensure_default_field_definitions(database, config.profile)
    _seed_source_with_render(database, resolved_workspace, SOURCE_ID)
    app = create_web_app(
        workspace, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project,
    )
    return app


def test_queue_page_renders_image_and_overlay_for_every_row_in_the_table(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    with app.test_request_context(f"/mapping-labels/{SOURCE_ID}/queue/relation-ef"):
        body = app.view_functions["label_mapping_queue_item"](SOURCE_ID, "relation-ef")
    assert f"/mapping-labels/{SOURCE_ID}/table-image/{TABLE_ID}" in body
    assert body.count("mapping-overlay-box") >= 4  # label+value box per each of the 2 rows
    assert "is-current" in body


def test_table_image_route_returns_a_cropped_png(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    with app.test_request_context(f"/mapping-labels/{SOURCE_ID}/table-image/{TABLE_ID}"):
        response = app.view_functions["label_mapping_table_image"](SOURCE_ID, TABLE_ID)
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    decoded = cv2.imdecode(np.frombuffer(response.get_data(), dtype="uint8"), cv2.IMREAD_COLOR)
    assert decoded is not None
    # Smaller than the full 400x300 source (cropped to the table + padding).
    assert decoded.shape[1] < IMAGE_WIDTH
    assert decoded.shape[0] < IMAGE_HEIGHT


def test_table_image_route_404s_for_unknown_table(tmp_path: Path) -> None:
    from werkzeug.exceptions import NotFound

    app = _make_app(tmp_path)
    with app.test_request_context(f"/mapping-labels/{SOURCE_ID}/table-image/does-not-exist"):
        with pytest.raises(NotFound):
            app.view_functions["label_mapping_table_image"](SOURCE_ID, "does-not-exist")
