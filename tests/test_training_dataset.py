import json
from pathlib import Path

import cv2
import numpy as np

from isala_ocr.training.dataset import RECOGNITION_GT_METHOD, build_dataset
from isala_ocr.training.db import TrainingDatabase


def _add_sample(db: TrainingDatabase, root: Path, source: str, field: str, label: str) -> None:
    relative = Path("crops") / "original" / source / f"{field}.png"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.full((24, 120, 3), 255, dtype=np.uint8)
    cv2.putText(image, label, (2, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
    assert cv2.imwrite(str(path), image)
    sample_id = f"{source}_{field}"
    db.upsert_sample(
        {
            "sample_id": sample_id,
            "source_id": source,
            "profile": "profile",
            "field_key": field,
            "field_label": field,
            "crop_path": relative.as_posix(),
            "raw_ocr": "different",
            "raw_confidence": 0.5,
            "raw_variant": "test",
            "extraction_method": RECOGNITION_GT_METHOD,
            "image_width": 120,
            "image_height": 24,
            "roi_x1": 0,
            "roi_y1": 0,
            "roi_x2": 120,
            "roi_y2": 24,
        }
    )
    db.review_roi(sample_id, "correct")
    db.review(sample_id, "accepted", label)


def test_dataset_preserves_labels_and_groups_sources(tmp_path: Path):
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    labels = [" 12,7 ml ", "51.2 %", "1O0 mI", "0.00 ml"]
    for source_index in range(6):
        source = f"source-{source_index}"
        for field_index, label in enumerate(labels[:2]):
            _add_sample(db, tmp_path, source, f"field-{field_index}", label)

    manifest = build_dataset(
        tmp_path,
        train_ratio=0.5,
        val_ratio=0.25,
        test_ratio=0.25,
        augmentations_per_train_sample=1,
        minimum_samples=1,
    )
    dataset = tmp_path / "datasets" / manifest["dataset_id"]
    loaded = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))

    source_splits: dict[str, set[str]] = {}
    for sample in loaded["samples"]:
        source_splits.setdefault(sample["source_id"], set()).add(sample["split"])
        if sample.get("augmented"):
            parent = next(
                item for item in loaded["samples"] if item["sample_id"] == sample["parent_sample_id"]
            )
            assert sample["label"] == parent["label"]
            assert sample["split"] == "train"
    assert all(len(splits) == 1 for splits in source_splits.values())
    assert set.union(*(splits for splits in source_splits.values())) == {"train", "val", "test"}

    all_lines = "".join(
        (dataset / name).read_text(encoding="utf-8")
        for name in ("train.txt", "val.txt", "test.txt")
    )
    for label in labels[:2]:
        assert f"\t{label}\n" in all_lines
    assert "different" not in all_lines

    observed = (dataset / "characters.txt").read_text(encoding="utf-8").splitlines()
    assert observed == sorted(set("".join(labels[:2])) - {" "})
    assert not (dataset / "dict.txt").exists()
    assert loaded["dictionary"]["materialization"] == (
        "synchronized_from_official_model_dictionary_by_training_runtime"
    )
    assert loaded["dictionary"]["space_present_in_labels"] is True


def test_dataset_split_is_deterministic_for_same_sources(tmp_path: Path):
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    for index in range(5):
        _add_sample(db, tmp_path, f"source-{index}", "field", str(index))
    first = build_dataset(tmp_path, augmentations_per_train_sample=0, split_salt="fixed")
    second = build_dataset(tmp_path, augmentations_per_train_sample=0, split_salt="fixed")
    first_map = {item["sample_id"]: item["split"] for item in first["samples"]}
    second_map = {item["sample_id"]: item["split"] for item in second["samples"]}
    assert first_map == second_map
