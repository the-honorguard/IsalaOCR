from isala_ocr.training.table_model_comparison import _evaluate_panel


def _panel(*gt_boxes):
    return {
        "source_id": "source-a",
        "panel_id": "rv",
        "panel_name": "Right ventricle Volume Result",
        "split": "train",
        "file_name": "source-a__rv.png",
        "panel_box": [0, 0, 240, 120],
        "width": 240,
        "height": 120,
        "ground_truth": [
            {"gt_id": f"gt-{index}", "box": box}
            for index, box in enumerate(gt_boxes, start=1)
        ],
    }


def test_prediction_that_only_owns_one_gt_center_is_not_merged():
    """Large edge overlap with a neighbour must not create a false merge.

    The prediction substantially overlaps both padded GT boxes, but contains only
    the centre of the right-hand GT cell. This mirrors the Step-7 case where the
    visible prediction belongs only to the Normal Values cell.
    """
    panel = _panel(
        [20, 20, 120, 60],
        [90, 20, 210, 60],
    )
    predictions = [{
        "prediction_id": "normal-values-only",
        "box": [100, 20, 210, 60],
        "confidence": 0.85,
    }]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["merged"] == 0
    assert not any(issue["type"] == "merged" for issue in result["issues"])
    assert result["tp"] == 1
    assert result["fn"] == 1


def test_prediction_spanning_two_gt_centers_is_merged():
    """A genuine two-cell prediction must remain a merged model error candidate."""
    panel = _panel(
        [20, 20, 100, 60],
        [100, 20, 200, 60],
    )
    predictions = [{
        "prediction_id": "two-cells",
        "box": [20, 20, 200, 60],
        "confidence": 0.92,
    }]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["merged"] == 1
    merged = [issue for issue in result["issues"] if issue["type"] == "merged"]
    assert len(merged) == 1
    assert len(merged[0]["gt_boxes"]) == 2


def test_70_percent_coverage_without_gt_center_is_not_enough_for_merge():
    panel = _panel(
        [0, 0, 100, 40],
        [80, 0, 180, 40],
    )
    predictions = [{
        "prediction_id": "right-cell",
        "box": [70, 0, 180, 40],
        "confidence": 0.90,
    }]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["merged"] == 0
    assert not any(issue["type"] == "merged" for issue in result["issues"])
