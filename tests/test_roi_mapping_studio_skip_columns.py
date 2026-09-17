from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.projects import resolve_project_workspace
from isala_ocr.training.recognition_ground_truth import save_table_studio_roles
from isala_ocr.training.table_panels import save_panel_profile
from isala_ocr.training.webui import create_web_app

SOURCE_ID = "source-a"


TABLE_ID = "canonical-table-1"


def _block(
    block_id: str, *, role: str, text: str, x1: int, y1: int, x2: int, y2: int, column_index: int
) -> dict:
    return {
        "block_id": block_id,
        "block_type": "table_cell",
        "role": role,
        "text": text,
        "normalized_text": text.lower(),
        "confidence": 0.95,
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "line_index": 0,
        "sequence_index": 0,
        "table_id": TABLE_ID,
        "row_index": 0,
        "column_index": column_index,
    }


def _relation(relation_id: str, *, value_block_id: str, value_column_index: int, context_text: str) -> dict:
    return {
        "relation_id": relation_id,
        "label_block_id": "",
        "value_block_id": value_block_id,
        "unit_block_id": "",
        "relation_type": "table_cell",
        "confidence": 0.95,
        "rank": 1,
        "context_text": context_text,
        "table_id": TABLE_ID,
        "row_index": 0,
        "value_column_index": value_column_index,
    }


def _seed(raw_workspace: Path) -> None:
    # create_web_app()'s workspace_root() always resolves through
    # ProjectManager (unconditionally, unlike resolve_project_workspace()'s
    # CLI-side helpers), which bootstraps/rewrites a bare "training/workspace"
    # path into its default active project's own subdirectory. Seed fixtures
    # at that same resolved path, or the running app looks in a different
    # place than the test just wrote to.
    workspace = resolve_project_workspace(raw_workspace)
    database = TrainingDatabase(workspace / "samples.sqlite3")
    blocks = [
        _block("value-skip", role="value", text="42", x1=0, y1=0, x2=20, y2=20, column_index=0),
        _block("value-keep", role="value", text="75", x1=30, y1=0, x2=50, y2=20, column_index=1),
    ]
    relations = [
        _relation("relation-skip", value_block_id="value-skip", value_column_index=0, context_text="Panel A"),
        _relation("relation-keep", value_block_id="value-keep", value_column_index=1, context_text="Panel A"),
    ]
    # Give resolve_value_roi_box() a canonical table-cell to resolve each
    # value block's ROI against (Pipeline-B requires a valid Pipeline-A ROI
    # before a relation is even shown - unrelated to the skip-column filter
    # under test, but required for either relation to render at all).
    database.replace_localization_detection(
        {
            "source_id": SOURCE_ID,
            "image_width": 200,
            "image_height": 100,
            "render_path": f"source_renders/{SOURCE_ID}.png",
            "detector_version": "test",
            "token_count": 5,
        },
        [],
        [
            {
                "table_id": TABLE_ID,
                "x1": 0, "y1": 0, "x2": 60, "y2": 20,
                "confidence": 0.95,
                "cells": [
                    {"cell_id": "cell-0", "row_index": 0, "column_index": 0, "confidence": 0.95, "x1": 0, "y1": 0, "x2": 20, "y2": 20},
                    {"cell_id": "cell-1", "row_index": 0, "column_index": 1, "confidence": 0.95, "x1": 30, "y1": 0, "x2": 50, "y2": 20},
                ],
            }
        ],
    )
    database.replace_generic_detection(
        {
            "source_id": SOURCE_ID,
            "image_width": 200,
            "image_height": 100,
            "render_path": f"source_renders/{SOURCE_ID}.png",
            "detector_version": "test",
            "token_count": 5,
        },
        blocks,
        relations,
    )
    profile = save_panel_profile(
        workspace,
        panels=[{"name": "Panel A", "x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}],
        reference_source_id=SOURCE_ID,
        reference_width=200,
        reference_height=100,
    )
    panel_id = str(profile["panels"][0]["panel_id"])
    save_table_studio_roles(workspace, {panel_id: {"0": "skip", "1": "value"}})


def test_roi_mapping_studio_hides_relations_from_a_skip_column(tmp_path: Path) -> None:
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
    response = app.test_client().get(f"/mapping/{SOURCE_ID}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    # A relation whose value column Table Studio marked "Overslaan" (skip)
    # must be entirely absent, not merely hidden by CSS - it should not
    # reach the template's relation list or its embedded JSON preview data.
    assert "relation-skip" not in body
    assert "relation-keep" in body
