from __future__ import annotations

import json
from pathlib import Path

import pytest

from isala_ocr.training import table_model_comparison
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.table_cell_ground_truth import ground_truth_review_state
from isala_ocr.training.table_model_comparison import (
    BASELINE_RUN_ID,
    review_comparison_issue,
    review_comparison_issues_bulk,
    table_cell_comparison_state,
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _seed_dataset(root: Path) -> str:
    dataset_id = "table-cells-test"
    base = root / "table_cell_datasets" / dataset_id
    (base / "images").mkdir(parents=True)
    _write_json(
        base / "manifest.json",
        {
            "schema_version": 1,
            "dataset_id": dataset_id,
            "type": "table_cell_detection",
            "path": f"table_cell_datasets/{dataset_id}",
            "created_at": "2026-08-14T09:00:00+00:00",
            "panel_profile_updated_at": "2026-08-14T07:00:00+00:00",
            "annotation_count": 2,
            "panel_count": 1,
            "panels": [
                {
                    "source_id": "source-a",
                    "panel_id": "lv",
                    "panel_name": "LV",
                    "split": "val",
                    "file_name": "source-a__lv.png",
                    "box": [0, 0, 100, 100],
                    "annotation_count": 2,
                }
            ],
        },
    )
    _write_json(base / "validation.json", {"valid": True})
    empty = {"images": [], "annotations": [], "categories": [{"id": 1, "name": "table_cell"}]}
    _write_json(base / "annotations" / "instance_train.json", empty)
    _write_json(base / "annotations" / "instance_test.json", empty)
    _write_json(
        base / "annotations" / "instance_val.json",
        {
            "images": [{"id": 1, "file_name": "source-a__lv.png", "width": 100, "height": 100}],
            "annotations": [
                {"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 10, 10, 10], "area": 100, "iscrowd": 0},
                {"id": 2, "image_id": 1, "category_id": 1, "bbox": [10, 30, 10, 10], "area": 100, "iscrowd": 0},
            ],
            "categories": [{"id": 1, "name": "table_cell"}],
        },
    )
    (root / "table_cell_datasets" / "latest.txt").write_text(dataset_id + "\n", encoding="ascii")
    return dataset_id


def _seed_baseline_and_current(root: Path, dataset_id: str) -> None:
    db = TrainingDatabase(root / "samples.sqlite3")
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO detection_sources(source_id,image_width,image_height,render_path,detector_version,
                token_count,block_count,relation_count,detected_at,updated_at,review_completed)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("source-a", 100, 100, "source_renders/source-a.png", "ppstructure", 0, 3, 0,
             "2026-08-14T10:00:00+00:00", "2026-08-14T10:00:00+00:00", 0),
        )
        # The initial Step-4 machine prediction merged two real cells.  The review
        # row preserves that original detector geometry even after later Step-3 runs.
        conn.execute(
            """
            INSERT INTO detection_reviews(review_id,source_id,candidate_id,review_status,reason_code,
                relevance_status,relevance_reason,notes,original_x1,original_y1,original_x2,original_y2,
                corrected_x1,corrected_y1,corrected_x2,corrected_y2,reviewed_at,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("review-base", "source-a", "", "rejected", "merged_fields", "unreviewed", "", "",
             10, 10, 20, 40, 10, 10, 20, 40,
             "2026-08-14T08:00:00+00:00", "2026-08-14T08:00:00+00:00", "2026-08-14T08:00:00+00:00"),
        )

    _write_json(
        root / "localization_detections" / "source-a.json",
        {
            "source_id": "source-a",
            "candidates": [
                {"candidate_id": "new-1", "source_kind": "table_cell", "confidence": 0.95, "x1": 10, "y1": 10, "x2": 20, "y2": 20},
                {"candidate_id": "new-2", "source_kind": "table_cell", "confidence": 0.94, "x1": 10, "y1": 30, "x2": 20, "y2": 40},
                {"candidate_id": "extra", "source_kind": "table_cell", "confidence": 0.70, "x1": 60, "y1": 60, "x2": 70, "y2": 70},
            ],
        },
    )

    model_root = root / "table_cell_models" / "table-model-1"
    (model_root / "inference").mkdir(parents=True)
    (model_root / "inference" / "inference.yml").write_text("model: table\n", encoding="utf-8")
    active = {
        "model_id": "table-model-1",
        "model_name": "RT-DETR-L_wireless_table_cell_det",
        "run_id": "train-run-1",
        "dataset_id": dataset_id,
        "device": "gpu:0",
        "inference_dir": "table_cell_models/table-model-1/inference",
        "created_at": "2026-08-14T09:30:00+00:00",
        "activated_at": "2026-08-14T09:45:00+00:00",
        "active": True,
    }
    _write_json(model_root / "model.json", active)
    _write_json(root / "table_cell_models" / "active.json", active)


def test_step7_compares_current_detection_to_frozen_step4_ground_truth(tmp_path: Path) -> None:
    dataset_id = _seed_dataset(tmp_path)
    _seed_baseline_and_current(tmp_path, dataset_id)

    state = table_cell_comparison_state(tmp_path)
    assert state["ready"] is True
    assert state["reference"]["run_id"] == BASELINE_RUN_ID
    assert state["candidate"]["model_id"] == "table-model-1"
    assert state["candidate"]["metrics"]["gt_total"] == 2
    assert state["candidate"]["metrics"]["tp"] == 2
    assert state["candidate"]["metrics"]["fn"] == 0
    assert state["candidate"]["metrics"]["fp"] == 1
    assert state["candidate"]["metrics"]["recall"] == 1.0
    assert state["reference"]["metrics"]["merged"] == 1
    assert state["delta"]["fn"] < 0
    assert state["open_issue_count"] == 1


def test_new_step3_run_reopens_ground_truth_review_for_all_covered_sources(tmp_path: Path) -> None:
    dataset_id = _seed_dataset(tmp_path)
    _seed_baseline_and_current(tmp_path, dataset_id)

    table_cell_comparison_state(tmp_path)

    review_state = ground_truth_review_state(tmp_path)
    assert review_state["source_count"] == 1
    assert review_state["completed_source_count"] == 0
    assert review_state["ready"] is False


def test_step7_followup_review_is_run_scoped_and_does_not_mutate_ground_truth(tmp_path: Path) -> None:
    dataset_id = _seed_dataset(tmp_path)
    _seed_baseline_and_current(tmp_path, dataset_id)
    before = (tmp_path / "table_cell_datasets" / dataset_id / "annotations" / "instance_val.json").read_text(encoding="utf-8")
    state = table_cell_comparison_state(tmp_path)
    issue = state["issue_panels"][0]["issues"][0]
    run_id = state["candidate"]["run_id"]

    review_comparison_issue(tmp_path, run_id, issue["issue_id"], "model_error")
    updated = table_cell_comparison_state(tmp_path, candidate_run_id=run_id)
    assert updated["reviewed_issue_count"] == 1
    assert updated["open_issue_count"] == 0
    after = (tmp_path / "table_cell_datasets" / dataset_id / "annotations" / "instance_val.json").read_text(encoding="utf-8")
    assert after == before


def test_step7_geometry_exposes_functional_quality_and_accepts_functional_ok(tmp_path: Path) -> None:
    dataset_id = _seed_dataset(tmp_path)
    _seed_baseline_and_current(tmp_path, dataset_id)
    # Keep the full 10x10 GT cell inside the prediction, but add 2 px above and
    # below. IoU drops below the strict 75% geometry limit while GT coverage is
    # 100% and prediction excess remains below the 30% review-hint limit.
    detections = json.loads((tmp_path / "localization_detections" / "source-a.json").read_text(encoding="utf-8"))
    detections["candidates"][0].update({"x1": 10, "y1": 8, "x2": 20, "y2": 22})
    _write_json(tmp_path / "localization_detections" / "source-a.json", detections)

    before = (tmp_path / "table_cell_datasets" / dataset_id / "annotations" / "instance_val.json").read_text(encoding="utf-8")
    state = table_cell_comparison_state(tmp_path)
    geometry = next(
        issue
        for panel in state["issue_panels"]
        for issue in panel["issues"]
        if issue["type"] == "geometry"
    )
    assert geometry["gt_coverage"] == pytest.approx(1.0)
    assert geometry["prediction_excess"] == pytest.approx(2 / 7)
    assert geometry["functional_candidate"] is True

    run_id = state["candidate"]["run_id"]
    review_comparison_issue(tmp_path, run_id, geometry["issue_id"], "functional_ok")
    reviewed = table_cell_comparison_state(tmp_path, candidate_run_id=run_id)
    reviewed_geometry = next(
        issue
        for panel in reviewed["issue_panels"]
        for issue in panel["issues"]
        if issue["issue_id"] == geometry["issue_id"]
    )
    assert reviewed_geometry["review"]["decision"] == "functional_ok"
    assert reviewed["reviewed_issue_count"] >= 1
    assert (tmp_path / "table_cell_datasets" / dataset_id / "annotations" / "instance_val.json").read_text(encoding="utf-8") == before


def test_step7_functional_ok_is_restricted_to_geometry_issues(tmp_path: Path) -> None:
    dataset_id = _seed_dataset(tmp_path)
    _seed_baseline_and_current(tmp_path, dataset_id)
    state = table_cell_comparison_state(tmp_path)
    fp = next(
        issue
        for panel in state["issue_panels"]
        for issue in panel["issues"]
        if issue["type"] == "fp"
    )
    with pytest.raises(ValueError, match="alleen geldig voor geometrie"):
        review_comparison_issue(tmp_path, state["candidate"]["run_id"], fp["issue_id"], "functional_ok")


def test_step7_gt_check_reopens_only_the_affected_source_for_gt_review(tmp_path: Path) -> None:
    dataset_id = _seed_dataset(tmp_path)
    _seed_baseline_and_current(tmp_path, dataset_id)
    state = table_cell_comparison_state(tmp_path)
    fp = next(
        issue
        for panel in state["issue_panels"]
        for issue in panel["issues"]
        if issue["type"] == "fp"
    )

    review_comparison_issue(tmp_path, state["candidate"]["run_id"], fp["issue_id"], "gt_check")

    review_state = ground_truth_review_state(tmp_path)
    source = next(item for item in review_state["sources"] if item["source_id"] == "source-a")
    assert source["review_completed"] is False
    assert review_state["ready"] is False


def test_review_comparison_issues_bulk_writes_reviews_once(tmp_path: Path, monkeypatch) -> None:
    dataset_id = _seed_dataset(tmp_path)
    _seed_baseline_and_current(tmp_path, dataset_id)
    # Add a second stray candidate away from any GT cell so this run carries two
    # independent fp issues, enough to prove a bulk call covers more than one
    # issue in its single write.
    detections = json.loads((tmp_path / "localization_detections" / "source-a.json").read_text(encoding="utf-8"))
    detections["candidates"].append(
        {"candidate_id": "extra-2", "source_kind": "table_cell", "confidence": 0.65, "x1": 80, "y1": 80, "x2": 90, "y2": 90}
    )
    _write_json(tmp_path / "localization_detections" / "source-a.json", detections)

    state = table_cell_comparison_state(tmp_path)
    issue_ids = [
        issue["issue_id"]
        for panel in state["issue_panels"]
        for issue in panel["issues"]
        if issue["type"] == "fp"
    ]
    assert len(issue_ids) >= 2
    run_id = state["candidate"]["run_id"]

    write_calls: list[Path] = []
    original_write = table_model_comparison._write_json

    def counting_write(path, payload):
        if Path(path).name == "reviews.json":
            write_calls.append(Path(path))
        return original_write(path, payload)

    monkeypatch.setattr(table_model_comparison, "_write_json", counting_write)

    applied = review_comparison_issues_bulk(tmp_path, run_id, issue_ids, "model_error")

    assert applied == issue_ids
    assert len(write_calls) == 1
    updated = table_cell_comparison_state(tmp_path, candidate_run_id=run_id)
    assert updated["reviewed_issue_count"] == len(issue_ids)
    for panel in updated["issue_panels"]:
        for issue in panel["issues"]:
            if issue["issue_id"] in issue_ids:
                assert issue["review"]["decision"] == "model_error"


def test_review_comparison_issues_bulk_skips_unknown_ids_and_keeps_valid_ones(tmp_path: Path) -> None:
    dataset_id = _seed_dataset(tmp_path)
    _seed_baseline_and_current(tmp_path, dataset_id)
    state = table_cell_comparison_state(tmp_path)
    fp = next(
        issue
        for panel in state["issue_panels"]
        for issue in panel["issues"]
        if issue["type"] == "fp"
    )
    run_id = state["candidate"]["run_id"]

    applied = review_comparison_issues_bulk(tmp_path, run_id, [fp["issue_id"], "does-not-exist"], "model_error")

    assert applied == [fp["issue_id"]]
    updated = table_cell_comparison_state(tmp_path, candidate_run_id=run_id)
    assert updated["reviewed_issue_count"] == 1


def test_step7_workflow_and_ui_are_explicitly_separate_from_step4() -> None:
    root = Path(__file__).resolve().parents[1]
    webui = (root / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    template = (root / "application/src/isala_ocr/training/templates/table_model_comparison.html").read_text(encoding="utf-8")
    collector = (root / "application/src/isala_ocr/training/collector.py").read_text(encoding="utf-8")
    assert '"key": "table-compare","index":7,"group":"detection"' in webui
    assert '"key": "mapping","index":8,"group":"value"' in webui
    assert "bevroren Stap-4 Ground Truth" in template
    assert "alleen verschillen" in template
    assert "capture_current_detection_run" in collector
