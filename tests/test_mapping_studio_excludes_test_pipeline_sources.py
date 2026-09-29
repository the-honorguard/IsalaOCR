from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.config import load_config
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.mapping import ensure_default_field_definitions
from isala_ocr.training.projects import resolve_project_workspace
from isala_ocr.training.test_pipeline_sources import record_test_pipeline_source
from isala_ocr.training.webui import create_web_app

ROOT = Path(__file__).resolve().parents[1]
TRAINING_SOURCE = "training-source"
PROEFPAGINA_SOURCE = "proefpagina-source"


def _seed_source(database: TrainingDatabase, source_id: str) -> None:
    table_id = f"table-{source_id}"
    database.replace_generic_detection(
        {
            "source_id": source_id, "image_width": 200, "image_height": 100,
            "render_path": f"source_renders/{source_id}.png", "detector_version": "test", "token_count": 2,
        },
        [
            {
                "block_id": f"label-{source_id}", "block_type": "table_cell", "role": "label",
                "text": "Ejectiefractie", "normalized_text": "ejectiefractie", "confidence": 0.95,
                "x1": 0, "y1": 0, "x2": 20, "y2": 20, "line_index": 0, "sequence_index": 0,
                "table_id": table_id, "row_index": 0, "column_index": 0,
            },
            {
                "block_id": f"value-{source_id}", "block_type": "table_cell", "role": "value",
                "text": "40 %", "normalized_text": "40 %", "confidence": 0.95,
                "x1": 30, "y1": 0, "x2": 50, "y2": 20, "line_index": 0, "sequence_index": 0,
                "table_id": table_id, "row_index": 0, "column_index": 1,
            },
        ],
        [{
            "relation_id": f"relation-{source_id}", "label_block_id": f"label-{source_id}",
            "value_block_id": f"value-{source_id}", "unit_block_id": "", "relation_type": "table_cell",
            "confidence": 0.95, "rank": 1, "context_text": "", "table_id": table_id,
            "row_index": 0, "value_column_index": 1,
        }],
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

    _seed_source(database, TRAINING_SOURCE)
    _seed_source(database, PROEFPAGINA_SOURCE)
    record_test_pipeline_source(resolved_workspace, PROEFPAGINA_SOURCE, origin_source_id=TRAINING_SOURCE)

    app = create_web_app(
        workspace, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project,
    )
    return app, database, resolved_workspace


def test_bulk_page_source_dropdown_excludes_proefpagina_reruns(tmp_path: Path) -> None:
    # Bypasses enforce_primary_workflow_gate (webui.py's before_request hook):
    # this fixture seeds only the Mapping-relevant tables directly, without
    # the full upstream pipeline the gate otherwise requires before a plain
    # GET is let through (see test_mapping_studio_label_history_autofill.py).
    app, _database, _workspace = _make_app(tmp_path)
    with app.test_request_context(f"/mapping-labels/{TRAINING_SOURCE}"):
        body = app.view_functions["label_mapping_studio"](TRAINING_SOURCE)
    assert f'value="{TRAINING_SOURCE}"' in body
    assert f'value="{PROEFPAGINA_SOURCE}"' not in body


def test_global_queue_never_lands_on_a_proefpagina_source(tmp_path: Path) -> None:
    app, _database, _workspace = _make_app(tmp_path)
    with app.test_request_context("/mapping-labels/queue"):
        response = app.view_functions["label_mapping_queue_global_start"]()
    assert response.status_code == 302
    assert f"/mapping-labels/{TRAINING_SOURCE}/queue/" in response.headers["Location"]
    assert PROEFPAGINA_SOURCE not in response.headers["Location"]


def test_mapping_index_never_redirects_into_a_proefpagina_source(tmp_path: Path) -> None:
    app, _database, _workspace = _make_app(tmp_path)
    with app.test_request_context("/mapping-labels"):
        response = app.view_functions["label_mapping_index"]()
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/mapping-labels/{TRAINING_SOURCE}")
