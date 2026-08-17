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


def test_right_cell_prediction_with_65_percent_neighbour_overlap_is_not_merged():
    """A right-cell prediction must not be merged because padded GT overlaps it.

    The prediction exactly matches the right GT cell. The left GT overlaps it by
    65%, which the previous >=60% rule incorrectly counted as a second covered GT.
    Under the stricter policy the left GT is not considered merged into the
    prediction, so Step 7 can review the right cell normally.
    """
    panel = _panel(
        [0, 20, 100, 60],
        [35, 20, 135, 60],
    )
    predictions = [{
        "prediction_id": "normal-values-only",
        "box": [35, 20, 135, 60],
        "confidence": 0.85,
    }]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["merged"] == 0
    assert not any(issue["type"] == "merged" for issue in result["issues"])
    assert result["tp"] == 1
    assert result["fn"] == 1


def test_prediction_spanning_two_gt_cells_is_merged():
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


def test_prediction_below_70_percent_second_gt_coverage_is_not_merged():
    panel = _panel(
        [0, 0, 100, 40],
        [31, 0, 131, 40],
    )
    predictions = [{
        "prediction_id": "right-cell",
        "box": [31, 0, 131, 40],
        "confidence": 0.90,
    }]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["merged"] == 0
    assert not any(issue["type"] == "merged" for issue in result["issues"])
