from __future__ import annotations

import json
from pathlib import Path

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.table_cell_ground_truth import (
    add_ground_truth_cell,
    ground_truth_path,
    ground_truth_review_state,
    list_ground_truth_sources,
    set_ground_truth_source_review_completed,
    update_ground_truth_cell,
)
from isala_ocr.training.table_quality import table_first_quality

ROOT = Path(__file__).resolve().parents[1]


def _write_legacy_gt(workspace: Path) -> None:
    path = ground_truth_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": 1,
        "type": "canonical_table_cell_ground_truth",
        "base_dataset_id": "dataset-v1",
        "base_review_fingerprint": "abc",
        "created_at": "2026-08-14T10:00:00+00:00",
        "updated_at": "2026-08-14T10:00:00+00:00",
        "revision": 1,
        "sources": {
            "source-a": {
                "source_id": "source-a",
                "split": "train",
                "cells": [{
                    "gt_id": "gt-1", "source_id": "source-a",
                    "x1": 10, "y1": 10, "x2": 40, "y2": 30,
                }],
            }
        },
    }), encoding="utf-8")


def test_legacy_canonical_gt_is_migrated_as_already_reviewed(tmp_path: Path) -> None:
    _write_legacy_gt(tmp_path)
    source = list_ground_truth_sources(tmp_path)[0]
    assert source["review_completed"] is True
    state = ground_truth_review_state(tmp_path)
    assert state["ready"] is True
    assert state["completed_source_count"] == 1
    assert state["open_source_count"] == 0


def test_gt_geometry_edit_reopens_only_that_source_and_reapproval_does_not_change_geometry_revision(tmp_path: Path) -> None:
    _write_legacy_gt(tmp_path)
    before = json.loads(ground_truth_path(tmp_path).read_text(encoding="utf-8"))
    update_ground_truth_cell(tmp_path, "source-a", "gt-1", (12, 10, 42, 30))
    state = ground_truth_review_state(tmp_path)
    assert state["ready"] is False
    assert state["open_source_count"] == 1

    after_edit = json.loads(ground_truth_path(tmp_path).read_text(encoding="utf-8"))
    assert after_edit["revision"] == before["revision"] + 1

    set_ground_truth_source_review_completed(tmp_path, "source-a", True)
    state = ground_truth_review_state(tmp_path)
    assert state["ready"] is True
    after_review = json.loads(ground_truth_path(tmp_path).read_text(encoding="utf-8"))
    assert after_review["revision"] == after_edit["revision"]


def test_new_gt_cell_reopens_source(tmp_path: Path) -> None:
    _write_legacy_gt(tmp_path)
    add_ground_truth_cell(tmp_path, "source-a", (50, 10, 80, 30))
    source = list_ground_truth_sources(tmp_path)[0]
    assert source["review_completed"] is False
    assert source["gt_count"] == 2


def test_canonical_gt_is_authoritative_table_first_mapping_gate(tmp_path: Path) -> None:
    _write_legacy_gt(tmp_path)
    db = TrainingDatabase(tmp_path / "samples.sqlite3")

    quality = table_first_quality(db)
    assert quality["ready"] is True
    assert quality["state"] == "canonical_gt_ready"
    assert quality["gate_source"] == "canonical_gt"
    assert quality["canonical_gt"]["gt_cell_count"] == 1
    assert quality["canonical_gt"]["open_source_count"] == 0

    update_ground_truth_cell(tmp_path, "source-a", "gt-1", (12, 10, 42, 30))
    quality = table_first_quality(db)
    assert quality["ready"] is False
    assert quality["state"] == "canonical_gt_needs_review"
    assert quality["canonical_gt"]["open_source_count"] == 1


def test_gt_studio_uses_cell_level_review_without_a_visible_source_approval() -> None:
    studio = (ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html").read_text(encoding="utf-8")
    webui = (ROOT / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    # set_ground_truth_source_review_completed() is called from routes_detection_review.py now.
    routes_detection_review = (
        ROOT / "application/src/isala_ocr/training/routes_detection_review.py"
    ).read_text(encoding="utf-8")

    assert 'class="review-dock-source" hidden' in studio
    assert 'id="source-done"' in studio
    assert "GT-afbeelding gecontroleerd" not in studio
    assert "Afbeelding klaar ✓" not in studio
    assert "markGtSourceDirty" in studio
    assert "set_ground_truth_source_review_completed" in routes_detection_review
    assert "Nieuwe modelpredictions tellen hier niet als open kandidaten" in webui
