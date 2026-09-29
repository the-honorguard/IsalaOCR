from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.config import load_config
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.mapping import ensure_default_field_definitions
from isala_ocr.training.projects import resolve_project_workspace
from isala_ocr.training.recognition_ground_truth import save_unrecognized_panel_policy
from isala_ocr.training.table_panels import save_panel_profile
from isala_ocr.training.table_semantics import save_assignment
from isala_ocr.training.webui import create_web_app

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "panel-mismatch-source"
TABLE_ID = "panel-mismatch-table"
IMAGE_WIDTH, IMAGE_HEIGHT = 200, 100


def _block(block_id: str, *, role: str, text: str, column_index: int) -> dict:
    x1 = 0 if column_index == 0 else 30
    return {
        "block_id": block_id, "block_type": "table_cell", "role": role, "text": text,
        "normalized_text": text.lower(), "confidence": 0.95,
        "x1": x1, "y1": 0, "x2": x1 + 20, "y2": 20,
        "line_index": 0, "sequence_index": 0,
        "table_id": TABLE_ID, "row_index": 0, "column_index": column_index,
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

    # Panel Setup HAS a panel configured (top-left quarter of the image) --
    # but this fixture's table sits in the bottom-right quarter, so it will
    # never be matched to it. This reproduces the real report: Table Studio
    # correctly configured, Panel Setup geometry simply doesn't cover where
    # this table actually is.
    save_panel_profile(
        resolved_workspace,
        panels=[{"panel_id": "left", "name": "Links", "x1": 0.0, "y1": 0.0, "x2": 0.4, "y2": 0.4}],
        reference_source_id=SOURCE_ID, reference_width=IMAGE_WIDTH, reference_height=IMAGE_HEIGHT,
    )
    database.replace_generic_detection(
        {
            "source_id": SOURCE_ID, "image_width": IMAGE_WIDTH, "image_height": IMAGE_HEIGHT,
            "render_path": f"source_renders/{SOURCE_ID}.png", "detector_version": "test", "token_count": 2,
        },
        [
            _block("label1", role="label", text="Ejectiefractie", column_index=0),
            _block("value1", role="value", text="33 %", column_index=1),
        ],
        [{
            "relation_id": "relation1", "label_block_id": "label1", "value_block_id": "value1",
            "unit_block_id": "", "relation_type": "table_cell", "confidence": 0.95, "rank": 1,
            "context_text": "", "table_id": TABLE_ID, "row_index": 0, "value_column_index": 1,
        }],
    )
    # Resolve left/right unambiguously via Stap 6, independent of the
    # (deliberately mismatched) Panel Setup geometry under test.
    save_assignment(resolved_workspace, TABLE_ID, "Linker ventrikel")
    app = create_web_app(
        workspace, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project,
    )
    return app, database, resolved_workspace


def _post_studio(app, **form):
    return app.test_client().post(f"/mapping-labels/{SOURCE_ID}", data=form, follow_redirects=True)


def test_default_policy_blocks_saving_an_unrecognized_panel_relation(tmp_path: Path) -> None:
    app, database, _workspace = _make_app(tmp_path)

    body = _post_studio(
        app, label_mapping_action="save", relation_id=["relation1"],
        field_relation1="family:ejection_fraction",
    ).get_data(as_text=True)

    assert "paneel niet herkend" in body.casefold() or "geblokkeerd" in body.casefold()
    assert database.list_mappings(SOURCE_ID, status="confirmed") == []


def test_switching_policy_to_allow_lets_the_save_through(tmp_path: Path) -> None:
    app, database, workspace = _make_app(tmp_path)
    save_unrecognized_panel_policy(workspace, "allow")

    response = _post_studio(
        app, label_mapping_action="save", relation_id=["relation1"],
        field_relation1="family:ejection_fraction",
    )
    assert response.status_code == 200
    mappings = {item["field_key"] for item in database.list_mappings(SOURCE_ID, status="confirmed")}
    assert "lv_ejection_fraction" in mappings


def test_panel_policy_toggle_persists(tmp_path: Path) -> None:
    app, _database, workspace = _make_app(tmp_path)
    from isala_ocr.training.recognition_ground_truth import unrecognized_panel_policy

    assert unrecognized_panel_policy(workspace) == "block"
    response = app.test_client().post(
        f"/mapping-labels/{SOURCE_ID}",
        data={"label_mapping_action": "set_panel_policy", "panel_policy": "allow"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert unrecognized_panel_policy(workspace) == "allow"
