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
        "panel_box": [0, 0, 220, 100],
        "width": 220,
        "height": 100,
        "ground_truth": [
            {"gt_id": f"gt-{index}", "box": box}
            for index, box in enumerate(gt_boxes, start=1)
        ],
    }


def test_broad_header_prediction_with_edge_bleed_is_one_geometry_issue():
    """A broad title prediction must not survive as a separate FP + FN pair.

    The boxes are strongly aligned on the same row, but neither direction reaches
    the 95% containment rule and IoU is deliberately below the normal 0.50 match
    threshold. This mirrors the broad Right-ventricle title/header case seen in
    Step 7.
    """
    panel = _panel([70, 10, 120, 32])
    predictions = [{
        "prediction_id": "broad-header",
        "box": [0, 12, 200, 30],
        "confidence": 0.944,
    }]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["tp"] == 1
    assert result["fp"] == 0
    assert result["fn"] == 0
    assert result["geometry_mismatch"] == 1
    assert len(result["issues"]) == 1
    issue = result["issues"][0]
    assert issue["type"] == "geometry"
    assert issue["match_reason"] == "row_alignment"
    assert issue["alignment_recovered"] is True
    assert len(issue["legacy_issue_ids"]) == 2


def test_row_alignment_does_not_guess_when_two_predictions_fit_one_gt():
    """Ambiguous split detections must not be collapsed into a fake 1:1 match."""
    panel = _panel([70, 10, 130, 32])
    predictions = [
        {"prediction_id": "left-part", "box": [0, 12, 125, 30], "confidence": 0.91},
        {"prediction_id": "right-part", "box": [75, 12, 200, 30], "confidence": 0.90},
    ]

    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)

    assert result["tp"] == 0
    assert result["fp"] == 2
    assert result["fn"] == 1
    assert not any(issue.get("alignment_recovered") for issue in result["issues"])


def test_schema_v4_forces_existing_v3_runs_through_new_matching_rules():
    assert EVALUATION_SCHEMA_VERSION == 4
