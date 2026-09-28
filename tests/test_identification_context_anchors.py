"""``_identification_stage_data``'s ``context_anchors`` (routes_documents.py)
must show *where* a window's Links/Rechts identification text was actually
OCR'd from, not just the resolved text string.

Before this, STAP 2.5 (the proefpagina compare screen) only listed the
per-field ``context_text`` string next to every single value cell -- the
same string repeated for every row in the table, with no visible anchor
proving it came from a real spot on the image. A user debugging a window
stuck on "Onbekend" had no way to see whether OCR actually read the header
text, misread it, or never found it at all. ``context_anchors`` reconstructs
the exact header row(s) ``integrate_table_regions()`` built ``table_context``
from (row_index 0-2 with no value-looking cell), one anchor box per row.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.routes_documents import _identification_stage_data

SOURCE_ID = "source-a"


def _cell(table_id: str, row_index: int, column_index: int, text: str, box: tuple[int, int, int, int]) -> dict:
    x1, y1, x2, y2 = box
    return {
        "block_id": f"{table_id}-{row_index}-{column_index}", "block_type": "table_cell",
        "table_id": table_id, "row_index": row_index, "column_index": column_index,
        "text": text, "x1": x1, "y1": y1, "x2": x2, "y2": y2,
    }


def _write_sources(workspace: Path) -> None:
    localization_root = workspace / "localization_detections"
    localization_root.mkdir(parents=True, exist_ok=True)
    (localization_root / f"{SOURCE_ID}.json").write_text(json.dumps({
        "image_width": 100, "image_height": 400,
        "tables": [
            {"x1": 0, "y1": 0, "x2": 100, "y2": 100},
            {"x1": 0, "y1": 200, "x2": 100, "y2": 300},
        ],
    }), encoding="utf-8")

    blocks = [
        # Top window (V1): two eligible header rows, then a data row with a
        # value-looking cell that must NOT be treated as a header.
        _cell("t1", 0, 0, "Left ventricle Volume Result", (0, 10, 100, 30)),
        _cell("t1", 1, 0, "Endo Volume", (0, 40, 50, 60)),
        _cell("t1", 1, 1, "Normal Values Chuang", (50, 40, 100, 60)),
        _cell("t1", 2, 0, "Cardiac Output", (0, 70, 50, 90)),
        _cell("t1", 2, 1, "9.5 L/min", (50, 70, 100, 90)),
        # Bottom window (V2): a single header row.
        _cell("t2", 0, 0, "Right ventricle Volume Result", (0, 210, 100, 230)),
    ]
    generic_root = workspace / "generic_detections"
    generic_root.mkdir(parents=True, exist_ok=True)
    (generic_root / f"{SOURCE_ID}.json").write_text(json.dumps({"blocks": blocks, "relations": []}), encoding="utf-8")


def _stage_data(workspace: Path) -> dict:
    database = TrainingDatabase(workspace / "samples.sqlite3")
    data = _identification_stage_data(
        SOURCE_ID, workspace_root=workspace,
        safe_workspace_file=lambda relative: workspace / relative,
        database=database,
    )
    assert data is not None
    return data


def test_header_rows_become_anchors_with_the_right_window_and_side(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write_sources(workspace)

    anchors = _stage_data(workspace)["context_anchors"]
    by_text = {anchor["text"]: anchor for anchor in anchors}

    assert set(by_text) == {"Left ventricle Volume Result", "Endo Volume Normal Values Chuang", "Right ventricle Volume Result"}

    left_header = by_text["Left ventricle Volume Result"]
    assert left_header["window_index"] == 1
    assert left_header["side"] == "left"
    assert (left_header["x1"], left_header["y1"], left_header["x2"], left_header["y2"]) == (0, 10, 100, 30)

    right_header = by_text["Right ventricle Volume Result"]
    assert right_header["window_index"] == 2
    assert right_header["side"] == "right"

    # A row with no left/right vocabulary is still a valid identification
    # anchor (it shows what OCR read there), just with an unresolved side.
    assert by_text["Endo Volume Normal Values Chuang"]["side"] == "unknown"
    assert by_text["Endo Volume Normal Values Chuang"]["window_index"] == 1


def test_a_value_looking_row_is_never_treated_as_a_header_anchor(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write_sources(workspace)

    anchors = _stage_data(workspace)["context_anchors"]
    assert not any("Cardiac Output" in anchor["text"] or "9.5 L/min" in anchor["text"] for anchor in anchors)
