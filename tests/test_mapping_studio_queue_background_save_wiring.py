from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.config import load_config
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.mapping import ensure_default_field_definitions
from isala_ocr.training.projects import resolve_project_workspace
from isala_ocr.training.table_semantics import save_assignment
from isala_ocr.training.webui import create_web_app

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "bg-save-source"
TABLE_ID = "bg-save-table"


def _block(block_id: str, *, role: str, text: str, column_index: int, row_index: int) -> dict:
    x1 = 0 if column_index == 0 else 30
    return {
        "block_id": block_id, "block_type": "table_cell", "role": role, "text": text,
        "normalized_text": text.lower(), "confidence": 0.95,
        "x1": x1, "y1": row_index * 20, "x2": x1 + 20, "y2": row_index * 20 + 20,
        "line_index": row_index, "sequence_index": row_index,
        "table_id": TABLE_ID, "row_index": row_index, "column_index": column_index,
    }


def _relation(relation_id: str, *, label_block_id: str, value_block_id: str, row_index: int) -> dict:
    return {
        "relation_id": relation_id, "label_block_id": label_block_id, "value_block_id": value_block_id,
        "unit_block_id": "", "relation_type": "table_cell", "confidence": 0.95, "rank": 1,
        "context_text": "", "table_id": TABLE_ID, "row_index": row_index, "value_column_index": 1,
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

    rows = [("Ejectiefractie", "ef"), ("Cardiac Output", "co")]
    blocks, relations = [], []
    for index, (label_text, tag) in enumerate(rows):
        label_id, value_id, relation_id = f"label-{tag}", f"value-{tag}", f"relation-{tag}"
        blocks.append(_block(label_id, role="label", text=label_text, column_index=0, row_index=index))
        blocks.append(_block(value_id, role="value", text="12.3", column_index=1, row_index=index))
        relations.append(_relation(relation_id, label_block_id=label_id, value_block_id=value_id, row_index=index))
    database.replace_generic_detection(
        {
            "source_id": SOURCE_ID, "image_width": 200, "image_height": 100,
            "render_path": f"source_renders/{SOURCE_ID}.png", "detector_version": "test", "token_count": len(blocks),
        },
        blocks, relations,
    )
    save_assignment(resolved_workspace, TABLE_ID, "Linker ventrikel")
    app = create_web_app(
        workspace, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project,
    )
    return app


def test_queue_page_wires_up_the_background_save_queue(tmp_path: Path) -> None:
    """The confirm/skip form must be handled by the background save queue
    (IsalaReviewQueue, review-queue.js - loaded globally by base.html), not
    left as a plain form submit that blocks on a slow write, and the page
    must carry a status widget the queue can report into.
    """
    app = _make_app(tmp_path)
    with app.test_request_context(f"/mapping-labels/{SOURCE_ID}/queue/relation-ef"):
        body = app.view_functions["label_mapping_queue_item"](SOURCE_ID, "relation-ef")
    assert "review-queue.js" in body
    assert "IsalaReviewQueue.createTaskQueue" in body
    assert 'id="save-queue-status"' in body
    assert "saveQueue.enqueue" in body
