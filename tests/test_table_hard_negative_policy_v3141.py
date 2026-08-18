from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from isala_ocr.training.table_hard_negative_policy import (
    HARD_NEGATIVE_COPIES,
    _append_hard_negative_images,
    _dedupe_hard_negatives,
    _negative_crop_box,
)


def test_persistent_fp_dedup_keeps_newest_similar_geometry() -> None:
    items = [
        {
            "run_id": "old",
            "issue_id": "old-fp",
            "source_id": "source-1",
            "panel_id": "left",
            "prediction_box": [10, 10, 80, 30],
            "reviewed_at": "2026-08-18T07:00:00+00:00",
        },
        {
            "run_id": "new",
            "issue_id": "new-fp",
            "source_id": "source-1",
            "panel_id": "left",
            "prediction_box": [11, 10, 81, 30],
            "reviewed_at": "2026-08-18T08:00:00+00:00",
        },
        {
            "run_id": "other",
            "issue_id": "other-fp",
            "source_id": "source-1",
            "panel_id": "right",
            "prediction_box": [11, 10, 81, 30],
            "reviewed_at": "2026-08-18T08:00:00+00:00",
        },
    ]

    result = _dedupe_hard_negatives(items)

    assert len(result) == 2
    assert {item["issue_id"] for item in result} == {"new-fp", "other-fp"}


def test_negative_crop_is_rejected_when_fp_conflicts_with_current_gt() -> None:
    gt = [(10.0, 20.0, 90.0, 40.0)]

    assert _negative_crop_box((20.0, 24.0, 80.0, 36.0), width=100, height=50, gt_boxes=gt) is None


def test_negative_crop_falls_back_to_exact_fp_when_padding_would_hit_gt() -> None:
    gt = [(0.0, 30.0, 100.0, 50.0)]

    crop = _negative_crop_box((20.0, 5.0, 80.0, 22.0), width=100, height=50, gt_boxes=gt)

    assert crop == (20, 5, 80, 22)


def test_dataset_gets_negative_only_training_images_without_gt_leakage(tmp_path: Path) -> None:
    dataset_root = tmp_path / "table_cell_datasets" / "dataset-1"
    images_root = dataset_root / "images"
    annotations_root = dataset_root / "annotations"
    images_root.mkdir(parents=True)
    annotations_root.mkdir(parents=True)

    Image.new("RGB", (120, 60), "white").save(images_root / "source-1__left.png")
    train_payload = {
        "images": [{"id": 1, "file_name": "source-1__left.png", "width": 120, "height": 60}],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 1, "bbox": [0, 35, 120, 20], "area": 2400, "iscrowd": 0}
        ],
        "categories": [{"id": 1, "name": "table_cell"}],
    }
    (annotations_root / "instance_train.json").write_text(json.dumps(train_payload), encoding="utf-8")

    manifest = {
        "path": "table_cell_datasets/dataset-1",
        "training_image_count": 1,
        "splits": {"train": {"sources": 1, "panels": 1, "annotations": 1}},
        "panels": [
            {
                "source_id": "source-1",
                "panel_id": "left",
                "split": "train",
                "file_name": "source-1__left.png",
            }
        ],
    }
    hard_negatives = [
        {
            "run_id": "run-1",
            "issue_id": "title-fp",
            "source_id": "source-1",
            "panel_id": "left",
            "prediction_box": [15, 5, 105, 22],
        },
        {
            "run_id": "run-1",
            "issue_id": "conflicting-fp",
            "source_id": "source-1",
            "panel_id": "left",
            "prediction_box": [15, 38, 105, 52],
        },
    ]

    updated = _append_hard_negative_images(tmp_path, manifest, hard_negatives)
    payload = json.loads((annotations_root / "instance_train.json").read_text(encoding="utf-8"))

    assert updated["hard_negative_fp_count"] == 1
    assert updated["hard_negative_conflict_count"] == 1
    assert updated["hard_negative_image_count"] == HARD_NEGATIVE_COPIES
    assert updated["training_image_count"] == 1 + HARD_NEGATIVE_COPIES
    assert len(payload["images"]) == 1 + HARD_NEGATIVE_COPIES
    assert len(payload["annotations"]) == 1
    negative_images = [item for item in payload["images"] if item.get("hard_negative")]
    assert len(negative_images) == HARD_NEGATIVE_COPIES
    assert all(item["hard_negative_issue_id"] == "title-fp" for item in negative_images)
