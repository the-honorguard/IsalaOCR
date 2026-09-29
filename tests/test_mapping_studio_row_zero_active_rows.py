from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.config import load_config
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.mapping import ensure_default_field_definitions
from isala_ocr.training.projects import resolve_project_workspace
from isala_ocr.training.recognition_ground_truth import save_table_studio_roles
from isala_ocr.training.table_panels import save_panel_profile
from isala_ocr.training.webui import create_web_app

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "row-zero-source"
TABLE_ID = "table-row-zero"
IMAGE_WIDTH, IMAGE_HEIGHT = 400, 300


def _block(block_id: str, *, role: str, text: str, x1: int, row_index: int) -> dict:
    y1 = row_index * 24
    return {
        "block_id": block_id, "block_type": "table_cell", "role": role, "text": text,
        "normalized_text": text.lower(), "confidence": 0.95,
        "x1": x1, "y1": y1, "x2": x1 + 60, "y2": y1 + 20,
        "line_index": row_index, "sequence_index": row_index,
        "table_id": TABLE_ID, "row_index": row_index, "column_index": 0 if x1 == 10 else 1,
    }


def _relation(relation_id: str, *, label_block_id: str, value_block_id: str, row_index: int) -> dict:
    return {
        "relation_id": relation_id, "label_block_id": label_block_id, "value_block_id": value_block_id,
        "unit_block_id": "", "relation_type": "table_cell", "confidence": 0.95, "rank": 1,
        "context_text": "Left ventricle Volume Result", "table_id": TABLE_ID,
        "row_index": row_index, "value_column_index": 1,
    }


def test_row_index_zero_is_not_silently_treated_as_missing_and_excluded(tmp_path: Path) -> None:
    """Regression: relation_raster_row() used `relation.get("row_index") or -1`,
    which reads a perfectly real row_index of 0 (the very first row) as
    falsy and substitutes -1 -- a row that legitimately IS row 0 then never
    matches Table Studio's own "active rows" list (which correctly says
    row 0 is active), and silently vanishes from Mapping Studio entirely.
    """
    workspace = tmp_path / "training" / "workspace"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.16.0")
    resolved_workspace = resolve_project_workspace(workspace)
    database = TrainingDatabase(resolved_workspace / "samples.sqlite3")
    config = load_config(ROOT / "application" / "config" / "app.yaml")
    ensure_default_field_definitions(database, config.profile)

    blocks = [
        _block("label-r0", role="label", text="Ejection Fraction", x1=10, row_index=0),
        _block("value-r0", role="value", text="63 %", x1=100, row_index=0),
        _block("label-r1", role="label", text="Stroke Volume", x1=10, row_index=1),
        _block("value-r1", role="value", text="80 ml", x1=100, row_index=1),
    ]
    relations = [
        _relation("relation-r0", label_block_id="label-r0", value_block_id="value-r0", row_index=0),
        _relation("relation-r1", label_block_id="label-r1", value_block_id="value-r1", row_index=1),
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
        panels=[{"panel_id": "left", "name": "Links", "x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}],
        reference_source_id=SOURCE_ID, reference_width=IMAGE_WIDTH, reference_height=IMAGE_HEIGHT,
    )
    # Only row 0 is active for this panel - row 1 is switched off.
    save_table_studio_roles(resolved_workspace, {"left": {"0": "label", "1": "value"}}, rows={"left": [0]})

    app = create_web_app(
        workspace, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project,
    )
    with app.test_request_context(f"/mapping-labels/{SOURCE_ID}"):
        body = app.view_functions["label_mapping_studio"](SOURCE_ID)

    assert 'value="relation-r0"' in body
    assert 'value="relation-r1"' not in body
