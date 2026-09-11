from isala_ocr.training.table_model_comparison import EVALUATION_SCHEMA_VERSION, _evaluate_panel
from isala_ocr.training.table_model_evaluation_policy import (
    SPATIAL_RECOVERY_MIN_AREA_RATIO,
    SPATIAL_RECOVERY_MIN_HORIZONTAL_OVERLAP,
    SPATIAL_RECOVERY_MIN_VERTICAL_OVERLAP,
    SPLIT_RECOVERY_MAX_GROUP_SIZE,
)


def _panel(*gt_boxes):
    return {
        "source_id": "source-a",
        "panel_id": "rv",
        "panel_name": "Right ventricle Volume Result",
        "split": "train",
        "file_name": "source-a__rv.png",
        "panel_box": [0, 0, 320, 140],
        "width": 320,
        "height": 140,
        "ground_truth": [
            {"gt_id": f"gt-{index}", "box": box}
            for index, box in enumerate(gt_boxes, start=1)
        ],
    }


def test_unique_same_row_fp_fn_pair_becomes_one_geometry_issue():
    panel = _panel([100, 40, 200, 80])
    predictions = [{
        "prediction_id": "shifted-cell",
        "box": [145, 40, 245, 80],
        "confidence": 0.93,
    }]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["tp"] == 1
    assert result["fp"] == 0
    assert result["fn"] == 0
    assert result["merged"] == 0
    assert result["spatial_recovered"] == 1
    assert result["functional_correct"] == 0
    assert result["geometry_mismatch"] == 1
    assert len(result["issues"]) == 1
    issue = result["issues"][0]
    assert issue["type"] == "geometry"
    assert issue["match_reason"] == "spatial_recovery"
    assert issue["spatial_recovered"] is True
    assert len(issue["legacy_issue_ids"]) == 2
    assert any(match.get("match_reason") == "spatial_recovery" for match in result["matches"])


def test_ambiguous_prediction_overlapping_two_gt_cells_stays_fp_and_fn():
    panel = _panel(
        [20, 40, 120, 80],
        [100, 40, 200, 80],
    )
    predictions = [{
        "prediction_id": "ambiguous-middle",
        "box": [60, 40, 160, 80],
        "confidence": 0.91,
    }]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["merged"] == 0
    assert result.get("spatial_recovered", 0) == 0
    assert result["tp"] == 0
    assert result["fp"] == 1
    assert result["fn"] == 2
    assert sorted(issue["type"] for issue in result["issues"]) == ["fn", "fn", "fp"]


def test_spatial_recovery_policy_is_conservative_and_versioned():
    assert SPATIAL_RECOVERY_MIN_VERTICAL_OVERLAP == 0.82
    assert SPATIAL_RECOVERY_MIN_HORIZONTAL_OVERLAP == 0.45
    assert SPATIAL_RECOVERY_MIN_AREA_RATIO == 0.10
    assert EVALUATION_SCHEMA_VERSION == 8


def test_two_split_predictions_covering_one_gt_row_become_one_geometry_issue():
    # The model detected a single row's label as two separate boxes (e.g.
    # "ED Wall +" and "Papillary mass" instead of one "ED Wall + Papillary
    # mass" cell). Individually neither prediction reaches the plain IoU
    # threshold, and the 1:1 spatial-recovery pass above declines because
    # both would claim the same FN -- this used to surface as 2 FP + 1 FN,
    # three separate manual "Model fout" clicks for one mistake.
    panel = _panel([0, 0, 200, 20])
    predictions = [
        {"prediction_id": "left-half", "box": [0, 0, 90, 20], "confidence": 0.927},
        {"prediction_id": "right-half", "box": [110, 0, 200, 20], "confidence": 0.96},
    ]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["tp"] == 1
    assert result["fp"] == 0
    assert result["fn"] == 0
    assert result["split_recovered"] == 1
    assert len(result["issues"]) == 1
    issue = result["issues"][0]
    assert issue["type"] == "geometry"
    assert issue["match_reason"] == "spatial_recovery_split"
    assert issue["spatial_recovered"] is True
    assert issue["prediction_box"] == [0.0, 0.0, 200.0, 20.0]
    assert len(issue["legacy_issue_ids"]) == 3  # both fp's + the fn


def test_split_recovery_declines_when_a_prediction_could_belong_to_two_fns():
    # "middle" row-aligns with both GT rows well enough to be a candidate
    # for either one, so which FN it's part of is ambiguous. Neither group
    # should be recovered; all three issues stay open for review.
    panel = _panel([0, 0, 90, 20], [110, 0, 200, 20])
    predictions = [{
        "prediction_id": "middle",
        "box": [40, 0, 160, 20],
        "confidence": 0.9,
    }]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result.get("split_recovered", 0) == 0
    assert result["tp"] == 0
    assert result["fp"] == 1
    assert result["fn"] == 2


def test_split_recovery_is_capped_at_a_small_group_size():
    # Four fragments reconstructing one row is past the point where "these
    # obviously belong together" is a safe geometric inference; leave it
    # for review rather than guessing across a large, unbounded group.
    panel = _panel([0, 0, 400, 20])
    predictions = [
        {"prediction_id": f"slice-{index}", "box": [index * 100, 0, index * 100 + 90, 20], "confidence": 0.9}
        for index in range(SPLIT_RECOVERY_MAX_GROUP_SIZE + 1)
    ]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result.get("split_recovered", 0) == 0
    assert result["fn"] == 1
    assert result["fp"] == SPLIT_RECOVERY_MAX_GROUP_SIZE + 1
