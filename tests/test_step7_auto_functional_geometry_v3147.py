from isala_ocr.training.table_model_comparison import EVALUATION_SCHEMA_VERSION, _evaluate_panel
from isala_ocr.training.table_model_evaluation_policy import AUTO_FUNCTIONAL_GT_COVERAGE, AUTO_FUNCTIONAL_PREDICTION_EXCESS


def _panel(*gt_boxes):
    return {
        "source_id": "source-a",
        "panel_id": "rv",
        "panel_name": "Right ventricle Volume Result",
        "split": "train",
        "file_name": "source-a__rv.png",
        "panel_box": [0, 0, 420, 180],
        "width": 420,
        "height": 180,
        "ground_truth": [
            {"gt_id": f"gt-{index}", "box": box}
            for index, box in enumerate(gt_boxes, start=1)
        ],
    }


def _prediction(box, confidence=0.88):
    return [{"prediction_id": "pred-1", "box": box, "confidence": confidence}]


def test_common_wider_single_cell_crop_needs_no_manual_review():
    result = _evaluate_panel(
        _panel([100, 100, 300, 140]),
        _prediction([80, 101, 360, 138]),
        iou_threshold=0.50,
        geometry_iou=0.75,
    )
    assert result["tp"] == 1
    assert result["fp"] == 0
    assert result["fn"] == 0
    assert result["merged"] == 0
    assert result["functional_correct"] == 1
    assert result["geometry_mismatch"] == 0
    assert result["issues"] == []
    assert result["matches"][0]["functional_accepted"] is True


def test_below_coverage_floor_remains_for_review():
    result = _evaluate_panel(
        _panel([100, 100, 300, 140]),
        _prediction([80, 102, 360, 138]),
        iou_threshold=0.50,
        geometry_iou=0.75,
    )
    assert result["functional_correct"] == 0
    assert result["geometry_mismatch"] == 1
    assert [item["type"] for item in result["issues"]] == ["geometry"]


def test_too_much_extra_area_remains_for_review():
    result = _evaluate_panel(
        _panel([100, 100, 300, 140]),
        _prediction([70, 101, 370, 138]),
        iou_threshold=0.50,
        geometry_iou=0.75,
    )
    assert result["functional_correct"] == 0
    assert result["geometry_mismatch"] == 1
    assert [item["type"] for item in result["issues"]] == ["geometry"]


def test_crop_reaching_another_cell_center_remains_for_review():
    result = _evaluate_panel(
        _panel([100, 100, 300, 140], [300, 100, 340, 140]),
        _prediction([80, 101, 325, 138]),
        iou_threshold=0.50,
        geometry_iou=0.75,
    )
    # The first GT is well covered with little overall excess, but the crop
    # reaches the centre of the neighbouring logical cell. It must not be
    # silently treated as a harmless wider crop.
    assert result["functional_correct"] == 0
    assert any(item["type"] == "geometry" for item in result["issues"])


def test_merged_cells_are_not_auto_accepted():
    result = _evaluate_panel(
        _panel([20, 40, 130, 75], [100, 40, 220, 75]),
        _prediction([20, 39, 220, 77], confidence=0.94),
        iou_threshold=0.50,
        geometry_iou=0.75,
    )
    assert result["merged"] == 1
    assert result["functional_correct"] == 0
    assert any(item["type"] == "merged" for item in result["issues"])


def test_policy_thresholds_and_schema():
    assert AUTO_FUNCTIONAL_GT_COVERAGE == 0.92
    assert AUTO_FUNCTIONAL_PREDICTION_EXCESS == 0.30
    assert EVALUATION_SCHEMA_VERSION == 7
