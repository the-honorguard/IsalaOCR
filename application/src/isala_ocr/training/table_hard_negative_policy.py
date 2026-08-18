from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image

from .projects import resolve_project_workspace
from . import table_model_comparison as comparison
from . import table_cell_training as training


HARD_NEGATIVE_COPIES = 3
HARD_NEGATIVE_DEDUPE_IOU = 0.70
HARD_NEGATIVE_CONFLICT_PIXELS = 1.0

_ORIGINAL_LATEST_FEEDBACK = comparison.latest_completed_training_feedback
_ORIGINAL_BUILD_DATASET = training.build_table_cell_dataset
_INSTALLED = False


def _box(raw: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _intersection_area(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> float:
    width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    return width * height


def _iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    intersection = _intersection_area(left, right)
    if intersection <= 0:
        return 0.0
    union = _area(left) + _area(right) - intersection
    return intersection / max(1e-9, union)


def _dedupe_hard_negatives(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one recent representative for the same persistent FP geometry."""
    result: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda row: (str(row.get("reviewed_at") or ""), str(row.get("run_id") or ""))):
        candidate = _box(item.get("prediction_box"))
        if candidate is None:
            continue
        key = (str(item.get("source_id") or ""), str(item.get("panel_id") or ""))
        replaced = False
        for index, existing in enumerate(result):
            existing_key = (str(existing.get("source_id") or ""), str(existing.get("panel_id") or ""))
            existing_box = _box(existing.get("prediction_box"))
            if key == existing_key and existing_box is not None and _iou(candidate, existing_box) >= HARD_NEGATIVE_DEDUPE_IOU:
                result[index] = item
                replaced = True
                break
        if not replaced:
            result.append(item)
    return sorted(result, key=lambda row: (str(row.get("source_id") or ""), str(row.get("panel_id") or ""), str(row.get("issue_id") or "")))


def _persistent_fp_hard_negatives(root: Path) -> list[dict[str, Any]]:
    """Collect FP=model_error decisions from every fully reviewed comparison run.

    Newer review rounds normally supersede old whole-panel weighting. False-positive
    hard negatives are different: once the operator has explicitly said that a
    prediction is background, keep teaching that fact until current GT conflicts
    with it. The dataset builder performs that live-GT conflict check.
    """
    reviews = comparison.comparison_reviews(root)
    runs_root = root / comparison.COMPARISON_DIRNAME / comparison.RUNS_DIRNAME
    if not runs_root.is_dir():
        return []

    collected: list[dict[str, Any]] = []
    for path in sorted(runs_root.glob("*.json")):
        payload = comparison._read_json(path, {}) or {}
        if not isinstance(payload, dict) or not payload.get("run_id"):
            continue
        run = comparison._current_evaluation_view(payload)
        run_id = str(run.get("run_id") or "")
        run_reviews = reviews.get(run_id, {}) if isinstance(reviews, dict) else {}
        run_reviews = run_reviews if isinstance(run_reviews, dict) else {}
        issues: list[tuple[dict[str, Any], dict[str, Any]]] = []
        complete = True
        for panel in run.get("panels") or []:
            if not isinstance(panel, dict):
                continue
            for issue in panel.get("issues") or []:
                if not isinstance(issue, dict):
                    continue
                review = comparison._review_for_issue(issue, run_reviews) or {}
                decision = str(review.get("decision") or "")
                if not decision or decision == "deferred":
                    complete = False
                    break
                issues.append((issue, review))
            if not complete:
                break
        if not complete:
            continue

        for issue, review in issues:
            if str(issue.get("type") or "") != "fp" or str(review.get("decision") or "") != "model_error":
                continue
            prediction_box = _box(issue.get("prediction_box"))
            if prediction_box is None:
                continue
            collected.append({
                "run_id": run_id,
                "issue_id": str(issue.get("issue_id") or ""),
                "source_id": str(issue.get("source_id") or ""),
                "panel_id": str(issue.get("panel_id") or ""),
                "prediction_box": list(prediction_box),
                "confidence": float(issue.get("confidence") or 0.0),
                "reviewed_at": str(review.get("reviewed_at") or run.get("created_at") or ""),
            })
    return _dedupe_hard_negatives(collected)


def _feedback_with_persistent_hard_negatives(workspace: str | Path) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    base = dict(_ORIGINAL_LATEST_FEEDBACK(root) or {})
    hard_negatives = _persistent_fp_hard_negatives(root)

    # FP model errors now get targeted negative-only crops instead of merely
    # repeating the whole positive panel. Keep whole-panel weighting for geometry,
    # FN and merged errors because those still need positive target emphasis.
    non_fp_errors = [
        dict(item) for item in (base.get("model_errors") or [])
        if isinstance(item, dict) and str(item.get("type") or "") != "fp"
    ]
    panel_weights: dict[str, int] = {}
    source_weights: dict[str, int] = {}
    for item in non_fp_errors:
        source_id = str(item.get("source_id") or "")
        panel_id = str(item.get("panel_id") or "")
        multiplier = max(1, int(item.get("multiplier") or 1))
        if source_id and panel_id:
            panel_weights[f"{source_id}::{panel_id}"] = max(panel_weights.get(f"{source_id}::{panel_id}", 1), multiplier)
        if source_id:
            source_weights[source_id] = max(source_weights.get(source_id, 1), multiplier)

    fingerprint_material = {
        "base": str(base.get("fingerprint") or ""),
        "persistent_fp_hard_negatives": [
            {
                "source_id": item.get("source_id"),
                "panel_id": item.get("panel_id"),
                "prediction_box": [round(float(value), 3) for value in item.get("prediction_box") or []],
            }
            for item in hard_negatives
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    base.update({
        "fingerprint": fingerprint,
        "panel_weights": panel_weights,
        "source_weights": source_weights,
        "persistent_fp_hard_negatives": hard_negatives,
        "persistent_fp_hard_negative_count": len(hard_negatives),
        "policy": (
            "model_error only; geometry/fn x3, merged x4 whole-panel; "
            "FP -> persistent negative-only crops x3; train split only"
        ),
    })
    if hard_negatives and not base.get("available"):
        base["available"] = True
    return base


def _gt_boxes_for_image(train_payload: dict[str, Any], image_id: int) -> list[tuple[float, float, float, float]]:
    result: list[tuple[float, float, float, float]] = []
    for annotation in train_payload.get("annotations") or []:
        if not isinstance(annotation, dict) or int(annotation.get("image_id") or -1) != image_id:
            continue
        bbox = annotation.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        try:
            x, y, width, height = (float(value) for value in bbox)
        except (TypeError, ValueError):
            continue
        candidate = _box([x, y, x + width, y + height])
        if candidate is not None:
            result.append(candidate)
    return result


def _conflicts_with_gt(
    candidate: tuple[float, float, float, float], gt_boxes: list[tuple[float, float, float, float]]
) -> bool:
    return any(_intersection_area(candidate, gt) > HARD_NEGATIVE_CONFLICT_PIXELS for gt in gt_boxes)


def _negative_crop_box(
    prediction: tuple[float, float, float, float], *, width: int, height: int,
    gt_boxes: list[tuple[float, float, float, float]],
) -> tuple[int, int, int, int] | None:
    """Return a GT-safe context crop, or None when the FP now conflicts with GT."""
    x1, y1, x2, y2 = prediction
    exact = (
        max(0.0, min(float(width), x1)), max(0.0, min(float(height), y1)),
        max(0.0, min(float(width), x2)), max(0.0, min(float(height), y2)),
    )
    if exact[2] <= exact[0] or exact[3] <= exact[1] or _conflicts_with_gt(exact, gt_boxes):
        return None

    box_width = exact[2] - exact[0]
    box_height = exact[3] - exact[1]
    pad_x = max(8.0, box_width * 0.12)
    pad_y = max(6.0, box_height * 0.35)
    padded = (
        max(0.0, exact[0] - pad_x), max(0.0, exact[1] - pad_y),
        min(float(width), exact[2] + pad_x), min(float(height), exact[3] + pad_y),
    )
    selected = exact if _conflicts_with_gt(padded, gt_boxes) else padded
    crop = tuple(int(round(value)) for value in selected)
    if crop[2] - crop[0] < 4 or crop[3] - crop[1] < 4:
        return None
    return crop


def _write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _append_hard_negative_images(
    root: Path, manifest: dict[str, Any], hard_negatives: list[dict[str, Any]]
) -> dict[str, Any]:
    dataset_root = root / str(manifest.get("path") or "")
    train_path = dataset_root / "annotations" / "instance_train.json"
    if not hard_negatives or not train_path.is_file():
        return manifest
    try:
        train_payload = json.loads(train_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return manifest
    if not isinstance(train_payload, dict):
        return manifest
    images = train_payload.get("images")
    annotations = train_payload.get("annotations")
    if not isinstance(images, list) or not isinstance(annotations, list):
        return manifest

    image_by_filename = {
        str(item.get("file_name") or ""): item
        for item in images if isinstance(item, dict) and item.get("id") is not None
    }
    panel_by_key = {
        (str(panel.get("source_id") or ""), str(panel.get("panel_id") or "")): panel
        for panel in (manifest.get("panels") or [])
        if isinstance(panel, dict) and str(panel.get("split") or "") == "train"
    }
    next_image_id = max([int(item.get("id") or 0) for item in images if isinstance(item, dict)] or [0]) + 1
    accepted_fp_count = 0
    added_image_count = 0
    conflict_count = 0
    skipped_non_train_count = 0
    accepted_records: list[dict[str, Any]] = []

    for item in hard_negatives:
        source_id = str(item.get("source_id") or "")
        panel_id = str(item.get("panel_id") or "")
        panel = panel_by_key.get((source_id, panel_id))
        if panel is None:
            skipped_non_train_count += 1
            continue
        filename = str(panel.get("file_name") or "")
        base_image_record = image_by_filename.get(filename)
        image_path = dataset_root / "images" / filename
        prediction = _box(item.get("prediction_box"))
        if base_image_record is None or prediction is None or not image_path.is_file():
            continue
        base_image_id = int(base_image_record.get("id") or -1)
        gt_boxes = _gt_boxes_for_image(train_payload, base_image_id)

        with Image.open(image_path) as image:
            image = image.convert("RGB")
            crop_box = _negative_crop_box(prediction, width=image.width, height=image.height, gt_boxes=gt_boxes)
            if crop_box is None:
                conflict_count += 1
                continue
            crop = image.crop(crop_box)
            if crop.width < 4 or crop.height < 4:
                continue
            digest = hashlib.sha256(json.dumps({
                "source": source_id, "panel": panel_id, "box": list(crop_box)
            }, sort_keys=True).encode("utf-8")).hexdigest()[:12]
            for copy_index in range(1, HARD_NEGATIVE_COPIES + 1):
                hard_filename = f"{source_id}__{panel_id}__hardneg-{digest}-{copy_index}.png"
                crop.save(dataset_root / "images" / hard_filename)
                images.append({
                    "id": next_image_id,
                    "file_name": hard_filename,
                    "width": crop.width,
                    "height": crop.height,
                    "hard_negative": True,
                    "hard_negative_source": filename,
                    "hard_negative_issue_id": str(item.get("issue_id") or ""),
                })
                next_image_id += 1
                added_image_count += 1
            accepted_fp_count += 1
            accepted_records.append({
                "source_id": source_id,
                "panel_id": panel_id,
                "issue_id": str(item.get("issue_id") or ""),
                "run_id": str(item.get("run_id") or ""),
                "prediction_box": list(prediction),
                "crop_box": list(crop_box),
                "copies": HARD_NEGATIVE_COPIES,
            })

    if added_image_count:
        _write_json(train_path, train_payload)

    updated = dict(manifest)
    updated["hard_negative_fp_count"] = accepted_fp_count
    updated["hard_negative_image_count"] = added_image_count
    updated["hard_negative_conflict_count"] = conflict_count
    updated["hard_negative_non_train_skipped_count"] = skipped_non_train_count
    updated["hard_negatives"] = accepted_records
    updated["training_image_count"] = int(updated.get("training_image_count") or 0) + added_image_count
    splits = dict(updated.get("splits") or {})
    train_split = dict(splits.get("train") or {})
    train_split["panels"] = int(train_split.get("panels") or 0) + added_image_count
    splits["train"] = train_split
    updated["splits"] = splits
    feedback_meta = dict(updated.get("training_feedback") or {})
    feedback_meta.update({
        "persistent_fp_hard_negative_count": len(hard_negatives),
        "hard_negative_fp_count": accepted_fp_count,
        "hard_negative_image_count": added_image_count,
        "hard_negative_conflict_count": conflict_count,
        "policy": "FP=model_error -> persistent GT-safe negative-only crops x3; train split only",
    })
    updated["training_feedback"] = feedback_meta
    _write_json(dataset_root / "manifest.json", updated)
    return updated


def _build_dataset_with_hard_negatives(workspace: str | Path) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    manifest = _ORIGINAL_BUILD_DATASET(root)
    feedback = comparison.latest_completed_training_feedback(root)
    hard_negatives = [
        dict(item) for item in (feedback.get("persistent_fp_hard_negatives") or [])
        if isinstance(item, dict)
    ]
    return _append_hard_negative_images(root, manifest, hard_negatives)


def install_table_hard_negative_policy() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    comparison.latest_completed_training_feedback = _feedback_with_persistent_hard_negatives
    training.build_table_cell_dataset = _build_dataset_with_hard_negatives
    _INSTALLED = True
