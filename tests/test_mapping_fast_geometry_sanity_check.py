"""``suggest_mappings_fast`` defers Pipeline-A ROI validation to value
materialization (see its docstring), but that means nothing else stood
between a corrupt detection and a stored mapping suggestion. A value block
whose box is evidently broken -- out of the image frame, or degenerate
(zero/negative width or height) -- must be rejected by a light, local sanity
check (``_geometry_looks_sane``) before it can ever become a suggestion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.mapping_fast import _geometry_looks_sane, suggest_mappings_fast

SOURCE_ID = "source-a"
TABLE_ID = "canonical-table-1"
IMAGE_WIDTH = 200
IMAGE_HEIGHT = 100


def _block(block_id: str, *, x1: int, y1: int, x2: int, y2: int, role: str = "value", text: str = "42") -> dict:
    return {
        "block_id": block_id, "block_type": "table_cell", "role": role, "text": text,
        "normalized_text": text.lower(), "confidence": 0.95, "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "line_index": 0, "sequence_index": 0, "table_id": TABLE_ID, "row_index": 0,
        "column_index": 0,
    }


def _relation(relation_id: str, *, label_block_id: str, value_block_id: str) -> dict:
    return {
        "relation_id": relation_id, "label_block_id": label_block_id, "value_block_id": value_block_id,
        "unit_block_id": "", "relation_type": "table_cell", "confidence": 0.95, "rank": 1,
        "context_text": "Panel A", "table_id": TABLE_ID, "row_index": 0,
        "value_column_index": 0,
    }


def _seed(workspace: Path, *, value_box: tuple[int, int, int, int]) -> TrainingDatabase:
    database = TrainingDatabase(workspace / "samples.sqlite3")
    database.upsert_field_definition("ejection_fraction", "Ejection Fraction", aliases=["EF"], active=True)
    x1, y1, x2, y2 = value_box
    blocks = [
        _block("value-a", x1=x1, y1=y1, x2=x2, y2=y2),
        _block("label-a", x1=0, y1=25, x2=20, y2=40, role="label", text="Ejection Fraction"),
    ]
    relations = [_relation("relation-a", label_block_id="label-a", value_block_id="value-a")]
    database.replace_localization_detection(
        {
            "source_id": SOURCE_ID, "image_width": IMAGE_WIDTH, "image_height": IMAGE_HEIGHT,
            "render_path": f"source_renders/{SOURCE_ID}.png", "detector_version": "test", "token_count": 5,
        },
        [],
        [{
            "table_id": TABLE_ID, "x1": 0, "y1": 0, "x2": 60, "y2": 40, "confidence": 0.95,
            "cells": [{"cell_id": "cell-0", "row_index": 0, "column_index": 0, "confidence": 0.95, "x1": 0, "y1": 0, "x2": 20, "y2": 20}],
        }],
    )
    database.replace_generic_detection(
        {
            "source_id": SOURCE_ID, "image_width": IMAGE_WIDTH, "image_height": IMAGE_HEIGHT,
            "render_path": f"source_renders/{SOURCE_ID}.png", "detector_version": "test", "token_count": 5,
        },
        blocks, relations,
    )
    return database


def test_suggest_mappings_fast_accepts_a_sane_value_block(tmp_path: Path) -> None:
    from isala_ocr.training.projects import resolve_project_workspace

    workspace = resolve_project_workspace(tmp_path / "training" / "workspace")
    database = _seed(workspace, value_box=(0, 0, 20, 20))

    suggestions = suggest_mappings_fast(database, SOURCE_ID)
    relation_ids = {str(item["relation_id"]) for item in suggestions}
    assert "relation-a" in relation_ids


def test_suggest_mappings_fast_rejects_out_of_frame_value_block(tmp_path: Path) -> None:
    from isala_ocr.training.projects import resolve_project_workspace

    workspace = resolve_project_workspace(tmp_path / "training" / "workspace")
    # x2/y2 both exceed the source's own 200x100 image bounds.
    database = _seed(workspace, value_box=(190, 90, 250, 140))

    suggestions = suggest_mappings_fast(database, SOURCE_ID)
    relation_ids = {str(item["relation_id"]) for item in suggestions}
    assert "relation-a" not in relation_ids, "an out-of-frame value box must never become a suggestion"


def test_suggest_mappings_fast_rejects_degenerate_value_block(tmp_path: Path) -> None:
    from isala_ocr.training.projects import resolve_project_workspace

    workspace = resolve_project_workspace(tmp_path / "training" / "workspace")
    # Zero-width box: x2 == x1.
    database = _seed(workspace, value_box=(20, 0, 20, 20))

    suggestions = suggest_mappings_fast(database, SOURCE_ID)
    relation_ids = {str(item["relation_id"]) for item in suggestions}
    assert "relation-a" not in relation_ids, "a degenerate (zero-area) value box must never become a suggestion"


@pytest.mark.parametrize(
    ("box", "expected"),
    [
        ((0, 0, 20, 20), True),
        ((-1, 0, 20, 20), False),  # x1 negative
        ((0, 0, IMAGE_WIDTH + 1, 20), False),  # x2 beyond the image width
        ((0, 0, 20, IMAGE_HEIGHT + 1), False),  # y2 beyond the image height
        ((5, 5, 5, 20), False),  # zero width (x2 == x1)
        ((5, 5, 20, 5), False),  # zero height (y2 == y1)
    ],
)
def test_geometry_looks_sane_unit(box: tuple[int, int, int, int], expected: bool) -> None:
    x1, y1, x2, y2 = box
    block = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
    assert _geometry_looks_sane(block, IMAGE_WIDTH, IMAGE_HEIGHT) is expected
