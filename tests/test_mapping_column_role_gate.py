"""Table Studio's per-column role config (label/value/unit/header/skip), set once
by an operator, now also gates the *automatic* mapping-suggestion engines
(``suggest_mappings`` / ``suggest_mappings_fast``), not just Mapping Studio's
review-list display filter (see ``test_roi_mapping_studio_skip_columns.py``).
A relation from a column an operator marked "Overslaan" (skip) must never
become a mapping suggestion -- confirmed or not -- when ``workspace`` is
passed, even if its label text would otherwise score a perfect match.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.mapping import suggest_mappings
from isala_ocr.training.mapping_fast import suggest_mappings_fast
from isala_ocr.training.projects import resolve_project_workspace
from isala_ocr.training.recognition_ground_truth import save_table_studio_roles
from isala_ocr.training.table_panels import save_panel_profile

SOURCE_ID = "source-a"
TABLE_ID = "canonical-table-1"


def _block(
    block_id: str, *, x1: int, y1: int, x2: int, y2: int, column_index: int, role: str = "value", text: str = "42",
) -> dict:
    return {
        "block_id": block_id, "block_type": "table_cell", "role": role, "text": text,
        "normalized_text": text.lower(), "confidence": 0.95, "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "line_index": 0, "sequence_index": 0, "table_id": TABLE_ID, "row_index": 0,
        "column_index": column_index,
    }


def _relation(
    relation_id: str, *, label_block_id: str, value_block_id: str, value_column_index: int,
) -> dict:
    return {
        "relation_id": relation_id, "label_block_id": label_block_id, "value_block_id": value_block_id,
        "unit_block_id": "", "relation_type": "table_cell", "confidence": 0.95, "rank": 1,
        "context_text": "Panel A", "table_id": TABLE_ID, "row_index": 0,
        "value_column_index": value_column_index,
    }


def _seed(workspace: Path) -> tuple[TrainingDatabase, str]:
    database = TrainingDatabase(workspace / "samples.sqlite3")
    # Two distinct fields/labels, one per relation, so the two never compete
    # for the same field slot -- the gate under test is column eligibility,
    # not the separate "one candidate per field" disambiguation logic.
    database.upsert_field_definition(
        "stroke_volume", "Stroke Volume", aliases=["SV"], preferred_unit="", active=True,
    )
    database.upsert_field_definition(
        "ejection_fraction", "Ejection Fraction", aliases=["EF"], preferred_unit="", active=True,
    )
    blocks = [
        _block("value-skip", x1=0, y1=0, x2=20, y2=20, column_index=0),
        _block("value-keep", x1=30, y1=0, x2=50, y2=20, column_index=1),
        _block("label-skip", x1=0, y1=25, x2=20, y2=40, column_index=0, role="label", text="Stroke Volume"),
        _block("label-keep", x1=30, y1=25, x2=50, y2=40, column_index=1, role="label", text="Ejection Fraction"),
    ]
    relations = [
        _relation("relation-skip", label_block_id="label-skip", value_block_id="value-skip", value_column_index=0),
        _relation("relation-keep", label_block_id="label-keep", value_block_id="value-keep", value_column_index=1),
    ]
    # suggest_mappings() (the non-table_first path) additionally requires a
    # Pipeline-A candidate overlapping each value block's box before it will
    # consider the relation at all (_pipeline_a_geometry_match) -- unrelated
    # to the column-role gate under test, but a real precondition either way.
    candidates = [
        {
            "candidate_id": f"candidate-{block['block_id']}", "confidence": 0.95, "source_kind": "text_geometry",
            "source_refs": [], "crop_path": "", "x1": block["x1"], "y1": block["y1"],
            "x2": block["x2"], "y2": block["y2"], "status": "proposed",
        }
        for block in blocks if block["role"] == "value"
    ]
    database.replace_localization_detection(
        {
            "source_id": SOURCE_ID, "image_width": 200, "image_height": 100,
            "render_path": f"source_renders/{SOURCE_ID}.png", "detector_version": "test", "token_count": 5,
        },
        candidates,
        [{
            "table_id": TABLE_ID, "x1": 0, "y1": 0, "x2": 60, "y2": 20, "confidence": 0.95,
            "cells": [
                {"cell_id": "cell-0", "row_index": 0, "column_index": 0, "confidence": 0.95, "x1": 0, "y1": 0, "x2": 20, "y2": 20},
                {"cell_id": "cell-1", "row_index": 0, "column_index": 1, "confidence": 0.95, "x1": 30, "y1": 0, "x2": 50, "y2": 20},
            ],
        }],
    )
    database.replace_generic_detection(
        {
            "source_id": SOURCE_ID, "image_width": 200, "image_height": 100,
            "render_path": f"source_renders/{SOURCE_ID}.png", "detector_version": "test", "token_count": 5,
        },
        blocks, relations,
    )
    profile = save_panel_profile(
        workspace, panels=[{"name": "Panel A", "x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}],
        reference_source_id=SOURCE_ID, reference_width=200, reference_height=100,
    )
    panel_id = str(profile["panels"][0]["panel_id"])
    save_table_studio_roles(workspace, {panel_id: {"0": "skip", "1": "value"}})
    return database, panel_id


def test_suggest_mappings_fast_without_workspace_ignores_table_studio(tmp_path: Path) -> None:
    """Baseline: unchanged, score-only behaviour when workspace is omitted."""
    workspace = resolve_project_workspace(tmp_path / "training" / "workspace")
    database, _ = _seed(workspace)

    suggestions = suggest_mappings_fast(database, SOURCE_ID)
    relation_ids = {str(item["relation_id"]) for item in suggestions}
    assert "relation-skip" in relation_ids, "without workspace, the skip-column relation is not gated"
    assert "relation-keep" in relation_ids


def test_suggest_mappings_fast_with_workspace_excludes_skip_column(tmp_path: Path) -> None:
    workspace = resolve_project_workspace(tmp_path / "training" / "workspace")
    database, _ = _seed(workspace)

    suggestions = suggest_mappings_fast(database, SOURCE_ID, workspace=workspace)
    relation_ids = {str(item["relation_id"]) for item in suggestions}
    assert "relation-skip" not in relation_ids, "Table Studio marked this column 'skip'; it must never be suggested"
    assert "relation-keep" in relation_ids, "the 'value' column should still be suggested/confirmed as before"


def test_suggest_mappings_with_workspace_excludes_skip_column(tmp_path: Path) -> None:
    """The slower ``suggest_mappings`` (non-table_first path) applies the same gate."""
    workspace = resolve_project_workspace(tmp_path / "training" / "workspace")
    database, _ = _seed(workspace)

    suggestions = suggest_mappings(database, SOURCE_ID, workspace=workspace)
    relation_ids = {str(item["relation_id"]) for item in suggestions}
    assert "relation-skip" not in relation_ids
    assert "relation-keep" in relation_ids


def test_unconfigured_panel_is_unaffected_by_table_studio_gate(tmp_path: Path) -> None:
    """A panel with no Table Studio configuration keeps its relations eligible."""
    workspace = resolve_project_workspace(tmp_path / "training" / "workspace")
    database = TrainingDatabase(workspace / "samples.sqlite3")
    database.upsert_field_definition("ejection_fraction", "Ejection Fraction", aliases=["EF"], active=True)
    blocks = [
        _block("value-a", x1=0, y1=0, x2=20, y2=20, column_index=0),
        _block("label-a", x1=0, y1=25, x2=20, y2=40, column_index=0, role="label", text="Ejection Fraction"),
    ]
    relations = [
        _relation("relation-a", label_block_id="label-a", value_block_id="value-a", value_column_index=0),
    ]
    database.replace_localization_detection(
        {
            "source_id": SOURCE_ID, "image_width": 200, "image_height": 100,
            "render_path": f"source_renders/{SOURCE_ID}.png", "detector_version": "test", "token_count": 5,
        },
        [],
        [{
            "table_id": TABLE_ID, "x1": 0, "y1": 0, "x2": 60, "y2": 20, "confidence": 0.95,
            "cells": [{"cell_id": "cell-0", "row_index": 0, "column_index": 0, "confidence": 0.95, "x1": 0, "y1": 0, "x2": 20, "y2": 20}],
        }],
    )
    database.replace_generic_detection(
        {
            "source_id": SOURCE_ID, "image_width": 200, "image_height": 100,
            "render_path": f"source_renders/{SOURCE_ID}.png", "detector_version": "test", "token_count": 5,
        },
        blocks, relations,
    )
    # No save_panel_profile()/save_table_studio_roles() call at all: no Table
    # Studio configuration exists anywhere for this project.

    suggestions = suggest_mappings_fast(database, SOURCE_ID, workspace=workspace)
    relation_ids = {str(item["relation_id"]) for item in suggestions}
    assert "relation-a" in relation_ids, "an unconfigured panel must not be gated by a missing Table Studio entry"
