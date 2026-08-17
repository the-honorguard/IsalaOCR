from isala_ocr.training.table_model_comparison import (
    EVALUATION_SCHEMA_VERSION,
    _evaluate_panel,
)


def _panel(*gt_boxes):
    return {
        "source_id": "source-a",
        "panel_id": "rv",
        "panel_name": "Right ventricle Volume Result",
        "split": "train",
        "file_name": "source-a__rv.png",
        "panel_box": [0, 0, 260, 120],
        "width": 260,
        "height": 120,
        "ground_truth": [
            {"gt_id": f"gt-{index}", "box": box}
            for index, box in enumerate(gt_boxes, start=1)
        ],
    }


def test_near_duplicate_gt_boxes_do_not_make_one_prediction_merged():
    panel = _panel(
        [120, 40, 220, 75],
        [126, 41, 224, 76],
    )
    predictions = [{
        "prediction_id": "normal-values-only",
        "box": [118, 39, 226, 77],
        "confidence": 0.85,
    }]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["merged"] == 0
    assert not any(issue["type"] == "merged" for issue in result["issues"])


def test_overlapping_but_spatially_distinct_cells_can_still_be_merged():
    panel = _panel(
        [20, 40, 130, 75],
        [100, 40, 220, 75],
    )
    predictions = [{
        "prediction_id": "real-two-cell-merge",
        "box": [20, 39, 220, 77],
        "confidence": 0.92,
    }]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["merged"] == 1
    merged = [issue for issue in result["issues"] if issue["type"] == "merged"]
    assert len(merged) == 1
    assert len(merged[0]["gt_boxes"]) == 2


def test_schema_v7_re_evaluates_existing_v6_runs():
    assert EVALUATION_SCHEMA_VERSION == 7
