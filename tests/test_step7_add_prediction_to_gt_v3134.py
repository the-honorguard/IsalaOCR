from __future__ import annotations

import json
from pathlib import Path

import pytest

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.table_cell_ground_truth import list_ground_truth_cells
from isala_ocr.training.table_model_comparison import (
    add_comparison_fp_to_ground_truth,
    table_cell_comparison_state,
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _seed(root: Path) -> None:
    dataset_id = "table-cells-test"
    base = root / "table_cell_datasets" / dataset_id
    (base / "images").mkdir(parents=True)
    _write_json(base / "manifest.json", {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "type": "table_cell_detection",
        "path": f"table_cell_datasets/{dataset_id}",
        "created_at": "2026-08-14T09:00:00+00:00",
        "panel_profile_updated_at": "2026-08-14T07:00:00+00:00",
        "review_fingerprint": "baseline-fingerprint",
        "annotation_count": 1,
        "panel_count": 1,
        "panels": [{
            "source_id": "source-a", "panel_id": "lv", "panel_name": "LV", "split": "val",
            "file_name": "source-a__lv.png", "box": [100, 50, 200, 150], "annotation_count": 1,
        }],
    })
    empty = {"images": [], "annotations": [], "categories": [{"id": 1, "name": "table_cell"}]}
    _write_json(base / "annotations" / "instance_train.json", empty)
    _write_json(base / "annotations" / "instance_test.json", empty)
    _write_json(base / "annotations" / "instance_val.json", {
        "images": [{"id": 1, "file_name": "source-a__lv.png", "width": 100, "height": 100}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 10, 10, 10], "area": 100, "iscrowd": 0}],
        "categories": [{"id": 1, "name": "table_cell"}],
    })
    (root / "table_cell_datasets" / "latest.txt").write_text(dataset_id + "\n", encoding="ascii")

    db = TrainingDatabase(root / "samples.sqlite3")
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO detection_sources(source_id,image_width,image_height,render_path,detector_version,
                token_count,block_count,relation_count,detected_at,updated_at,review_completed)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("source-a", 300, 200, "source_renders/source-a.png", "ppstructure", 0, 2, 0,
             "2026-08-14T10:00:00+00:00", "2026-08-14T10:00:00+00:00", 0),
        )
        conn.execute(
            """
            INSERT INTO detection_reviews(review_id,source_id,candidate_id,review_status,reason_code,
                relevance_status,relevance_reason,notes,original_x1,original_y1,original_x2,original_y2,
                corrected_x1,corrected_y1,corrected_x2,corrected_y2,reviewed_at,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("review-base", "source-a", "", "accepted", "", "relevant", "", "",
             110, 60, 120, 70, 110, 60, 120, 70,
             "2026-08-14T08:00:00+00:00", "2026-08-14T08:00:00+00:00", "2026-08-14T08:00:00+00:00"),
        )

    _write_json(root / "localization_detections" / "source-a.json", {
        "source_id": "source-a",
        "candidates": [
            {"candidate_id": "match", "source_kind": "table_cell", "confidence": 0.95, "x1": 110, "y1": 60, "x2": 120, "y2": 70},
            {"candidate_id": "new-real-cell", "source_kind": "table_cell", "confidence": 0.85, "x1": 160, "y1": 110, "x2": 180, "y2": 125},
        ],
    })


def test_fp_can_be_promoted_directly_to_canonical_gt_and_is_idempotent(tmp_path: Path) -> None:
    _seed(tmp_path)
    state = table_cell_comparison_state(tmp_path)
    fp = next(issue for panel in state["issue_panels"] for issue in panel["issues"] if issue["type"] == "fp")
    run_id = state["candidate"]["run_id"]

    result = add_comparison_fp_to_ground_truth(tmp_path, run_id, fp["issue_id"])
    assert result["already_present"] is False
    cells = list_ground_truth_cells(tmp_path, "source-a")
    promoted = next(cell for cell in cells if cell.get("provenance") == "step7_prediction_gt")
    assert [promoted[k] for k in ("x1", "y1", "x2", "y2")] == [160, 110, 180, 125]
    assert promoted["panel_id"] == "lv"

    again = add_comparison_fp_to_ground_truth(tmp_path, run_id, fp["issue_id"])
    assert again["already_present"] is True
    assert len(list_ground_truth_cells(tmp_path, "source-a")) == 2

    updated = table_cell_comparison_state(tmp_path, candidate_run_id=run_id)
    reviewed = next(issue for panel in updated["issue_panels"] for issue in panel["issues"] if issue["issue_id"] == fp["issue_id"])
    assert reviewed["review"]["decision"] == "gt_added"
    assert updated["open_issue_count"] == 0


def test_only_fp_predictions_can_use_direct_add_to_gt(tmp_path: Path) -> None:
    _seed(tmp_path)
    state = table_cell_comparison_state(tmp_path)
    # Fabricate a request for an unknown/non-FP issue by using a GT identifier.
    with pytest.raises(KeyError):
        add_comparison_fp_to_ground_truth(tmp_path, state["candidate"]["run_id"], "not-an-issue")


def test_step7_template_exposes_direct_add_to_gt_only_for_fp() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "application/src/isala_ocr/training/templates/table_model_comparison.html").read_text(encoding="utf-8")
    webui = (root / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    assert "+ Toevoegen aan GT" in template
    assert "issue.type == 'fp'" in template
    assert 'value="add_prediction_to_gt"' in template
    assert "add_comparison_fp_to_ground_truth" in webui
    assert "trainingsdataset is nu verouderd" in webui
