from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2

from .augment import safe_augment
from .projects import resolve_project_workspace
from .db import TrainingDatabase, validate_exact_label
from .recognition_ground_truth import EXTRACTION_METHOD as RECOGNITION_GT_METHOD


def _group_split(source_ids: list[str], ratios: tuple[float, float, float], salt: str) -> dict[str, str]:
    unique = sorted(
        set(source_ids),
        key=lambda value: hashlib.sha256(f"{salt}:{value}".encode()).hexdigest(),
    )
    count = len(unique)
    if count == 0:
        return {}
    train_ratio, val_ratio, test_ratio = ratios
    if any(value < 0 for value in ratios) or abs(sum(ratios) - 1.0) > 1e-6:
        raise ValueError("Split ratios must be non-negative and sum to 1")

    if count >= 3:
        val_count = max(1, round(count * val_ratio)) if val_ratio else 0
        test_count = max(1, round(count * test_ratio)) if test_ratio else 0
        while val_count + test_count >= count:
            if test_count > 1:
                test_count -= 1
            elif val_count > 1:
                val_count -= 1
            else:
                break
    else:
        val_count = 0
        test_count = 0
    train_count = count - val_count - test_count

    assignment: dict[str, str] = {}
    for index, source_id in enumerate(unique):
        if index < train_count:
            split = "train"
        elif index < train_count + val_count:
            split = "val"
        else:
            split = "test"
        assignment[source_id] = split
    return assignment


def _dataset_id(rows: list[dict[str, Any]], settings: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(row["sample_id"].encode())
        digest.update(b"\0")
        digest.update(str(row["exact_label"]).encode("utf-8"))
        digest.update(b"\n")
    digest.update(json.dumps(settings, sort_keys=True).encode())
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"ds-{timestamp}-{digest.hexdigest()[:10]}"


def build_dataset(
    workspace: str | Path,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    augmentations_per_train_sample: int = 2,
    split_salt: str = "isala-ocr-v1",
    minimum_samples: int = 1,
) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    project_meta: dict[str, Any] = {}
    project_file = root / "project.json"
    if project_file.is_file():
        try:
            payload = json.loads(project_file.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                project_meta = {
                    "project_id": str(payload.get("project_id") or root.name),
                    "use_case_id": str(payload.get("use_case_id") or ""),
                }
        except (OSError, ValueError, TypeError):
            project_meta = {}
    db = TrainingDatabase(root / "samples.sqlite3")
    # Recognition training is a Model Factory concern. Application Mapping
    # samples (mapped_generic) must never leak into the model-training dataset.
    rows = [
        row for row in db.accepted()
        if str(row.get("extraction_method") or "") == RECOGNITION_GT_METHOD
    ]
    if len(rows) < minimum_samples:
        raise ValueError(
            f"Only {len(rows)} accepted Recognition-GT samples are available; minimum is {minimum_samples}. "
            "Create and review Recognition GT before building the dataset."
        )
    for row in rows:
        validate_exact_label(str(row["exact_label"]))

    settings = {
        "ratios": [train_ratio, val_ratio, test_ratio],
        "augmentations_per_train_sample": augmentations_per_train_sample,
        "split_salt": split_salt,
        "label_policy": "verbatim_no_normalization",
        "source": "canonical_table_cell_recognition_gt",
        "extraction_method": RECOGNITION_GT_METHOD,
    }
    dataset_id = _dataset_id(rows, settings)
    destination = root / "datasets" / dataset_id
    if destination.exists():
        raise FileExistsError(destination)
    for split in ("train", "val", "test"):
        (destination / "images" / split).mkdir(parents=True, exist_ok=True)

    assignments = _group_split(
        [str(row["source_id"]) for row in rows],
        (train_ratio, val_ratio, test_ratio),
        split_salt,
    )
    annotations: dict[str, list[str]] = {"train": [], "val": [], "test": []}
    sample_manifest: list[dict[str, Any]] = []
    character_counts: Counter[str] = Counter()

    for row in rows:
        split = assignments[str(row["source_id"])]
        label = str(row["exact_label"])
        character_counts.update(label)
        source = root / str(row["crop_path"])
        if not source.is_file():
            raise FileNotFoundError(source)
        filename = f"{row['sample_id']}.png"
        relative = Path("images") / split / filename
        target = destination / relative
        shutil.copy2(source, target)
        annotations[split].append(f"{relative.as_posix()}\t{label}")
        sample_manifest.append(
            {
                "sample_id": row["sample_id"],
                "source_id": row["source_id"],
                "field_key": row["field_key"],
                "split": split,
                "image": relative.as_posix(),
                "label": label,
                "content_class": row.get("content_class", "value"),
                "augmented": False,
            }
        )

        if split == "train":
            image = cv2.imread(str(source), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError(f"Could not read training crop: {source}")
            for index in range(augmentations_per_train_sample):
                augmented = safe_augment(image, f"{dataset_id}:{row['sample_id']}:{index}")
                aug_name = f"{row['sample_id']}__aug{index + 1:02d}.png"
                aug_relative = Path("images") / "train" / aug_name
                if not cv2.imwrite(str(destination / aug_relative), augmented):
                    raise RuntimeError(f"Could not write augmentation: {aug_relative}")
                annotations["train"].append(f"{aug_relative.as_posix()}\t{label}")
                sample_manifest.append(
                    {
                        "sample_id": f"{row['sample_id']}__aug{index + 1:02d}",
                        "parent_sample_id": row["sample_id"],
                        "source_id": row["source_id"],
                        "field_key": row["field_key"],
                        "split": "train",
                        "image": aug_relative.as_posix(),
                        "label": label,
                        "content_class": row.get("content_class", "value"),
                        "augmented": True,
                    }
                )

    for split, lines in annotations.items():
        (destination / f"{split}.txt").write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
        )
    observed_characters = sorted(char for char in character_counts if char != " ")
    (destination / "characters.txt").write_text(
        "\n".join(observed_characters) + "\n",
        encoding="utf-8",
    )

    original_counts = Counter(item["split"] for item in sample_manifest if not item["augmented"])
    total_counts = Counter(item["split"] for item in sample_manifest)
    source_splits: dict[str, set[str]] = {}
    for item in sample_manifest:
        source_splits.setdefault(str(item["source_id"]), set()).add(str(item["split"]))
    leakage = {key: sorted(value) for key, value in source_splits.items() if len(value) > 1}
    if leakage:
        raise RuntimeError(f"Source group leakage detected: {leakage}")

    manifest = {
        "dataset_id": dataset_id,
        **project_meta,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "settings": settings,
        "original_samples": dict(original_counts),
        "samples_including_augmentation": dict(total_counts),
        "source_groups": Counter(assignments.values()),
        "field_counts": dict(Counter(str(row["field_key"]) for row in rows)),
        "content_class_counts": dict(
            Counter(str(row.get("content_class", "value")) for row in rows)
        ),
        "character_counts": dict(sorted(character_counts.items())),
        "dictionary": {
            "paddlex_file": "dict.txt",
            "observed_characters_file": "characters.txt",
            "materialization": "synchronized_from_official_model_dictionary_by_training_runtime",
            "observed_non_space_character_count": len(observed_characters),
            "space_present_in_labels": " " in character_counts,
            "label_policy": "verbatim_no_normalization",
        },
        "samples": sample_manifest,
        "privacy": {
            "patient_metadata": False,
            "source_filename": False,
            "source_grouping": "SHA-256-derived source_id only",
        },
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (root / "datasets" / "latest.txt").write_text(dataset_id, encoding="utf-8")
    return manifest
