"""``_cells_stage_data`` (routes_documents.py) must read a cell's OCR text from
whichever block type a source actually has.

A table-first-processed source's ``generic_detections`` has only
``block_type: "table_cell"`` blocks (see ``generic_detection.py``'s
``integrate_table_regions``); a fusion-strategy source (including job 61's
proefpagina reruns, which force fusion for their own mapping pass) has
``block_type: "semantic"`` blocks instead. Before this fix, only "semantic"
was read, so a table-first source's cell grid rendered as entirely empty
despite real per-cell text existing -- first noticed by comparing a
proefpagina rerun (fusion, text showed) against its trainingspipeline origin
(table-first, text was blank) on the same compare screen.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.routes_documents import _cells_stage_data

SOURCE_ID = "source-a"
TABLE_ID = "canonical-table-1"


def _localization_json(workspace: Path) -> None:
    root = workspace / "localization_detections"
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{SOURCE_ID}.json").write_text(json.dumps({
        "image_width": 100, "image_height": 50,
        "tables": [{
            "table_id": TABLE_ID, "x1": 0, "y1": 0, "x2": 100, "y2": 50,
            "cells": [
                {"cell_id": "cell-0", "row_index": 0, "column_index": 0, "confidence": 0.9, "x1": 0, "y1": 0, "x2": 50, "y2": 50},
            ],
        }],
    }), encoding="utf-8")


def _generic_detections_json(workspace: Path, blocks: list[dict]) -> None:
    root = workspace / "generic_detections"
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{SOURCE_ID}.json").write_text(json.dumps({"blocks": blocks, "relations": []}), encoding="utf-8")


def _block(block_id: str, *, block_type: str, text: str) -> dict:
    # Centered inside the single cell (0,0)-(50,50) from _localization_json.
    return {"block_id": block_id, "block_type": block_type, "text": text, "x1": 10, "y1": 10, "x2": 40, "y2": 40}


def _stage_data(workspace: Path):
    database = TrainingDatabase(workspace / "samples.sqlite3")
    return _cells_stage_data(
        SOURCE_ID, workspace_root=workspace,
        safe_workspace_file=lambda relative: workspace / relative,
        database=database,
    )


def _cell_text(data: dict) -> str:
    cell = data["windows"][0]["grid"][0][0]
    return str(cell["text"]) if cell else ""


def test_table_first_source_reads_table_cell_text(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _localization_json(workspace)
    _generic_detections_json(workspace, [_block("b1", block_type="table_cell", text="210.4 ml")])

    data = _stage_data(workspace)
    assert data is not None
    assert _cell_text(data) == "210.4 ml"


def test_fusion_source_still_reads_semantic_text(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _localization_json(workspace)
    _generic_detections_json(workspace, [_block("b1", block_type="semantic", text="210.4 ml")])

    data = _stage_data(workspace)
    assert data is not None
    assert _cell_text(data) == "210.4 ml"


def test_table_cell_text_is_not_duplicated_by_a_coincident_semantic_block(tmp_path: Path) -> None:
    """When both block types cover the same cell, table_cell wins outright -- no concatenation."""
    workspace = tmp_path / "workspace"
    _localization_json(workspace)
    _generic_detections_json(workspace, [
        _block("b1", block_type="table_cell", text="210.4 ml"),
        _block("b2", block_type="semantic", text="210.4 ml"),
    ])

    data = _stage_data(workspace)
    assert data is not None
    assert _cell_text(data) == "210.4 ml", "table_cell text must win outright, not be concatenated with semantic"
