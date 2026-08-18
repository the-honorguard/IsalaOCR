from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _read_strict_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    if not isinstance(payload, dict):
        raise ValueError(f"top-level JSON object expected in {path.name}")
    return payload


def _finite_number(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite numeric value: {value!r}")
    return number


def validate_dataset(dataset: Path) -> tuple[list[str], list[str], dict[str, dict[str, int]]]:
    errors: list[str] = []
    warnings: list[str] = []
    counts: dict[str, dict[str, int]] = {}

    for split in ("train", "val", "test"):
        annotation_path = dataset / "annotations" / f"instance_{split}.json"
        if not annotation_path.is_file():
            errors.append(f"{split}: annotation file ontbreekt: {annotation_path.name}")
            continue
        try:
            payload = _read_strict_json(annotation_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{split}: ongeldige/non-finite COCO JSON: {exc}")
            continue

        images = payload.get("images") if isinstance(payload.get("images"), list) else []
        annotations = payload.get("annotations") if isinstance(payload.get("annotations"), list) else []
        counts[split] = {"images": len(images), "annotations": len(annotations)}

        image_by_id: dict[int, dict[str, Any]] = {}
        image_ids: set[int] = set()
        for image in images:
            if not isinstance(image, dict):
                errors.append(f"{split}: image-record is geen object")
                continue
            try:
                image_id = int(image["id"])
                width = int(image["width"])
                height = int(image["height"])
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{split}: ongeldig image-record: {exc}")
                continue
            if image_id in image_ids:
                errors.append(f"{split}: dubbel image id {image_id}")
                continue
            image_ids.add(image_id)
            if width <= 0 or height <= 0:
                errors.append(f"{split}: image {image_id} heeft ongeldige afmeting {width}x{height}")
                continue
            filename = str(image.get("file_name") or "")
            image_path = dataset / "images" / filename
            if not filename or not image_path.is_file():
                errors.append(f"{split}: image ontbreekt voor id {image_id}: {filename!r}")
                continue
            try:
                with Image.open(image_path) as actual:
                    actual_width, actual_height = actual.size
            except Exception as exc:
                errors.append(f"{split}: image {filename} kan niet worden gelezen: {exc}")
                continue
            if actual_width != width or actual_height != height:
                errors.append(
                    f"{split}: image metadata mismatch {filename}: COCO={width}x{height}, bestand={actual_width}x{actual_height}"
                )
                continue
            image_by_id[image_id] = image

        annotation_ids: set[int] = set()
        seen_boxes: set[tuple[int, float, float, float, float]] = set()
        for annotation in annotations:
            if not isinstance(annotation, dict):
                errors.append(f"{split}: annotation-record is geen object")
                continue
            try:
                annotation_id = int(annotation["id"])
                image_id = int(annotation["image_id"])
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{split}: ongeldig annotation id/image id: {exc}")
                continue
            if annotation_id in annotation_ids:
                errors.append(f"{split}: dubbel annotation id {annotation_id}")
                continue
            annotation_ids.add(annotation_id)
            image = image_by_id.get(image_id)
            if image is None:
                errors.append(f"{split}: annotation {annotation_id} verwijst naar onbekend image id {image_id}")
                continue
            bbox = annotation.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                errors.append(f"{split}: annotation {annotation_id} heeft geen geldige bbox")
                continue
            try:
                x, y, w, h = [_finite_number(value) for value in bbox]
                width = _finite_number(image["width"])
                height = _finite_number(image["height"])
                area = _finite_number(annotation.get("area", w * h))
            except (TypeError, ValueError) as exc:
                errors.append(f"{split}: annotation {annotation_id} bevat non-finite numeriek veld: {exc}")
                continue
            if w <= 0 or h <= 0:
                errors.append(f"{split}: annotation {annotation_id} heeft niet-positieve bbox {bbox}")
                continue
            if x < 0 or y < 0 or x + w > width + 1e-6 or y + h > height + 1e-6:
                errors.append(
                    f"{split}: annotation {annotation_id} bbox buiten image {image_id}: bbox={bbox}, image={width}x{height}"
                )
                continue
            expected_area = w * h
            if area <= 0 or not math.isclose(area, expected_area, rel_tol=1e-6, abs_tol=1e-6):
                errors.append(
                    f"{split}: annotation {annotation_id} heeft inconsistente area {area}; verwacht {expected_area} voor bbox {bbox}"
                )
                continue
            key = (image_id, round(x, 6), round(y, 6), round(w, 6), round(h, 6))
            if key in seen_boxes:
                warnings.append(f"{split}: dubbele bbox op image {image_id}: {bbox}")
            seen_boxes.add(key)

    if counts.get("train", {}).get("images", 0) < 1:
        errors.append("train: geen images")
    if counts.get("train", {}).get("annotations", 0) < 1:
        errors.append("train: geen positieve annotations")
    return errors, warnings, counts


def patch_validation_report(dataset: Path, *, errors: list[str], warnings: list[str], counts: dict[str, dict[str, int]]) -> None:
    path = dataset / "validation.json"
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError, json.JSONDecodeError):
        current = {}
    if not isinstance(current, dict):
        current = {}
    current["numeric_sanity"] = {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "splits": counts,
    }
    if errors:
        existing = list(current.get("errors") or []) if isinstance(current.get("errors"), list) else []
        current["errors"] = existing + [f"Numeric sanity: {item}" for item in errors]
        current["valid"] = False
    elif "valid" not in current:
        current["valid"] = True
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Strict numeric/geometry sanity check for IsalaOCR table-cell COCO datasets")
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args()
    dataset = Path(args.dataset).resolve()
    if not dataset.is_dir():
        raise FileNotFoundError(dataset)
    errors, warnings, counts = validate_dataset(dataset)
    patch_validation_report(dataset, errors=errors, warnings=warnings, counts=counts)
    payload = {"valid": not errors, "errors": errors, "warnings": warnings, "splits": counts}
    print(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False), flush=True)
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
