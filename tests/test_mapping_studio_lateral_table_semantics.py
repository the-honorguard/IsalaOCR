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

SOURCE_ID = "source-ef"
TABLE_LV = "table-lv"
TABLE_RV = "table-rv"


def _block(block_id: str, *, role: str, text: str, x1: int, table_id: str, column_index: int) -> dict:
    return {
        "block_id": block_id,
        "block_type": "table_cell",
        "role": role,
        "text": text,
        "normalized_text": text.lower(),
        "confidence": 0.95,
        "x1": x1, "y1": 0, "x2": x1 + 20, "y2": 20,
        "line_index": 0,
        "sequence_index": 0,
        "table_id": table_id,
        "row_index": 0,
        "column_index": column_index,
    }


def _relation(relation_id: str, *, label_block_id: str, value_block_id: str, table_id: str) -> dict:
    return {
        "relation_id": relation_id,
        "label_block_id": label_block_id,
        "value_block_id": value_block_id,
        "unit_block_id": "",
        "relation_type": "table_cell",
        "confidence": 0.95,
        "rank": 1,
        # Deliberately free of any left/right vocabulary: the only place the
        # operator recorded which side this table is comes from Stap 6
        # ("Tabelregio selecteren"), not from OCR'd header text.
        "context_text": "",
        "table_id": table_id,
        "row_index": 0,
        "value_column_index": 1,
    }


def _seed(raw_workspace: Path) -> None:
    # create_web_app()'s workspace_root() resolves through ProjectManager, so
    # fixtures must be seeded at that same resolved path (see the identical
    # note in test_roi_mapping_studio_skip_columns.py).
    workspace = resolve_project_workspace(raw_workspace)
    database = TrainingDatabase(workspace / "samples.sqlite3")
    config = load_config(ROOT / "application" / "config" / "app.yaml")
    ensure_default_field_definitions(database, config.profile)

    blocks = [
        _block("label-lv", role="label", text="Ejectiefractie", x1=0, table_id=TABLE_LV, column_index=0),
        _block("value-lv", role="value", text="56 %", x1=30, table_id=TABLE_LV, column_index=1),
        _block("label-rv", role="label", text="Ejectiefractie", x1=0, table_id=TABLE_RV, column_index=0),
        _block("value-rv", role="value", text="48 %", x1=30, table_id=TABLE_RV, column_index=1),
    ]
    relations = [
        _relation("relation-lv", label_block_id="label-lv", value_block_id="value-lv", table_id=TABLE_LV),
        _relation("relation-rv", label_block_id="label-rv", value_block_id="value-rv", table_id=TABLE_RV),
    ]
    database.replace_generic_detection(
        {
            "source_id": SOURCE_ID,
            "image_width": 200,
            "image_height": 100,
            "render_path": f"source_renders/{SOURCE_ID}.png",
            "detector_version": "test",
            "token_count": 4,
        },
        blocks,
        relations,
    )


def _post_save(app, **field_values: str):
    data = {
        "label_mapping_action": "save",
        "relation_id": ["relation-lv", "relation-rv"],
        "field_relation-lv": field_values["relation-lv"],
        "field_relation-rv": field_values["relation-rv"],
    }
    return app.test_client().post(
        f"/mapping-labels/{SOURCE_ID}", data=data, follow_redirects=True
    )


def test_bilateral_generic_field_needs_stap6_table_semantics_to_resolve(tmp_path: Path) -> None:
    """Regression test for the reported bug: two 'Ejectiefractie' rows (one
    per ventricle table) both map to the same generic 'family:ejection_fraction'
    dropdown option in the label-first Mapping Studio. Saving both must not
    fail with "cannot uniquely link" once the operator has told Stap 6 which
    table is which side - even when nothing in the OCR'd label/context text
    itself says "left"/"right".
    """
    workspace = tmp_path / "training" / "workspace"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.16.0")
    _seed(workspace)

    app = create_web_app(
        workspace,
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project,
    )
    resolved_workspace = resolve_project_workspace(workspace)
    database = TrainingDatabase(resolved_workspace / "samples.sqlite3")

    # Without a Stap 6 semantic table name, both rows are genuinely
    # indistinguishable to relation_lateral_side() and must be rejected
    # rather than silently guessed.
    response = _post_save(
        app,
        **{"relation-lv": "family:ejection_fraction", "relation-rv": "family:ejection_fraction"},
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "niet eenduidig koppelen" in body
    assert not database.list_mappings(SOURCE_ID, status="confirmed")

    # Stap 6 ("Tabelregio selecteren") is where the operator explicitly
    # assigns each table region's semantic left/right name.
    save_assignment(resolved_workspace, TABLE_LV, "Linker ventrikel")
    save_assignment(resolved_workspace, TABLE_RV, "Rechter ventrikel")

    response = _post_save(
        app,
        **{"relation-lv": "family:ejection_fraction", "relation-rv": "family:ejection_fraction"},
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "niet eenduidig koppelen" not in body

    mappings = {
        item["field_key"]: item
        for item in database.list_mappings(SOURCE_ID, status="confirmed")
    }
    assert set(mappings) == {"lv_ejection_fraction", "rv_ejection_fraction"}
    assert mappings["lv_ejection_fraction"]["relation_id"] == "relation-lv"
    assert mappings["rv_ejection_fraction"]["relation_id"] == "relation-rv"
