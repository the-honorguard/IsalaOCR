from __future__ import annotations

import json
from pathlib import Path

import pytest

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.table_model_comparison import (
    _current_evaluation_view,
    _evaluate_panel,
    latest_completed_training_feedback,
    review_comparison_issue,
    table_cell_comparison_state,
)


def _panel(*gt_boxes: list[float]) -> dict:
    return {
        "source_id": "source-a",
        "panel_id": "rv",
        "panel_name": "Right ventricle Volume Result",
        "split": "train",
        "file_name": "source-a__rv.png",
        "panel_box": [0, 0, 200, 100],
        "width": 200,
        "height": 100,
        "ground_truth": [
            {"gt_id": f"gt-{index}", "box": box}
            for index, box in enumerate(gt_boxes, start=1)
        ],
    }


def test_low_iou_prediction_that_contains_one_gt_is_one_geometry_issue() -> None:
    panel = _panel([70, 20, 120, 35])
    predictions = [{
        "prediction_id": "oversized-title",
        "box": [0, 10, 190, 45],
        "confidence": 0.967,
    }]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["tp"] == 1
    assert result["fp"] == 0
    assert result["fn"] == 0
    assert result["geometry_mismatch"] == 1
    assert len(result["issues"]) == 1
    issue = result["issues"][0]
    assert issue["type"] == "geometry"
    assert issue["containment_recovered"] is True
    assert issue["prediction_containment_recovered"] is False
    assert issue["match_reason"] == "gt_coverage"
    assert issue["gt_coverage"] == pytest.approx(1.0)
    assert issue["prediction_excess"] > 0.30
    assert issue["functional_candidate"] is False
    assert len(issue["legacy_issue_ids"]) == 2


def test_low_iou_prediction_inside_one_broad_gt_is_one_geometry_issue() -> None:
    """Regression for broad merged GT rows with a tight text/title prediction."""
    panel = _panel([0, 10, 190, 40])
    predictions = [{
        "prediction_id": "tight-title",
        "box": [60, 14, 130, 36],
        "confidence": 0.951,
    }]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["tp"] == 1
    assert result["fp"] == 0
    assert result["fn"] == 0
    assert result["geometry_mismatch"] == 1
    assert len(result["issues"]) == 1
    issue = result["issues"][0]
    assert issue["type"] == "geometry"
    assert issue["containment_recovered"] is True
    assert issue["prediction_containment_recovered"] is True
    assert issue["match_reason"] == "prediction_coverage"
    assert issue["prediction_inside_gt"] == pytest.approx(1.0)
    assert issue["gt_coverage"] < 0.50
    assert issue["prediction_gt_area_fraction"] >= 0.10
    assert issue["prediction_gt_height_fraction"] >= 0.45
    assert len(issue["legacy_issue_ids"]) == 2


def test_reverse_containment_does_not_hide_split_predictions() -> None:
    """Two plausible predictions inside one GT remain explicit FP/FN errors."""
    panel = _panel([0, 10, 190, 40])
    predictions = [
        {"prediction_id": "left-half", "box": [20, 14, 80, 36], "confidence": 0.92},
        {"prediction_id": "right-half", "box": [110, 14, 170, 36], "confidence": 0.91},
    ]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["tp"] == 0
    assert result["fp"] == 2
    assert result["fn"] == 1
    assert not any(issue["type"] == "geometry" for issue in result["issues"])


def test_reverse_containment_does_not_promote_tiny_noise_inside_gt() -> None:
    panel = _panel([0, 10, 190, 40])
    predictions = [{
        "prediction_id": "tiny-noise",
        "box": [80, 20, 90, 25],
        "confidence": 0.88,
    }]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["tp"] == 0
    assert result["fp"] == 1
    assert result["fn"] == 1
    assert not any(issue["type"] == "geometry" for issue in result["issues"])


def test_containment_recovery_does_not_turn_multi_gt_prediction_into_single_geometry() -> None:
    panel = _panel([20, 20, 50, 35], [70, 20, 100, 35])
    predictions = [{
        "prediction_id": "merged-row",
        "box": [10, 10, 110, 45],
        "confidence": 0.91,
    }]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert any(issue["type"] == "merged" for issue in result["issues"])
    assert not any(issue.get("containment_recovered") for issue in result["issues"])


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _seed_legacy_run(root: Path) -> str:
    dataset_id = "table-cells-containment"
    base = root / "table_cell_datasets" / dataset_id
    (base / "images").mkdir(parents=True)
    _write_json(base / "manifest.json", {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "type": "table_cell_detection",
        "path": f"table_cell_datasets/{dataset_id}",
        "created_at": "2026-08-14T09:00:00+00:00",
        "panel_profile_updated_at": "2026-08-14T07:00:00+00:00",
        "annotation_count": 1,
        "panel_count": 1,
        "panels": [{
            "source_id": "source-a", "panel_id": "rv", "panel_name": "RV", "split": "train",
            "file_name": "source-a__rv.png", "box": [0, 0, 200, 100], "annotation_count": 1,
        }],
    })
    empty = {"images": [], "annotations": [], "categories": [{"id": 1, "name": "table_cell"}]}
    _write_json(base / "annotations" / "instance_val.json", empty)
    _write_json(base / "annotations" / "instance_test.json", empty)
    _write_json(base / "annotations" / "instance_train.json", {
        "images": [{"id": 1, "file_name": "source-a__rv.png", "width": 200, "height": 100}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [70, 20, 50, 15], "area": 750, "iscrowd": 0}],
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
            ("source-a", 200, 100, "source_renders/source-a.png", "ppstructure", 0, 1, 0,
             "2026-08-14T10:00:00+00:00", "2026-08-14T10:00:00+00:00", 0),
        )

    run_id = "detect-legacy-containment"
    legacy_panel = _panel([70, 20, 120, 35])
    legacy_prediction = {"prediction_id": "oversized-title", "box": [0, 10, 190, 45], "confidence": 0.967}
    # This is intentionally evaluator-v1 output: one FP + one FN for the same logical object.
    legacy_panel.update({
        "predictions": [legacy_prediction],
        "matches": [],
        "issues": [
            {
                "type": "fp", "label": "Extra detectie (FP)", "prediction_box": legacy_prediction["box"],
                "gt_boxes": [], "confidence": 0.967, "iou": 0.0,
                "issue_id": "legacy-fp",
            },
            {
                "type": "fn", "label": "GT-cel gemist (FN)", "prediction_box": None,
                "gt_boxes": [[70, 20, 120, 35]], "confidence": 0.0, "iou": 0.0,
                "issue_id": "legacy-fn",
            },
        ],
        "tp": 0, "fp": 1, "fn": 1, "direct_correct": 0, "geometry_mismatch": 0, "merged": 0,
    })
    _write_json(root / "table_cell_comparisons" / "runs" / f"{run_id}.json", {
        "schema_version": 1,
        "run_id": run_id,
        "label": "legacy run",
        "model_id": "model-legacy",
        "model_name": "legacy",
        "dataset_id": dataset_id,
        "source": "step3_localization_diagnostics",
        "created_at": "2026-08-14T10:00:00+00:00",
        "iou_threshold": 0.50,
        "geometry_iou": 0.75,
        "metrics": {"gt_total": 1, "prediction_total": 1, "tp": 0, "fp": 1, "fn": 1, "precision": 0.0, "recall": 0.0, "f1": 0.0, "direct_correct": 0, "geometry_mismatch": 0, "merged": 0, "review_needed": 2, "panel_count": 1},
        "panels": [legacy_panel],
    })
    return run_id


def test_existing_v1_run_is_reclassified_without_redetect_and_can_be_functional_ok(tmp_path: Path) -> None:
    run_id = _seed_legacy_run(tmp_path)
    state = table_cell_comparison_state(tmp_path, candidate_run_id=run_id)

    assert state["candidate"]["schema_version"] == 3
    assert state["candidate"]["evaluation_upgraded_from_schema"] == 1
    assert state["candidate"]["metrics"]["tp"] == 1
    assert state["candidate"]["metrics"]["fp"] == 0
    assert state["candidate"]["metrics"]["fn"] == 0
    assert state["candidate"]["metrics"]["geometry_mismatch"] == 1
    issues = [issue for panel in state["issue_panels"] for issue in panel["issues"]]
    assert len(issues) == 1
    assert issues[0]["type"] == "geometry"
    assert issues[0]["containment_recovered"] is True

    review_comparison_issue(tmp_path, run_id, issues[0]["issue_id"], "functional_ok")
    reviewed = table_cell_comparison_state(tmp_path, candidate_run_id=run_id)
    issue = reviewed["issue_panels"][0]["issues"][0]
    assert issue["review"]["decision"] == "functional_ok"
    assert reviewed["open_issue_count"] == 0


def test_existing_v2_reverse_containment_is_reclassified_without_redetect() -> None:
    panel = _panel([0, 10, 190, 40])
    prediction = {"prediction_id": "tight-title", "box": [60, 14, 130, 36], "confidence": 0.951}
    panel.update({
        "predictions": [prediction],
        "matches": [],
        "issues": [
            {"type": "fp", "prediction_box": prediction["box"], "gt_boxes": [], "issue_id": "old-fp"},
            {"type": "fn", "prediction_box": None, "gt_boxes": [[0, 10, 190, 40]], "issue_id": "old-fn"},
        ],
        "tp": 0, "fp": 1, "fn": 1, "direct_correct": 0, "geometry_mismatch": 0, "merged": 0,
    })
    run = {
        "schema_version": 2,
        "run_id": "detect-v2-reverse",
        "label": "v2 reverse",
        "model_id": "model-v2",
        "model_name": "model-v2",
        "dataset_id": "dataset-v2",
        "source": "step3_localization_diagnostics",
        "created_at": "2026-08-17T09:00:00+00:00",
        "iou_threshold": 0.50,
        "geometry_iou": 0.75,
        "metrics": {"review_needed": 2},
        "panels": [panel],
    }

    upgraded = _current_evaluation_view(run)

    assert upgraded["schema_version"] == 3
    assert upgraded["evaluation_upgraded_from_schema"] == 2
    assert upgraded["metrics"]["tp"] == 1
    assert upgraded["metrics"]["fp"] == 0
    assert upgraded["metrics"]["fn"] == 0
    assert upgraded["metrics"]["review_needed"] == 1
    issue = upgraded["panels"][0]["issues"][0]
    assert issue["type"] == "geometry"
    assert issue["match_reason"] == "prediction_coverage"


def test_functional_ok_reverse_containment_is_not_training_error(tmp_path: Path) -> None:
    panel = _panel([0, 10, 190, 40])
    prediction = {"prediction_id": "tight-title", "box": [60, 14, 130, 36], "confidence": 0.951}
    panel.update({
        "predictions": [prediction],
        "matches": [],
        "issues": [],
        "tp": 0, "fp": 1, "fn": 1, "direct_correct": 0, "geometry_mismatch": 0, "merged": 0,
    })
    run = {
        "schema_version": 2,
        "run_id": "detect-v2-functional-reverse",
        "label": "v2 reverse",
        "model_id": "model-v2",
        "model_name": "model-v2",
        "dataset_id": "dataset-v2",
        "source": "step3_localization_diagnostics",
        "created_at": "2026-08-17T09:00:00+00:00",
        "iou_threshold": 0.50,
        "geometry_iou": 0.75,
        "metrics": {"review_needed": 2},
        "panels": [panel],
    }
    upgraded = _current_evaluation_view(run)
    issue = upgraded["panels"][0]["issues"][0]
    _write_json(tmp_path / "table_cell_comparisons" / "runs" / f"{run['run_id']}.json", run)
    _write_json(tmp_path / "table_cell_comparisons" / "reviews.json", {
        run["run_id"]: {
            issue["issue_id"]: {
                "decision": "functional_ok",
                "reviewed_at": "2026-08-17T09:05:00+00:00",
            }
        }
    })

    feedback = latest_completed_training_feedback(tmp_path)

    assert feedback["available"] is True
    assert feedback["issue_count"] == 1
    assert feedback["decision_counts"] == {"functional_ok": 1}
    assert feedback["model_error_count"] == 0
    assert feedback["model_errors"] == []
    assert feedback["panel_weights"] == {}


def test_gt_check_on_recovered_geometry_has_panel_context(tmp_path: Path) -> None:
    run_id = _seed_legacy_run(tmp_path)
    state = table_cell_comparison_state(tmp_path, candidate_run_id=run_id)
    issue = state["issue_panels"][0]["issues"][0]

    review = review_comparison_issue(tmp_path, run_id, issue["issue_id"], "gt_check")

    assert review["decision"] == "gt_check"


def test_step7_ui_explains_containment_recovery() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "application/src/isala_ocr/training/templates/table_model_comparison.html").read_text(encoding="utf-8")
    comparison = (root / "application/src/isala_ocr/training/table_model_comparison.py").read_text(encoding="utf-8")
    assert "FP+FN gekoppeld" in template
    assert "≥95% van één GT-cel" in template
    assert '"match_reason": "gt_coverage"' in comparison
    assert '"prediction_coverage"' in comparison
    assert '"containment_recovered"' in comparison
    assert "EVALUATION_SCHEMA_VERSION = 3" in comparison
