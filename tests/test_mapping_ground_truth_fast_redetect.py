from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
import pytest
from isala_ocr.config import load_config
from isala_ocr.dicom import hash_file
from isala_ocr.models import Box, OCRToken
from isala_ocr.ocr.base import OCREngine
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.mapping_ground_truth import canonical_table_regions
from isala_ocr.training.mapping_ground_truth_fast import (
    collect_mapping_from_canonical_gt,
)
from isala_ocr.training.table_cell_ground_truth import add_ground_truth_cell

ROOT = Path(__file__).resolve().parents[1]


class FixedTokenLocatorEngine(OCREngine):
    """A locator engine that always returns the same fixed OCR tokens.

    Stands in for a real (now presumably fixed) full-page OCR pass during a
    redetection attempt, independent of whatever image bytes are decoded.
    """

    def __init__(self, tokens: list[OCRToken]) -> None:
        self._tokens = tokens

    def recognize_many(self, images, whitelists=None):
        del whitelists
        return [list(self._tokens) for _ in images]

    def info(self):
        return {"provider": "fixed-token-fake"}


def _write_canonical_gt_shell(workspace: Path, source_id: str) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "table_cell_ground_truth.json").write_text(
        f"""{{
  "schema_version": 1,
  "type": "canonical_table_cell_ground_truth",
  "base_dataset_id": "test",
  "created_at": "2026-08-20T00:00:00+00:00",
  "updated_at": "2026-08-20T00:00:00+00:00",
  "revision": 1,
  "sources": {{
    "{source_id}": {{
      "source_id": "{source_id}",
      "split": "train",
      "review_completed": false,
      "review_completed_at": null,
      "cells": []
    }}
  }}
}}
""",
        encoding="utf-8",
    )


def test_redetection_recovers_a_source_stuck_with_zero_relations(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    image = np.full((100, 200, 3), 255, dtype=np.uint8)
    source_path = input_dir / "source.png"
    assert cv2.imwrite(str(source_path), image)
    source_id = hash_file(source_path)[:24]

    workspace = tmp_path / "training"
    _write_canonical_gt_shell(workspace, source_id)
    # integrate_table_regions() only treats a canonical region as a real
    # table (and stamps a matching table_id on its relations) once it has at
    # least 2 rows with at least one multi-cell row; a single-row grid falls
    # back to a generic, table_id-less relation and never gets panel context
    # attached. Use a 2x2 grid, like the geometry-reconstruction test in
    # test_mapping_canonical_gt_v3142.py.
    add_ground_truth_cell(workspace, source_id, (0, 0, 90, 22), panel_id="panel-a", panel_name="Panel A")
    add_ground_truth_cell(workspace, source_id, (100, 0, 160, 22), panel_id="panel-a", panel_name="Panel A")
    add_ground_truth_cell(workspace, source_id, (0, 32, 90, 54), panel_id="panel-a", panel_name="Panel A")
    add_ground_truth_cell(workspace, source_id, (100, 32, 160, 54), panel_id="panel-a", panel_name="Panel A")

    database = TrainingDatabase(workspace / "samples.sqlite3")
    # Seed a broken prior Detection/Recognition run, exactly like the one
    # reported in production: empty blocks/relations and zero OCR tokens.
    # Nothing else in this pipeline ever revisits such a source, so without
    # the redetection escape hatch it would stay stuck like this forever.
    database.replace_generic_detection(
        {
            "source_id": source_id,
            "image_width": 200,
            "image_height": 100,
            "render_path": f"source_renders/{source_id}.png",
            "detector_version": "test",
            "token_count": 0,
        },
        [],
        [],
    )

    config = load_config(ROOT / "application" / "config" / "app.yaml")
    tokens = [
        OCRToken("HR", 0.99, Box(10, 3, 35, 19)),
        OCRToken("75", 0.97, Box(110, 3, 140, 19)),
        OCRToken("SV", 0.98, Box(10, 35, 35, 51)),
        OCRToken("80", 0.96, Box(110, 35, 140, 51)),
    ]
    engine = FixedTokenLocatorEngine(tokens)

    with caplog.at_level(logging.WARNING):
        manifest = collect_mapping_from_canonical_gt(input_dir, workspace, config, engine)

    assert manifest["processed_sources"] == 1
    assert manifest["redetected_sources"] == 1
    assert manifest["ocr_performed"] is True

    relations = database.list_detected_relations(source_id)
    assert len(relations) >= 1

    # A recovered source must not still be reported as broken.
    assert not any(
        "bevat geen relaties" in record.getMessage() for record in caplog.records
    )

    # Mapping Studio resolves a relation's Table/Panel Setup panel from
    # context_text alone (table_id is a per-run hash that never matches a
    # panel_id) - without this, the Table Studio "Overslaan" (skip) column
    # filter silently stops applying to every relation this redetection path
    # produces, exactly like collector.py's own detection run already does.
    assert all("panel a" in relation["context_text"].casefold() for relation in relations)


def test_stale_relations_missing_panel_context_are_backfilled_without_redetection(
    tmp_path: Path,
) -> None:
    """A source that already has relations must also get panel context repaired.

    Before this fix, the "reuse existing relations" refresh step read
    Pipeline-A's detection_table_regions - a table_id space that never
    matches a canonical-GT relation's table_id - so it could never actually
    repair a relation's context_text no matter how many times Mapping
    preparation ran. A source stuck with relation_count > 0 but empty
    context_text (e.g. one already recovered once by the redetection escape
    hatch before this fix existed) needs this path, not the escape hatch
    (which only triggers at relation_count <= 0), to ever get fixed.
    """
    workspace = tmp_path / "training"
    source_id = "source-already-detected"
    _write_canonical_gt_shell(workspace, source_id)
    add_ground_truth_cell(workspace, source_id, (0, 0, 90, 22), panel_id="panel-a", panel_name="Panel A")
    add_ground_truth_cell(workspace, source_id, (100, 0, 160, 22), panel_id="panel-a", panel_name="Panel A")
    add_ground_truth_cell(workspace, source_id, (0, 32, 90, 54), panel_id="panel-a", panel_name="Panel A")
    add_ground_truth_cell(workspace, source_id, (100, 32, 160, 54), panel_id="panel-a", panel_name="Panel A")

    # The real table_id canonical_table_regions() will (deterministically)
    # assign to this panel's single table, so the seeded relation below is
    # indistinguishable from one a real detection run would have produced.
    [table_region] = canonical_table_regions(
        workspace, source_id, [], image_width=200, image_height=100
    )

    database = TrainingDatabase(workspace / "samples.sqlite3")
    label_block = {
        "block_id": "label-block", "block_type": "table_cell", "role": "label",
        "text": "HR", "normalized_text": "hr", "confidence": 0.9,
        "x1": 0, "y1": 0, "x2": 90, "y2": 22, "line_index": 0, "sequence_index": 0,
        "table_id": table_region.table_id, "row_index": 0, "column_index": 0,
    }
    value_block = {
        "block_id": "value-block", "block_type": "table_cell", "role": "value",
        "text": "75", "normalized_text": "75", "confidence": 0.9,
        "x1": 100, "y1": 0, "x2": 160, "y2": 22, "line_index": 0, "sequence_index": 0,
        "table_id": table_region.table_id, "row_index": 0, "column_index": 1,
    }
    relation = {
        "relation_id": "relation-stuck", "label_block_id": "label-block",
        "value_block_id": "value-block", "unit_block_id": "",
        "relation_type": "table_cell", "confidence": 0.9, "rank": 1,
        "context_text": "",
        "table_id": table_region.table_id, "row_index": 0, "value_column_index": 1,
    }
    database.replace_generic_detection(
        {
            "source_id": source_id,
            "image_width": 200,
            "image_height": 100,
            "render_path": f"source_renders/{source_id}.png",
            "detector_version": "test",
            "token_count": 5,
        },
        [label_block, value_block],
        [relation],
    )

    config = load_config(ROOT / "application" / "config" / "app.yaml")
    # relation_count is already > 0, so the redetection escape hatch never
    # runs and never touches locator_engine - it can be None, exactly like
    # test_mapping_ground_truth_fast_zero_relations.py's non-redetection cases.
    manifest = collect_mapping_from_canonical_gt(
        tmp_path / "input", workspace, config, None
    )

    assert manifest["processed_sources"] == 1
    assert manifest["redetected_sources"] == 0

    [stored] = database.list_detected_relations(source_id)
    assert "panel a" in stored["context_text"].casefold()


def test_redetection_is_skipped_when_source_file_is_not_in_the_current_input(
    tmp_path: Path,
) -> None:
    """If the original file can't be located, fall back to the old behavior.

    A stale detection_sources row can outlive the input selection it was
    produced from (e.g. the file was moved/removed). Redetection must not be
    attempted in that case; the existing skip-and-report path still applies.
    """
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    workspace = tmp_path / "training"
    workspace.mkdir()
    database = TrainingDatabase(workspace / "samples.sqlite3")
    database.replace_generic_detection(
        {
            "source_id": "missing-source",
            "image_width": 200,
            "image_height": 100,
            "render_path": "source_renders/missing-source.png",
            "detector_version": "test",
            "token_count": 0,
        },
        [],
        [],
    )

    config = load_config(ROOT / "application" / "config" / "app.yaml")
    engine = FixedTokenLocatorEngine([])

    with pytest.raises(RuntimeError) as excinfo:
        collect_mapping_from_canonical_gt(input_dir, workspace, config, engine)

    assert "1 bron(nen) hadden 0 OCR-tokens" in str(excinfo.value)
