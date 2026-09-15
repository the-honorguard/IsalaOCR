from __future__ import annotations

import json
from pathlib import Path

from isala_ocr.training.table_cell_training import evaluate_table_cell_predictions


def _write_dataset(tmp_path: Path, dataset_id: str, images: list[dict], annotations: list[dict]) -> None:
    dataset_root = tmp_path / "table_cell_datasets" / dataset_id / "annotations"
    dataset_root.mkdir(parents=True, exist_ok=True)
    payload = {"images": images, "annotations": annotations, "categories": [{"id": 1, "name": "table_cell"}]}
    (dataset_root / "instance_val.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_predictions(tmp_path: Path, predictions: dict) -> Path:
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({"predictions": predictions}), encoding="utf-8")
    return path


def test_sweep_shows_a_saturation_gap_the_single_point_hides(tmp_path: Path) -> None:
    # A prediction offset just enough that it still matches at the loose
    # default point (confidence 0.25 / IoU 0.50) but not at a strict IoU
    # (0.9025 overlap: passes 0.85, fails 0.95). The single-point metric alone
    # cannot show this; the sweep must.
    _write_dataset(
        tmp_path, "ds1",
        images=[{"id": 1, "file_name": "img1.png", "width": 100, "height": 100}],
        annotations=[{"id": 1, "image_id": 1, "category_id": 1, "bbox": [0, 0, 100, 100], "area": 10000, "iscrowd": 0}],
    )
    predictions_path = _write_predictions(tmp_path, {"img1": [{"coordinate": [0, 0, 95, 95], "score": 0.9}]})

    report = evaluate_table_cell_predictions(tmp_path, predictions_path, dataset_id="ds1", split="val")

    # Backward-compatible single-point fields are unchanged.
    assert (report["tp"], report["fp"], report["fn"]) == (1, 0, 0)
    assert report["precision"] == 1.0
    assert report["recall"] == 1.0
    assert report["panel_count"] == 1
    assert report["images"] == [{"file_name": "img1.png", "tp": 1, "fp": 0, "fn": 0}]

    # The sweep exposes the strict-IoU failure that the loose default hides.
    assert report["saturated"] is True
    assert report["strictest_clean_iou_threshold"] == 0.85
    assert report["note"]
    strict_point = next(
        point for point in report["sweep"]
        if abs(point["confidence"] - 0.25) < 1e-9 and abs(point["iou_threshold"] - 0.95) < 1e-9
    )
    assert (strict_point["tp"], strict_point["fp"], strict_point["fn"]) == (0, 1, 1)
    loose_point = next(
        point for point in report["sweep"]
        if abs(point["confidence"] - 0.25) < 1e-9 and abs(point["iou_threshold"] - 0.85) < 1e-9
    )
    assert (loose_point["tp"], loose_point["fp"], loose_point["fn"]) == (1, 0, 0)
    assert all("images" not in point for point in report["sweep"])


def test_sweep_is_not_saturated_when_a_real_error_exists(tmp_path: Path) -> None:
    _write_dataset(
        tmp_path, "ds2",
        images=[{"id": 1, "file_name": "img2.png", "width": 400, "height": 400}],
        annotations=[
            {"id": 1, "image_id": 1, "category_id": 1, "bbox": [0, 0, 100, 100], "area": 10000, "iscrowd": 0},
            {"id": 2, "image_id": 1, "category_id": 1, "bbox": [200, 0, 100, 100], "area": 10000, "iscrowd": 0},
        ],
    )
    predictions_path = _write_predictions(tmp_path, {
        "img2": [
            {"coordinate": [0, 0, 95, 95], "score": 0.9},        # matches box 1 well
            {"coordinate": [350, 350, 400, 400], "score": 0.9},  # spurious, matches nothing
        ]
    })

    report = evaluate_table_cell_predictions(tmp_path, predictions_path, dataset_id="ds2", split="val")

    assert (report["tp"], report["fp"], report["fn"]) == (1, 1, 1)
    assert report["precision"] == 0.5
    assert report["recall"] == 0.5
    assert report["saturated"] is False
    assert report["strictest_clean_iou_threshold"] is None
    assert report["note"] == ""


def test_custom_threshold_lists_are_merged_with_the_primary_point(tmp_path: Path) -> None:
    _write_dataset(
        tmp_path, "ds3",
        images=[{"id": 1, "file_name": "img3.png", "width": 100, "height": 100}],
        annotations=[{"id": 1, "image_id": 1, "category_id": 1, "bbox": [0, 0, 100, 100], "area": 10000, "iscrowd": 0}],
    )
    predictions_path = _write_predictions(tmp_path, {"img3": [{"coordinate": [0, 0, 100, 100], "score": 0.6}]})

    report = evaluate_table_cell_predictions(
        tmp_path, predictions_path, dataset_id="ds3", split="val",
        confidence=0.25, iou_threshold=0.50,
        confidence_thresholds=[0.55], iou_thresholds=[0.99],
    )

    sweep_points = {(round(p["confidence"], 4), round(p["iou_threshold"], 4)) for p in report["sweep"]}
    assert (0.55, 0.99) in sweep_points
    # The primary point itself is always folded into the sweep grid too.
    assert (0.25, 0.5) in sweep_points
