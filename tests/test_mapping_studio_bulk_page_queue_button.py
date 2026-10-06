from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.config import load_config
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.mapping import ensure_default_field_definitions
from isala_ocr.training.projects import resolve_project_workspace
from isala_ocr.training.webui import create_web_app

ROOT = Path(__file__).resolve().parents[1]
DONE_SOURCE = "done-source"
OPEN_SOURCE = "open-source"


def _seed(database: TrainingDatabase, source_id: str, *, confirm: bool) -> None:
    table_id = f"table-{source_id}"
    label_id, value_id, relation_id = f"label-{source_id}", f"value-{source_id}", f"relation-{source_id}"
    database.replace_generic_detection(
        {
            "source_id": source_id, "image_width": 200, "image_height": 100,
            "render_path": f"source_renders/{source_id}.png", "detector_version": "test", "token_count": 2,
        },
        [
            {
                "block_id": label_id, "block_type": "table_cell", "role": "label", "text": "Ejectiefractie",
                "normalized_text": "ejectiefractie", "confidence": 0.95,
                "x1": 0, "y1": 0, "x2": 20, "y2": 20, "line_index": 0, "sequence_index": 0,
                "table_id": table_id, "row_index": 0, "column_index": 0,
            },
            {
                "block_id": value_id, "block_type": "table_cell", "role": "value", "text": "40 %",
                "normalized_text": "40 %", "confidence": 0.95,
                "x1": 30, "y1": 0, "x2": 50, "y2": 20, "line_index": 0, "sequence_index": 0,
                "table_id": table_id, "row_index": 0, "column_index": 1,
            },
        ],
        [{
            "relation_id": relation_id, "label_block_id": label_id, "value_block_id": value_id,
            "unit_block_id": "", "relation_type": "table_cell", "confidence": 0.95, "rank": 1,
            "context_text": "", "table_id": table_id, "row_index": 0, "value_column_index": 1,
        }],
    )
    if confirm:
        database.sync_relation_mappings(
            source_id, [{"relation_id": relation_id, "field_key": "lv_ejection_fraction", "notes": "label-first mapping"}]
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
    _seed(database, DONE_SOURCE, confirm=True)
    _seed(database, OPEN_SOURCE, confirm=False)
    app = create_web_app(
        workspace, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project,
    )
    return app


def test_queue_button_on_a_fully_mapped_source_still_links_to_the_global_queue(tmp_path: Path) -> None:
    """Regression: the button used to be disabled ('Wachtrij doorlopen (0)')
    whenever *this* source had nothing pending, even though other sources
    still had open work - forcing the operator to hunt down a source with
    open labels by hand before they could even start the queue."""
    app = _make_app(tmp_path)
    with app.test_request_context(f"/mapping-labels/{DONE_SOURCE}"):
        body = app.view_functions["label_mapping_studio"](DONE_SOURCE)
    assert 'class="button is-disabled"' not in body
    assert '/mapping-labels/queue"' in body

    with app.test_request_context("/mapping-labels/queue"):
        response = app.view_functions["label_mapping_queue_global_start"]()
    assert response.status_code == 302
    assert f"/mapping-labels/{OPEN_SOURCE}/queue/" in response.headers["Location"]
