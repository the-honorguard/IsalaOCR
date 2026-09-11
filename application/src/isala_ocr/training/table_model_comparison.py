from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import TrainingDatabase, utc_now
from .projects import resolve_project_workspace
from .table_cell_ground_truth import (
    add_ground_truth_cell,
    list_ground_truth_cells,
    set_ground_truth_source_review_completed,
)
from .table_cell_training import active_table_cell_model, latest_table_cell_dataset
from .json_store import read_json as _read_json, write_json_atomic as _write_json

COMPARISON_DIRNAME = "table_cell_comparisons"
RUNS_DIRNAME = "runs"
BASELINE_RUN_ID = "step4-baseline"
DEFAULT_IOU_THRESHOLD = 0.50
DEFAULT_GEOMETRY_IOU = 0.75
FUNCTIONAL_GT_COVERAGE = 0.95
FUNCTIONAL_PREDICTION_EXCESS = 0.30
REVERSE_CONTAINMENT_PREDICTION_COVERAGE = 0.95
REVERSE_CONTAINMENT_MIN_GT_AREA_FRACTION = 0.10
REVERSE_CONTAINMENT_MIN_HEIGHT_FRACTION = 0.45
ROW_ALIGNMENT_MIN_VERTICAL_OVERLAP = 0.85
ROW_ALIGNMENT_MIN_HORIZONTAL_OVERLAP = 0.90
ROW_ALIGNMENT_MIN_AREA_RATIO = 0.12
MERGED_GT_MIN_COVERAGE = 0.70
MERGED_GT_MIN_CENTER_SEPARATION = 0.35
EVALUATION_SCHEMA_VERSION = 6


def _safe_iso(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _dataset_root(root: Path, dataset: dict[str, Any]) -> Path:
    relative = str(dataset.get("path") or "").strip()
    if not relative:
        raise FileNotFoundError("Table-cell dataset heeft geen pad")
    path = (root / relative).resolve()
    if path != root.resolve() and root.resolve() not in path.parents:
        raise ValueError("Table-cell datasetpad valt buiten de projectworkspace")
    if not path.is_dir():
        raise FileNotFoundError(f"Table-cell dataset ontbreekt: {path}")
    return path


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


def _iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    lx1, ly1, lx2, ly2 = left
    rx1, ry1, rx2, ry2 = right
    ix1, iy1 = max(lx1, rx1), max(ly1, ry1)
    ix2, iy2 = min(lx2, rx2), min(ly2, ry2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = max(1e-9, (lx2 - lx1) * (ly2 - ly1) + (rx2 - rx1) * (ry2 - ry1) - inter)
    return inter / union


def _coverage_fraction(inner: tuple[float, float, float, float], outer: tuple[float, float, float, float]) -> float:
    """Fraction of ``inner`` covered by ``outer``."""
    ix1, iy1 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix2, iy2 = min(inner[2], outer[2]), min(inner[3], outer[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area = max(1e-9, (inner[2] - inner[0]) * (inner[3] - inner[1]))
    return inter / area


def _box_area(box: tuple[float, float, float, float]) -> float:
    return max(1e-9, (box[2] - box[0]) * (box[3] - box[1]))


def _box_center_inside(
    inner: tuple[float, float, float, float], outer: tuple[float, float, float, float]
) -> bool:
    """Return whether the centre of ``inner`` lies inside ``outer``."""
    cx = (inner[0] + inner[2]) / 2.0
    cy = (inner[1] + inner[3]) / 2.0
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def _gt_is_merged_into_prediction(
    gt_box: tuple[float, float, float, float], prediction_box: tuple[float, float, float, float]
) -> bool:
    """Require substantial GT coverage and the GT centre inside the prediction."""
    return (
        _coverage_fraction(gt_box, prediction_box) >= MERGED_GT_MIN_COVERAGE
        and _box_center_inside(gt_box, prediction_box)
    )


def _gt_boxes_are_spatially_distinct(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> bool:
    """Return whether two GT boxes represent clearly different spatial cells.

    Canonical GT can contain duplicate or near-duplicate boxes around one logical
    cell. Counting those as two cells makes a perfectly normal single-cell
    prediction look like a merged prediction. Compare centre separation relative
    to the smaller cell dimensions: adjacent rows/columns remain distinct, while
    strongly overlapping boxes with nearly coincident centres collapse to one
    logical merge target.
    """
    left_cx = (left[0] + left[2]) / 2.0
    left_cy = (left[1] + left[3]) / 2.0
    right_cx = (right[0] + right[2]) / 2.0
    right_cy = (right[1] + right[3]) / 2.0
    min_width = max(1e-9, min(left[2] - left[0], right[2] - right[0]))
    min_height = max(1e-9, min(left[3] - left[1], right[3] - right[1]))
    x_separation = abs(left_cx - right_cx) / min_width
    y_separation = abs(left_cy - right_cy) / min_height
    return max(x_separation, y_separation) >= MERGED_GT_MIN_CENTER_SEPARATION


def _distinct_merge_gt_indexes(truth: list[dict[str, Any]], indexes: list[int]) -> list[int]:
    """Collapse duplicate/near-duplicate GT boxes for merged-cell classification."""
    representatives: list[int] = []
    for gt_index in indexes:
        gt_box = _box((truth[gt_index] or {}).get("box"))
        if gt_box is None:
            continue
        if all(
            (other_box := _box((truth[other_index] or {}).get("box"))) is None
            or _gt_boxes_are_spatially_distinct(gt_box, other_box)
            for other_index in representatives
        ):
            representatives.append(gt_index)
    return representatives


def _axis_overlap_fraction_of_smaller(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    *,
    axis: str,
) -> float:
    if axis == "x":
        left_start, left_end = left[0], left[2]
        right_start, right_end = right[0], right[2]
    elif axis == "y":
        left_start, left_end = left[1], left[3]
        right_start, right_end = right[1], right[3]
    else:
        raise ValueError(f"Onbekende as: {axis}")
    overlap = max(0.0, min(left_end, right_end) - max(left_start, right_start))
    smaller = max(1e-9, min(left_end - left_start, right_end - right_start))
    return overlap / smaller


def _geometry_quality(
    prediction_box: tuple[float, float, float, float], gt_box: tuple[float, float, float, float]
) -> dict[str, Any]:
    """Describe how an imperfect prediction relates to its canonical GT cell.

    IoU alone penalises both harmlessly oversized predictions and useful tight
    predictions inside a broad/merged GT cell. Step 7 therefore exposes both
    directions of containment. Automatic ``functional_candidate`` remains
    deliberately conservative: only a prediction that covers the complete GT
    without much excess is hinted as probably usable. A contained, tighter
    prediction is always left to human review because geometry alone cannot
    prove that the omitted GT area contains no useful content.
    """
    gt_coverage = _coverage_fraction(gt_box, prediction_box)
    prediction_inside_gt = _coverage_fraction(prediction_box, gt_box)
    prediction_excess = max(0.0, min(1.0, 1.0 - prediction_inside_gt))
    prediction_gt_area_fraction = min(1.0, _box_area(prediction_box) / _box_area(gt_box))
    gt_height = max(1e-9, gt_box[3] - gt_box[1])
    prediction_gt_height_fraction = min(1.0, (prediction_box[3] - prediction_box[1]) / gt_height)
    return {
        "gt_coverage": gt_coverage,
        "prediction_inside_gt": prediction_inside_gt,
        "prediction_excess": prediction_excess,
        "prediction_gt_area_fraction": prediction_gt_area_fraction,
        "prediction_gt_height_fraction": prediction_gt_height_fraction,
        "functional_candidate": (
            gt_coverage >= FUNCTIONAL_GT_COVERAGE
            and prediction_excess <= FUNCTIONAL_PREDICTION_EXCESS
        ),
    }


def _issue_identifier(panel_key: str, issue: dict[str, Any]) -> str:
    seed = json.dumps({
        "panel": panel_key,
        "type": issue.get("type"),
        "prediction": issue.get("prediction_box"),
        "gt": issue.get("gt_boxes"),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def _legacy_fp_fn_issue_ids(
    panel_key: str, prediction_box: Any, gt_box: Any
) -> list[str]:
    """IDs used before geometry recovery joined one logical FP + FN pair."""
    return [
        _issue_identifier(panel_key, {"type": "fp", "prediction_box": prediction_box, "gt_boxes": []}),
        _issue_identifier(panel_key, {"type": "fn", "prediction_box": None, "gt_boxes": [gt_box]}),
    ]


def _clip_to_panel(
    raw: tuple[float, float, float, float], panel_box: tuple[float, float, float, float]
) -> tuple[float, float, float, float] | None:
    px1, py1, px2, py2 = panel_box
    x1, y1 = max(raw[0], px1), max(raw[1], py1)
    x2, y2 = min(raw[2], px2), min(raw[3], py2)
    if x2 <= x1 or y2 <= y1:
        return None
    return x1 - px1, y1 - py1, x2 - px1, y2 - py1


def _ground_truth_panels(root: Path, dataset: dict[str, Any]) -> list[dict[str, Any]]:
    dataset_root = _dataset_root(root, dataset)
    annotations_by_file: dict[str, list[dict[str, Any]]] = {}
    image_size_by_file: dict[str, tuple[int, int]] = {}
    for split in ("train", "val", "test"):
        payload = _read_json(dataset_root / "annotations" / f"instance_{split}.json", {}) or {}
        images = payload.get("images") if isinstance(payload, dict) else []
        annotations = payload.get("annotations") if isinstance(payload, dict) else []
        images = images if isinstance(images, list) else []
        annotations = annotations if isinstance(annotations, list) else []
        image_by_id: dict[int, dict[str, Any]] = {}
        for item in images:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            image_by_id[int(item["id"])] = item
            filename = str(item.get("file_name") or "")
            image_size_by_file[filename] = (int(item.get("width") or 0), int(item.get("height") or 0))
        for item in annotations:
            if not isinstance(item, dict) or not isinstance(item.get("bbox"), list) or len(item["bbox"]) != 4:
                continue
            image = image_by_id.get(int(item.get("image_id") or -1))
            if not image:
                continue
            try:
                x, y, w, h = (float(value) for value in item["bbox"])
            except (TypeError, ValueError):
                continue
            if w <= 0 or h <= 0:
                continue
            filename = str(image.get("file_name") or "")
            annotations_by_file.setdefault(filename, []).append({
                "gt_id": f"gt-{split}-{item.get('id')}",
                "box": [x, y, x + w, y + h],
            })

    result: list[dict[str, Any]] = []
    for panel in dataset.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        filename = str(panel.get("file_name") or "")
        full_box = _box(panel.get("box"))
        if not filename or full_box is None:
            continue
        width, height = image_size_by_file.get(filename, (round(full_box[2] - full_box[0]), round(full_box[3] - full_box[1])))
        result.append({
            "source_id": str(panel.get("source_id") or ""),
            "panel_id": str(panel.get("panel_id") or ""),
            "panel_name": str(panel.get("panel_name") or panel.get("panel_id") or "Panel"),
            "split": str(panel.get("split") or ""),
            "file_name": filename,
            "panel_box": list(full_box),
            "width": int(width),
            "height": int(height),
            "ground_truth": annotations_by_file.get(filename, []),
        })
    return result


def _machine_predictions_for_panel(
    candidates: list[dict[str, Any]], panel_box: tuple[float, float, float, float]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict) or "table_cell" not in str(item.get("source_kind") or ""):
            continue
        raw = _box([item.get("x1"), item.get("y1"), item.get("x2"), item.get("y2")])
        if raw is None or _coverage_fraction(raw, panel_box) < 0.55:
            continue
        local = _clip_to_panel(raw, panel_box)
        if local is None:
            continue
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        result.append({
            "prediction_id": str(item.get("candidate_id") or ""),
            "box": list(local),
            "full_box": list(raw),
            "confidence": max(0.0, min(1.0, confidence)),
        })
    return result


def _evaluate_panel(
    panel: dict[str, Any], predictions: list[dict[str, Any]], *, iou_threshold: float, geometry_iou: float
) -> dict[str, Any]:
    truth = list(panel.get("ground_truth") or [])
    pairs: list[tuple[float, int, int]] = []
    for pred_index, pred in enumerate(predictions):
        pred_box = _box(pred.get("box"))
        if pred_box is None:
            continue
        for gt_index, gt in enumerate(truth):
            gt_box = _box(gt.get("box"))
            if gt_box is None:
                continue
            score = _iou(pred_box, gt_box)
            if score >= iou_threshold:
                pairs.append((score, pred_index, gt_index))
    pairs.sort(reverse=True)
    matched_pred: set[int] = set()
    matched_gt: set[int] = set()
    matches: list[dict[str, Any]] = []
    for score, pred_index, gt_index in pairs:
        if pred_index in matched_pred or gt_index in matched_gt:
            continue
        matched_pred.add(pred_index)
        matched_gt.add(gt_index)
        matches.append({
            "prediction_index": pred_index,
            "gt_index": gt_index,
            "iou": score,
            "match_reason": "iou",
        })

    # Merge classification must count logical cells, not raw GT annotations.
    # Duplicate/near-duplicate GT boxes around one cell are collapsed first.
    merged_prediction_indexes: set[int] = set()
    merged_gt_indexes: set[int] = set()
    merged_gt_by_prediction: dict[int, list[int]] = {}
    for pred_index, pred in enumerate(predictions):
        pred_box = _box(pred.get("box"))
        if pred_box is None:
            continue
        covered: list[int] = []
        for gt_index, gt in enumerate(truth):
            gt_box = _box(gt.get("box"))
            if gt_box is not None and _gt_is_merged_into_prediction(gt_box, pred_box):
                covered.append(gt_index)
        distinct_covered = _distinct_merge_gt_indexes(truth, covered)
        if len(distinct_covered) >= 2:
            merged_prediction_indexes.add(pred_index)
            merged_gt_indexes.update(distinct_covered)
            merged_gt_by_prediction[pred_index] = distinct_covered

    containment_pairs: list[tuple[float, float, int, int, str]] = []
    for pred_index, pred in enumerate(predictions):
        if pred_index in matched_pred or pred_index in merged_prediction_indexes:
            continue
        pred_box = _box(pred.get("box"))
        if pred_box is None:
            continue
        for gt_index, gt in enumerate(truth):
            if gt_index in matched_gt or gt_index in merged_gt_indexes:
                continue
            gt_box = _box(gt.get("box"))
            if gt_box is None:
                continue
            coverage = _coverage_fraction(gt_box, pred_box)
            if coverage >= FUNCTIONAL_GT_COVERAGE:
                containment_pairs.append((coverage, _iou(pred_box, gt_box), pred_index, gt_index, "gt_coverage"))

    reverse_candidates: list[tuple[float, float, int, int]] = []
    for pred_index, pred in enumerate(predictions):
        if pred_index in matched_pred or pred_index in merged_prediction_indexes:
            continue
        pred_box = _box(pred.get("box"))
        if pred_box is None:
            continue
        for gt_index, gt in enumerate(truth):
            if gt_index in matched_gt or gt_index in merged_gt_indexes:
                continue
            gt_box = _box(gt.get("box"))
            if gt_box is None:
                continue
            prediction_coverage = _coverage_fraction(pred_box, gt_box)
            if prediction_coverage < REVERSE_CONTAINMENT_PREDICTION_COVERAGE:
                continue
            area_fraction = min(1.0, _box_area(pred_box) / _box_area(gt_box))
            gt_height = max(1e-9, gt_box[3] - gt_box[1])
            height_fraction = min(1.0, (pred_box[3] - pred_box[1]) / gt_height)
            if area_fraction < REVERSE_CONTAINMENT_MIN_GT_AREA_FRACTION:
                continue
            if height_fraction < REVERSE_CONTAINMENT_MIN_HEIGHT_FRACTION:
                continue
            reverse_candidates.append((prediction_coverage, _iou(pred_box, gt_box), pred_index, gt_index))

    reverse_pred_counts: dict[int, int] = {}
    reverse_gt_counts: dict[int, int] = {}
    for _, _, pred_index, gt_index in reverse_candidates:
        reverse_pred_counts[pred_index] = reverse_pred_counts.get(pred_index, 0) + 1
        reverse_gt_counts[gt_index] = reverse_gt_counts.get(gt_index, 0) + 1
    for coverage, score, pred_index, gt_index in reverse_candidates:
        if reverse_pred_counts.get(pred_index) == 1 and reverse_gt_counts.get(gt_index) == 1:
            containment_pairs.append((coverage, score, pred_index, gt_index, "prediction_coverage"))

    aligned_candidates: list[tuple[float, float, int, int]] = []
    for pred_index, pred in enumerate(predictions):
        if pred_index in matched_pred or pred_index in merged_prediction_indexes:
            continue
        pred_box = _box(pred.get("box"))
        if pred_box is None:
            continue
        for gt_index, gt in enumerate(truth):
            if gt_index in matched_gt or gt_index in merged_gt_indexes:
                continue
            gt_box = _box(gt.get("box"))
            if gt_box is None:
                continue
            vertical = _axis_overlap_fraction_of_smaller(pred_box, gt_box, axis="y")
            horizontal = _axis_overlap_fraction_of_smaller(pred_box, gt_box, axis="x")
            area_ratio = min(_box_area(pred_box), _box_area(gt_box)) / max(_box_area(pred_box), _box_area(gt_box))
            if vertical < ROW_ALIGNMENT_MIN_VERTICAL_OVERLAP:
                continue
            if horizontal < ROW_ALIGNMENT_MIN_HORIZONTAL_OVERLAP:
                continue
            if area_ratio < ROW_ALIGNMENT_MIN_AREA_RATIO:
                continue
            aligned_candidates.append((vertical * horizontal, _iou(pred_box, gt_box), pred_index, gt_index))

    aligned_pred_counts: dict[int, int] = {}
    aligned_gt_counts: dict[int, int] = {}
    for _, _, pred_index, gt_index in aligned_candidates:
        aligned_pred_counts[pred_index] = aligned_pred_counts.get(pred_index, 0) + 1
        aligned_gt_counts[gt_index] = aligned_gt_counts.get(gt_index, 0) + 1
    for alignment, score, pred_index, gt_index in aligned_candidates:
        if aligned_pred_counts.get(pred_index) == 1 and aligned_gt_counts.get(gt_index) == 1:
            containment_pairs.append((alignment, score, pred_index, gt_index, "row_alignment"))

    containment_pairs.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for coverage, score, pred_index, gt_index, match_reason in containment_pairs:
        if pred_index in matched_pred or gt_index in matched_gt:
            continue
        matched_pred.add(pred_index)
        matched_gt.add(gt_index)
        match = {
            "prediction_index": pred_index,
            "gt_index": gt_index,
            "iou": score,
            "match_reason": match_reason,
        }
        if match_reason == "gt_coverage":
            match["match_gt_coverage"] = coverage
        elif match_reason == "prediction_coverage":
            match["match_prediction_coverage"] = coverage
        else:
            match["match_row_alignment"] = coverage
        matches.append(match)

    issues: list[dict[str, Any]] = []
    panel_key = f"{panel.get('source_id')}::{panel.get('panel_id')}"
    for item in matches:
        if float(item["iou"]) >= geometry_iou:
            continue
        pred = predictions[item["prediction_index"]]
        gt = truth[item["gt_index"]]
        pred_box = _box(pred.get("box"))
        gt_box = _box(gt.get("box"))
        quality = _geometry_quality(pred_box, gt_box) if pred_box is not None and gt_box is not None else {}
        issue = {
            "type": "geometry",
            "label": "Geometrie afwijkend",
            "prediction_box": pred.get("box"),
            "gt_boxes": [gt.get("box")],
            "confidence": pred.get("confidence", 0.0),
            "iou": float(item["iou"]),
            "match_reason": item.get("match_reason") or "iou",
            **quality,
        }
        if issue["match_reason"] in {"gt_coverage", "prediction_coverage", "row_alignment"}:
            issue["legacy_issue_ids"] = _legacy_fp_fn_issue_ids(
                panel_key, pred.get("box"), gt.get("box")
            )
        if issue["match_reason"] in {"gt_coverage", "prediction_coverage"}:
            issue["containment_recovered"] = True
            issue["prediction_containment_recovered"] = issue["match_reason"] == "prediction_coverage"
        elif issue["match_reason"] == "row_alignment":
            issue["alignment_recovered"] = True
        issues.append(issue)

    for pred_index in sorted(merged_prediction_indexes):
        pred = predictions[pred_index]
        covered = [
            truth[gt_index].get("box")
            for gt_index in merged_gt_by_prediction.get(pred_index, [])
            if 0 <= gt_index < len(truth)
        ]
        issues.append({
            "type": "merged",
            "label": "Meerdere GT-cellen samengevoegd",
            "prediction_box": pred.get("box"),
            "gt_boxes": covered,
            "confidence": pred.get("confidence", 0.0),
            "iou": 0.0,
        })

    for pred_index, pred in enumerate(predictions):
        if pred_index in matched_pred or pred_index in merged_prediction_indexes:
            continue
        issues.append({
            "type": "fp",
            "label": "Extra detectie (FP)",
            "prediction_box": pred.get("box"),
            "gt_boxes": [],
            "confidence": pred.get("confidence", 0.0),
            "iou": 0.0,
        })
    for gt_index, gt in enumerate(truth):
        if gt_index in matched_gt or gt_index in merged_gt_indexes:
            continue
        issues.append({
            "type": "fn",
            "label": "GT-cel gemist (FN)",
            "prediction_box": None,
            "gt_boxes": [gt.get("box")],
            "confidence": 0.0,
            "iou": 0.0,
        })

    for issue in issues:
        issue["issue_id"] = _issue_identifier(panel_key, issue)
        issue["source_id"] = panel.get("source_id")
        issue["panel_id"] = panel.get("panel_id")
        issue["panel_name"] = panel.get("panel_name")
        issue["file_name"] = panel.get("file_name")
        issue["width"] = panel.get("width")
        issue["height"] = panel.get("height")
        issue["split"] = panel.get("split")

    direct_correct = sum(1 for item in matches if float(item["iou"]) >= geometry_iou)
    geometry_mismatch = len(matches) - direct_correct
    return {
        **panel,
        "predictions": predictions,
        "matches": matches,
        "issues": issues,
        "tp": len(matches),
        "fp": len(predictions) - len(matched_pred),
        "fn": len(truth) - len(matched_gt),
        "direct_correct": direct_correct,
        "geometry_mismatch": geometry_mismatch,
        "merged": len(merged_prediction_indexes),
    }


def _summarize(panels: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(int(item.get("tp") or 0) for item in panels)
    fp = sum(int(item.get("fp") or 0) for item in panels)
    fn = sum(int(item.get("fn") or 0) for item in panels)
    gt_total = sum(len(item.get("ground_truth") or []) for item in panels)
    predictions = sum(len(item.get("predictions") or []) for item in panels)
    direct = sum(int(item.get("direct_correct") or 0) for item in panels)
    geometry = sum(int(item.get("geometry_mismatch") or 0) for item in panels)
    merged = sum(int(item.get("merged") or 0) for item in panels)
    issues = sum(len(item.get("issues") or []) for item in panels)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    return {
        "gt_total": gt_total,
        "prediction_total": predictions,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "direct_correct": direct,
        "geometry_mismatch": geometry,
        "merged": merged,
        "review_needed": issues,
        "panel_count": len(panels),
    }


def _evaluate_run(
    *, run_id: str, label: str, model_id: str, model_name: str, dataset_id: str,
    created_at: str, panels: list[dict[str, Any]], predictions_by_panel: dict[str, list[dict[str, Any]]],
    source: str, iou_threshold: float = DEFAULT_IOU_THRESHOLD, geometry_iou: float = DEFAULT_GEOMETRY_IOU,
) -> dict[str, Any]:
    evaluated: list[dict[str, Any]] = []
    for panel in panels:
        key = f"{panel.get('source_id')}::{panel.get('panel_id')}"
        evaluated.append(_evaluate_panel(panel, list(predictions_by_panel.get(key) or []), iou_threshold=iou_threshold, geometry_iou=geometry_iou))
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "run_id": run_id,
        "label": label,
        "model_id": model_id,
        "model_name": model_name,
        "dataset_id": dataset_id,
        "source": source,
        "created_at": created_at,
        "iou_threshold": iou_threshold,
        "geometry_iou": geometry_iou,
        "metrics": _summarize(evaluated),
        "panels": evaluated,
    }


def build_step4_baseline(workspace: str | Path, dataset: dict[str, Any] | None = None) -> dict[str, Any] | None:
    root = resolve_project_workspace(workspace)
    dataset = dataset or latest_table_cell_dataset(root)
    if not dataset:
        return None
    panels = _ground_truth_panels(root, dataset)
    if not panels:
        return None
    created_at = _safe_iso(dataset.get("created_at"))
    panel_profile_at = _safe_iso(dataset.get("panel_profile_updated_at"))
    db = TrainingDatabase(root / "samples.sqlite3")
    with db.connect() as conn:
        sql = """
            SELECT source_id,review_status,original_x1,original_y1,original_x2,original_y2,reviewed_at
            FROM detection_reviews
            WHERE review_status<>'added'
        """
        params: list[Any] = []
        if created_at:
            sql += " AND reviewed_at<=?"
            params.append(created_at)
        if panel_profile_at:
            sql += " AND reviewed_at>=?"
            params.append(panel_profile_at)
        sql += " ORDER BY reviewed_at,source_id"
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]

    by_source: dict[str, list[dict[str, Any]]] = {}
    for index, item in enumerate(rows):
        by_source.setdefault(str(item.get("source_id") or ""), []).append({
            "candidate_id": f"baseline-{index}",
            "source_kind": "table_cell_baseline",
            "confidence": 1.0,
            "x1": item.get("original_x1"), "y1": item.get("original_y1"),
            "x2": item.get("original_x2"), "y2": item.get("original_y2"),
        })

    predictions_by_panel: dict[str, list[dict[str, Any]]] = {}
    for panel in panels:
        full_box = _box(panel.get("panel_box"))
        if full_box is None:
            continue
        key = f"{panel.get('source_id')}::{panel.get('panel_id')}"
        predictions_by_panel[key] = _machine_predictions_for_panel(by_source.get(str(panel.get("source_id") or ""), []), full_box)

    return _evaluate_run(
        run_id=BASELINE_RUN_ID,
        label="Model 0 · eerste Stap-8-run",
        model_id="generic-ppstructure",
        model_name="Generieke PP-Structure wireless table-cell detector",
        dataset_id=str(dataset.get("dataset_id") or ""),
        created_at=created_at,
        panels=panels,
        predictions_by_panel=predictions_by_panel,
        source="initial_step4_reviews",
    )


def _current_detection_identity(
    root: Path, dataset_id: str, model_id: str, detection_batch_id: str = ""
) -> tuple[str, str]:
    db = TrainingDatabase(root / "samples.sqlite3")
    sources = db.list_detection_sources()
    material = []
    newest = ""
    for item in sorted(sources, key=lambda row: str(row.get("source_id") or "")):
        detected = _safe_iso(item.get("detected_at"))
        newest = max(newest, detected)
        material.append((str(item.get("source_id") or ""), detected, int(item.get("block_count") or 0)))
    digest = hashlib.sha256(json.dumps({
        "dataset": dataset_id,
        "model": model_id,
        "batch": detection_batch_id,
        "sources": material,
    }, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    stamp = ""
    if newest:
        try:
            stamp = datetime.fromisoformat(newest).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        except ValueError:
            stamp = "current"
    return f"detect-{stamp or 'current'}-{digest}", newest or utc_now()


def current_detection_context(workspace: str | Path) -> dict[str, Any]:
    """Return the immutable model identity of the latest complete Step-3 output.

    Crucially this is derived from the diagnostic files written *during* Step 3,
    never from whichever model happens to be active when Step 7 is opened.
    Legacy diagnostics without run metadata use activation timestamps only as a
    migration fallback.
    """
    root = resolve_project_workspace(workspace)
    dataset = latest_table_cell_dataset(root)
    if not dataset:
        return {"available": False, "reason": "no_dataset"}
    panels = _ground_truth_panels(root, dataset)
    source_ids = sorted({str(panel.get("source_id") or "") for panel in panels if str(panel.get("source_id") or "")})
    if not source_ids:
        return {"available": False, "reason": "no_sources"}

    db = TrainingDatabase(root / "samples.sqlite3")
    detected_by_source = {
        str(item.get("source_id") or ""): _safe_iso(item.get("detected_at"))
        for item in db.list_detection_sources()
    }
    diagnostics: list[dict[str, Any]] = []
    for source_id in source_ids:
        payload = _read_json(root / "localization_detections" / f"{source_id}.json", {}) or {}
        if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
            return {"available": False, "reason": "incomplete_detection", "source_id": source_id}
        diagnostics.append(payload)

    has_run_metadata = all("active_table_cell_model" in item for item in diagnostics)
    explicit_models = []
    for item in diagnostics:
        meta = item.get("active_table_cell_model")
        if isinstance(meta, dict) and str(meta.get("model_id") or ""):
            explicit_models.append(meta)
        elif has_run_metadata:
            explicit_models.append({"model_id": "generic-ppstructure", "model_name": "Generieke PP-Structure wireless table-cell detector"})

    model_ids = {str(item.get("model_id") or "") for item in explicit_models if str(item.get("model_id") or "")}
    if len(model_ids) > 1:
        return {"available": False, "reason": "mixed_model_detection", "model_ids": sorted(model_ids)}

    active = active_table_cell_model(root) or {}
    active_id = str(active.get("model_id") or "")
    if model_ids:
        model_id = next(iter(model_ids))
        selected_meta = next((item for item in explicit_models if str(item.get("model_id") or "") == model_id), {})
        model_name = str(selected_meta.get("model_name") or (active.get("model_name") if model_id == active_id else "") or model_id)
        model_training_run_id = str(selected_meta.get("run_id") or "")
        model_dataset_id = str(selected_meta.get("dataset_id") or "")
    else:
        source_times = [detected_by_source.get(source_id, "") for source_id in source_ids]
        activated_at = _safe_iso(active.get("activated_at"))
        can_be_active = bool(active_id and activated_at and source_times and all(value and value >= activated_at for value in source_times))
        if can_be_active:
            model_id = active_id
            model_name = str(active.get("model_name") or model_id)
            model_training_run_id = str(active.get("run_id") or "")
            model_dataset_id = str(active.get("dataset_id") or "")
        else:
            model_id = "generic-ppstructure"
            model_name = "Generieke PP-Structure wireless table-cell detector"
            model_training_run_id = ""
            model_dataset_id = ""

    batch_ids = {str(item.get("detection_batch_id") or "") for item in diagnostics if str(item.get("detection_batch_id") or "")}
    if len(batch_ids) > 1:
        return {"available": False, "reason": "mixed_detection_batch", "batch_ids": sorted(batch_ids)}
    detection_batch_id = next(iter(batch_ids), "")
    diagnostic_times = [_safe_iso(item.get("detected_at")) for item in diagnostics]
    diagnostic_times = [item for item in diagnostic_times if item]
    db_times = [detected_by_source.get(source_id, "") for source_id in source_ids]
    db_times = [item for item in db_times if item]
    created_at = max(diagnostic_times or db_times or [utc_now()])
    stale = bool(active_id and model_id != active_id)
    return {
        "available": True,
        "dataset_id": str(dataset.get("dataset_id") or ""),
        "model_id": model_id,
        "model_name": model_name,
        "model_training_run_id": model_training_run_id,
        "model_dataset_id": model_dataset_id,
        "detection_batch_id": detection_batch_id,
        "created_at": created_at,
        "active_model_id": active_id,
        "active_model_name": str(active.get("model_name") or ""),
        "stale_against_active_model": stale,
        "source_count": len(source_ids),
    }


def capture_current_detection_run(workspace: str | Path) -> dict[str, Any] | None:
    root = resolve_project_workspace(workspace)
    dataset = latest_table_cell_dataset(root)
    if not dataset:
        return None
    panels = _ground_truth_panels(root, dataset)
    if not panels:
        return None
    context = current_detection_context(root)
    if not context.get("available"):
        return None
    model_id = str(context.get("model_id") or "generic-ppstructure")
    model_name = str(context.get("model_name") or model_id)

    runs_root = root / COMPARISON_DIRNAME / RUNS_DIRNAME
    batch_id = str(context.get("detection_batch_id") or "")
    context_created_at = str(context.get("created_at") or "")
    if runs_root.is_dir():
        for archived_path in sorted(runs_root.glob("*.json"), reverse=True):
            archived = _read_json(archived_path, {}) or {}
            if not isinstance(archived, dict) or str(archived.get("model_id") or "") != model_id:
                continue
            archived_batch = str(archived.get("detection_batch_id") or "")
            same_batch = bool(batch_id and archived_batch == batch_id)
            legacy_same_detection = bool(
                not batch_id and not archived_batch and context_created_at
                and _safe_iso(archived.get("created_at")) == _safe_iso(context_created_at)
            )
            if same_batch or legacy_same_detection:
                return archived

    run_id, fallback_created_at = _current_detection_identity(
        root, str(dataset.get("dataset_id") or ""), model_id, str(context.get("detection_batch_id") or "")
    )
    created_at = str(context.get("created_at") or fallback_created_at)
    run_path = root / COMPARISON_DIRNAME / RUNS_DIRNAME / f"{run_id}.json"
    if run_path.is_file():
        payload = _read_json(run_path, {}) or {}
        return payload if isinstance(payload, dict) else None

    diagnostics: dict[str, list[dict[str, Any]]] = {}
    for panel in panels:
        source_id = str(panel.get("source_id") or "")
        if source_id in diagnostics:
            continue
        payload = _read_json(root / "localization_detections" / f"{source_id}.json", {}) or {}
        candidates = payload.get("candidates") if isinstance(payload, dict) else []
        diagnostics[source_id] = candidates if isinstance(candidates, list) else []
    if not any(diagnostics.values()):
        return None

    predictions_by_panel: dict[str, list[dict[str, Any]]] = {}
    for panel in panels:
        full_box = _box(panel.get("panel_box"))
        if full_box is None:
            continue
        key = f"{panel.get('source_id')}::{panel.get('panel_id')}"
        predictions_by_panel[key] = _machine_predictions_for_panel(diagnostics.get(str(panel.get("source_id") or ""), []), full_box)

    label = f"{model_id} · Stap 8"
    run = _evaluate_run(
        run_id=run_id,
        label=label,
        model_id=model_id,
        model_name=model_name,
        dataset_id=str(dataset.get("dataset_id") or ""),
        created_at=created_at,
        panels=panels,
        predictions_by_panel=predictions_by_panel,
        source="step3_localization_diagnostics",
    )
    run.update({
        "detection_batch_id": str(context.get("detection_batch_id") or ""),
        "model_training_run_id": str(context.get("model_training_run_id") or ""),
        "model_training_dataset_id": str(context.get("model_dataset_id") or ""),
    })
    _write_json(run_path, run)
    pointer = root / COMPARISON_DIRNAME / "latest.txt"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(run_id + "\n", encoding="ascii")
    for source_id in sorted({
        str(panel.get("source_id") or "").strip()
        for panel in panels
        if str(panel.get("source_id") or "").strip()
    }):
        set_ground_truth_source_review_completed(root, source_id, False)
    return run


def _current_evaluation_view(run: dict[str, Any]) -> dict[str, Any]:
    """Re-evaluate archived runs with current matching semantics in memory.

    Raw predictions and frozen GT stay untouched on disk. Existing Step-7 v1-v5
    runs immediately benefit from the current geometry/merge recovery after an
    upgrade, without forcing the user to run detection again.
    """
    try:
        schema_version = int(run.get("schema_version") or 1)
    except (TypeError, ValueError):
        schema_version = 1
    if schema_version >= EVALUATION_SCHEMA_VERSION:
        return run
    panels = []
    try:
        iou_threshold = float(run.get("iou_threshold") or DEFAULT_IOU_THRESHOLD)
    except (TypeError, ValueError):
        iou_threshold = DEFAULT_IOU_THRESHOLD
    try:
        geometry_iou = float(run.get("geometry_iou") or DEFAULT_GEOMETRY_IOU)
    except (TypeError, ValueError):
        geometry_iou = DEFAULT_GEOMETRY_IOU
    for panel in run.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        predictions = panel.get("predictions")
        predictions = predictions if isinstance(predictions, list) else []
        panels.append(_evaluate_panel(
            panel, predictions, iou_threshold=iou_threshold, geometry_iou=geometry_iou
        ))
    return {
        **run,
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "evaluation_upgraded_from_schema": schema_version,
        "metrics": _summarize(panels),
        "panels": panels,
    }


def _rebase_run_to_dataset(
    run: dict[str, Any], *, dataset: dict[str, Any], current_panels: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Re-evaluate archived predictions against the current canonical GT.

    This keeps model-v1 versus model-v2 comparison meaningful after a GT-only or
    hard-example dataset rebuild. The archived prediction geometry is immutable;
    only the evaluation view is recalculated. Panel-profile changes are not
    silently rebased because local coordinates would no longer be comparable.
    """
    current_dataset_id = str(dataset.get("dataset_id") or "")
    if str(run.get("dataset_id") or "") == current_dataset_id:
        return _current_evaluation_view(run)
    old_by_key = {
        f"{panel.get('source_id')}::{panel.get('panel_id')}": panel
        for panel in (run.get("panels") or []) if isinstance(panel, dict)
    }
    predictions_by_panel: dict[str, list[dict[str, Any]]] = {}
    usable = 0
    for panel in current_panels:
        key = f"{panel.get('source_id')}::{panel.get('panel_id')}"
        old = old_by_key.get(key)
        if not old:
            continue
        if _box(old.get("panel_box")) != _box(panel.get("panel_box")):
            continue
        predictions = old.get("predictions") if isinstance(old.get("predictions"), list) else []
        predictions_by_panel[key] = list(predictions)
        usable += 1
    if usable != len(current_panels):
        return None
    rebased = _evaluate_run(
        run_id=str(run.get("run_id") or ""),
        label=str(run.get("label") or run.get("run_id") or "Historische run"),
        model_id=str(run.get("model_id") or ""),
        model_name=str(run.get("model_name") or ""),
        dataset_id=current_dataset_id,
        created_at=str(run.get("created_at") or ""),
        panels=current_panels,
        predictions_by_panel=predictions_by_panel,
        source=str(run.get("source") or "") + ":rebased_current_gt",
        iou_threshold=float(run.get("iou_threshold") or DEFAULT_IOU_THRESHOLD),
        geometry_iou=float(run.get("geometry_iou") or DEFAULT_GEOMETRY_IOU),
    )
    rebased.update({
        "original_dataset_id": str(run.get("dataset_id") or ""),
        "rebased_to_current_gt": True,
        "detection_batch_id": str(run.get("detection_batch_id") or ""),
        "model_training_run_id": str(run.get("model_training_run_id") or ""),
        "model_training_dataset_id": str(run.get("model_training_dataset_id") or ""),
    })
    return rebased


def list_comparison_runs(workspace: str | Path) -> list[dict[str, Any]]:
    root = resolve_project_workspace(workspace)
    dataset = latest_table_cell_dataset(root)
    if not dataset:
        return []
    capture_current_detection_run(root)
    current_panels = _ground_truth_panels(root, dataset)
    result: list[dict[str, Any]] = []
    baseline = build_step4_baseline(root, dataset)
    if baseline:
        result.append(baseline)
    runs_root = root / COMPARISON_DIRNAME / RUNS_DIRNAME
    if runs_root.is_dir():
        for path in sorted(runs_root.glob("*.json")):
            payload = _read_json(path, {}) or {}
            if not isinstance(payload, dict) or not payload.get("run_id"):
                continue
            view = _rebase_run_to_dataset(payload, dataset=dataset, current_panels=current_panels)
            if view is not None:
                result.append(view)
    unique: dict[str, dict[str, Any]] = {}
    for item in result:
        unique[str(item.get("run_id"))] = item
    baseline_item = unique.pop(BASELINE_RUN_ID, None)
    ordered = sorted(unique.values(), key=lambda item: str(item.get("created_at") or ""))
    return ([baseline_item] if baseline_item else []) + ordered


def comparison_run_history(workspace: str | Path) -> list[dict[str, Any]]:
    """Compact all-dataset run history for UI/audit; never used as active review."""
    root = resolve_project_workspace(workspace)
    reviews = comparison_reviews(root)
    runs_root = root / COMPARISON_DIRNAME / RUNS_DIRNAME
    result: list[dict[str, Any]] = []
    if not runs_root.is_dir():
        return result
    for path in sorted(runs_root.glob("*.json")):
        payload = _read_json(path, {}) or {}
        if not isinstance(payload, dict) or not payload.get("run_id"):
            continue
        view = _current_evaluation_view(payload)
        run_id = str(view.get("run_id") or "")
        run_reviews = reviews.get(run_id, {}) if isinstance(reviews, dict) else {}
        run_reviews = run_reviews if isinstance(run_reviews, dict) else {}
        issues = [
            issue for panel in (view.get("panels") or []) if isinstance(panel, dict)
            for issue in (panel.get("issues") or []) if isinstance(issue, dict)
        ]
        reviewed = 0
        decisions: dict[str, int] = {}
        for issue in issues:
            review = _review_for_issue(issue, run_reviews)
            decision = str((review or {}).get("decision") or "")
            if decision and decision != "deferred":
                reviewed += 1
                decisions[decision] = decisions.get(decision, 0) + 1
        result.append({
            "run_id": run_id,
            "label": str(view.get("label") or run_id),
            "model_id": str(view.get("model_id") or ""),
            "dataset_id": str(view.get("dataset_id") or ""),
            "created_at": str(view.get("created_at") or ""),
            "metrics": dict(view.get("metrics") or {}),
            "issue_count": len(issues),
            "reviewed_issue_count": reviewed,
            "open_issue_count": max(0, len(issues) - reviewed),
            "decisions": decisions,
        })
    return sorted(result, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def _reviews_path(root: Path) -> Path:
    return root / COMPARISON_DIRNAME / "reviews.json"


def comparison_reviews(workspace: str | Path) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    payload = _read_json(_reviews_path(root), {}) or {}
    return payload if isinstance(payload, dict) else {}


def _review_for_issue(issue: dict[str, Any], run_reviews: dict[str, Any]) -> dict[str, Any] | None:
    review = run_reviews.get(str(issue.get("issue_id") or "")) if isinstance(run_reviews, dict) else None
    if isinstance(review, dict):
        return review
    legacy_ids = issue.get("legacy_issue_ids") or []
    if not isinstance(run_reviews, dict) or not legacy_ids:
        return None
    legacy_reviews = [run_reviews.get(str(key)) for key in legacy_ids]
    legacy_reviews = [item for item in legacy_reviews if isinstance(item, dict)]
    if len(legacy_reviews) != len(legacy_ids) or not legacy_reviews:
        return None
    decisions = {str(item.get("decision") or "") for item in legacy_reviews}
    if len(decisions) == 1 and next(iter(decisions)) not in {"", "deferred", "gt_added"}:
        return max(legacy_reviews, key=lambda item: str(item.get("reviewed_at") or ""))
    return None


def latest_completed_training_feedback(workspace: str | Path) -> dict[str, Any]:
    """Translate the newest fully reviewed Step-7 run into training feedback.

    Only explicit ``model_error`` decisions become hard examples. Functional
    geometry is deliberately not punished. A newer completed review supersedes
    older feedback, including the case where it contains zero model errors; this
    lets the next dataset remove hard-example oversampling once a model has fixed
    those failures.
    """
    root = resolve_project_workspace(workspace)
    reviews = comparison_reviews(root)
    runs_root = root / COMPARISON_DIRNAME / RUNS_DIRNAME
    if not runs_root.is_dir():
        return {"available": False, "fingerprint": "", "model_error_count": 0, "panel_weights": {}}
    candidates: list[dict[str, Any]] = []
    for path in runs_root.glob("*.json"):
        payload = _read_json(path, {}) or {}
        if isinstance(payload, dict) and payload.get("run_id"):
            candidates.append(_current_evaluation_view(payload))
    candidates.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    for run in candidates:
        run_id = str(run.get("run_id") or "")
        run_reviews = reviews.get(run_id, {}) if isinstance(reviews, dict) else {}
        run_reviews = run_reviews if isinstance(run_reviews, dict) else {}
        issues = [
            issue for panel in (run.get("panels") or []) if isinstance(panel, dict)
            for issue in (panel.get("issues") or []) if isinstance(issue, dict)
        ]
        if not issues:
            fingerprint = hashlib.sha256(json.dumps({
                "run_id": run_id, "decisions": []
            }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            return {
                "available": True,
                "run_id": run_id,
                "model_id": str(run.get("model_id") or ""),
                "dataset_id": str(run.get("dataset_id") or ""),
                "created_at": str(run.get("created_at") or ""),
                "fingerprint": fingerprint,
                "issue_count": 0,
                "decision_counts": {},
                "model_error_count": 0,
                "model_errors": [],
                "panel_weights": {},
                "source_weights": {},
                "policy": "perfect run; previous hard-example weighting cleared",
            }
        resolved: list[tuple[dict[str, Any], dict[str, Any]]] = []
        complete = True
        for issue in issues:
            review = _review_for_issue(issue, run_reviews)
            decision = str((review or {}).get("decision") or "")
            if not decision or decision == "deferred":
                complete = False
                break
            resolved.append((issue, review or {}))
        if not complete:
            continue

        panel_weights: dict[str, int] = {}
        source_weights: dict[str, int] = {}
        model_errors: list[dict[str, Any]] = []
        type_multiplier = {"geometry": 3, "fn": 3, "fp": 3, "merged": 4}
        decision_counts: dict[str, int] = {}
        material = []
        for issue, review in resolved:
            decision = str(review.get("decision") or "")
            decision_counts[decision] = decision_counts.get(decision, 0) + 1
            material.append((str(issue.get("issue_id") or ""), decision))
            if decision != "model_error":
                continue
            source_id = str(issue.get("source_id") or "")
            panel_id = str(issue.get("panel_id") or "")
            key = f"{source_id}::{panel_id}"
            multiplier = int(type_multiplier.get(str(issue.get("type") or ""), 3))
            panel_weights[key] = max(panel_weights.get(key, 1), multiplier)
            source_weights[source_id] = max(source_weights.get(source_id, 1), multiplier)
            model_errors.append({
                "issue_id": str(issue.get("issue_id") or ""),
                "type": str(issue.get("type") or ""),
                "source_id": source_id,
                "panel_id": panel_id,
                "multiplier": multiplier,
            })
        fingerprint = hashlib.sha256(json.dumps({
            "run_id": run_id,
            "decisions": sorted(material),
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return {
            "available": True,
            "run_id": run_id,
            "model_id": str(run.get("model_id") or ""),
            "dataset_id": str(run.get("dataset_id") or ""),
            "created_at": str(run.get("created_at") or ""),
            "fingerprint": fingerprint,
            "issue_count": len(issues),
            "decision_counts": decision_counts,
            "model_error_count": len(model_errors),
            "model_errors": model_errors,
            "panel_weights": panel_weights,
            "source_weights": source_weights,
            "policy": "model_error only; geometry/fn/fp x3, merged x4; train split only",
        }
    return {"available": False, "fingerprint": "", "model_error_count": 0, "panel_weights": {}}


def _gt_worklist_for_run(run: dict[str, Any], reviews: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only unresolved GT checks from one immutable prediction run."""
    run_id = str(run.get("run_id") or "")
    run_reviews = reviews.get(run_id, {}) if isinstance(reviews, dict) else {}
    if not isinstance(run_reviews, dict):
        run_reviews = {}
    result: list[dict[str, Any]] = []
    for panel in run.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        for issue in panel.get("issues") or []:
            if not isinstance(issue, dict):
                continue
            review = _review_for_issue(issue, run_reviews) or {}
            if str(review.get("decision") or "") != "gt_check":
                continue
            result.append({
                "run_id": run_id,
                "issue_id": str(issue.get("issue_id") or ""),
                "source_id": str(issue.get("source_id") or panel.get("source_id") or ""),
                "panel_id": str(issue.get("panel_id") or panel.get("panel_id") or ""),
                "panel_name": str(issue.get("panel_name") or panel.get("panel_name") or ""),
                "type": str(issue.get("type") or ""),
                "label": str(issue.get("label") or ""),
                "prediction_box": issue.get("prediction_box"),
                "gt_boxes": issue.get("gt_boxes") or [],
                "reviewed_at": str(review.get("reviewed_at") or ""),
            })
    return result


# These are deliberately suggestions rather than a new evaluator threshold.
# A user still explicitly applies the list in Step 9. They are looser than the
# immutable run metric policy, but retain that policy's no-neighbour safeguard.
FUNCTIONAL_SUGGESTION_GT_COVERAGE = 0.85
FUNCTIONAL_SUGGESTION_PREDICTION_EXCESS = 0.45


def functional_geometry_suggestions(candidate: dict[str, Any], run_reviews: dict[str, Any]) -> dict[str, Any]:
    """Return conservative, reviewable functional-correct suggestions."""
    suggestions: list[dict[str, Any]] = []
    for panel in candidate.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        truth = panel.get("ground_truth") or []
        for issue in panel.get("issues") or []:
            if not isinstance(issue, dict) or str(issue.get("type") or "") != "geometry":
                continue
            if _review_for_issue(issue, run_reviews):
                continue
            # FP/FN recovery is deliberately left for human review.
            if str(issue.get("match_reason") or "") != "iou" or issue.get("spatial_recovered"):
                continue
            prediction_box = _box(issue.get("prediction_box"))
            gt_boxes = issue.get("gt_boxes") or []
            gt_box = _box(gt_boxes[0]) if len(gt_boxes) == 1 else None
            if prediction_box is None or gt_box is None:
                continue
            quality = _geometry_quality(prediction_box, gt_box)
            if (
                float(quality.get("gt_coverage") or 0.0) < FUNCTIONAL_SUGGESTION_GT_COVERAGE
                or float(quality.get("prediction_excess") or 1.0) > FUNCTIONAL_SUGGESTION_PREDICTION_EXCESS
            ):
                continue
            reaches_other_cell = any(
                isinstance(other_gt, dict)
                and (other_box := _box(other_gt.get("box"))) is not None
                and tuple(other_box) != tuple(gt_box)
                and _gt_boxes_are_spatially_distinct(gt_box, other_box)
                and _box_center_inside(other_box, prediction_box)
                for other_gt in truth
            )
            if reaches_other_cell:
                continue
            suggestions.append({
                "issue_id": str(issue.get("issue_id") or ""),
                "source_id": str(panel.get("source_id") or ""),
                "panel_name": str(panel.get("panel_name") or panel.get("panel_id") or ""),
                "gt_coverage": float(quality.get("gt_coverage") or 0.0),
                "prediction_excess": float(quality.get("prediction_excess") or 0.0),
            })
    return {
        "issues": suggestions,
        "issue_ids": [item["issue_id"] for item in suggestions if item["issue_id"]],
        "gt_coverage": FUNCTIONAL_SUGGESTION_GT_COVERAGE,
        "prediction_excess": FUNCTIONAL_SUGGESTION_PREDICTION_EXCESS,
    }


# Mirrors functional_geometry_suggestions but flags the opposite extreme:
# a prediction far taller than any GT cell the reviewer already accepted in
# that same panel is an obvious model error, never a legitimate cell. Height
# (not area) is the signal because column width legitimately varies a lot
# between cells, while a cell's height rarely should. A "geometry" issue
# already has its own one-to-one matched GT cell (from _geometry_quality),
# so it is compared against that cell's own height, not the panel's tallest
# cell — a panel that also contains a tall merged header row would otherwise
# dilute the ratio for an ordinary data row far below the threshold, even
# though the row's own match is obviously oversized. Only "fp" stray
# detections, which have no matched cell to compare against, fall back to
# the tallest GT box in the same panel rather than a dataset-wide value,
# because typical cell height differs by table type and a global reference
# would be too permissive for panels made of small cells. A user still
# explicitly applies the list, same as the functional suggestions above.
# Real Step-7 review data showed obviously-wrong detections sitting at
# ~1.9x their matched GT cell, so a 2x floor missed them; 1.5x is the new
# floor, chosen to still leave a mildly oversized (but plausibly correct)
# crop for manual review rather than auto-suggesting it.
OBVIOUS_ERROR_HEIGHT_RATIO = 1.5

# A "geometry" issue can also be obviously oversized without ever crossing
# the height-ratio floor above: a box that already contains virtually the
# whole GT cell (gt_coverage) but still carries far more excess area than
# functional_geometry_suggestions would ever wave through as harmless is,
# by construction, too large for that cell — whatever its exact height vs.
# width split happens to be. This matters most when the excess comes from
# extra width rather than height (a box reaching sideways into a neighbour
# column), which the height-ratio check above can never see. This mirrors
# FUNCTIONAL_SUGGESTION_* below so the two suggestion lists partition
# cleanly: <=45% excess can be offered as "waarschijnlijk functioneel
# correct", >45% (with the GT still essentially covered) is instead offered
# here as an obvious model error.
OBVIOUS_ERROR_GT_COVERAGE = 0.95
OBVIOUS_ERROR_PREDICTION_EXCESS = FUNCTIONAL_SUGGESTION_PREDICTION_EXCESS


def obvious_error_suggestions(candidate: dict[str, Any], run_reviews: dict[str, Any]) -> dict[str, Any]:
    """Return conservative suggestions for predictions far taller/larger than their matched (or panel) GT."""
    suggestions: list[dict[str, Any]] = []
    for panel in candidate.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        truth = panel.get("ground_truth") or []
        gt_heights = [
            gt_box[3] - gt_box[1]
            for gt in truth
            if isinstance(gt, dict) and (gt_box := _box(gt.get("box"))) is not None
        ]
        if not gt_heights:
            continue
        max_gt_height = max(gt_heights)
        if max_gt_height <= 0:
            continue
        for issue in panel.get("issues") or []:
            issue_type = str(issue.get("type") or "")
            if not isinstance(issue, dict) or issue_type not in {"fp", "geometry"}:
                continue
            if _review_for_issue(issue, run_reviews):
                continue
            prediction_box = _box(issue.get("prediction_box"))
            if prediction_box is None:
                continue

            reference_height = max_gt_height
            gt_coverage: float | None = None
            prediction_excess: float | None = None
            gt_boxes = issue.get("gt_boxes") or []
            if issue_type == "geometry" and isinstance(gt_boxes, list) and len(gt_boxes) == 1:
                matched_gt_box = _box(gt_boxes[0])
                if matched_gt_box is not None:
                    matched_height = matched_gt_box[3] - matched_gt_box[1]
                    if matched_height > 0:
                        reference_height = matched_height
                    quality = _geometry_quality(prediction_box, matched_gt_box)
                    gt_coverage = float(quality.get("gt_coverage") or 0.0)
                    prediction_excess = float(quality.get("prediction_excess") or 0.0)

            height_ratio = (prediction_box[3] - prediction_box[1]) / reference_height
            oversized_by_excess = (
                gt_coverage is not None
                and prediction_excess is not None
                and gt_coverage >= OBVIOUS_ERROR_GT_COVERAGE
                and prediction_excess > OBVIOUS_ERROR_PREDICTION_EXCESS
            )
            if height_ratio < OBVIOUS_ERROR_HEIGHT_RATIO and not oversized_by_excess:
                continue
            suggestions.append({
                "issue_id": str(issue.get("issue_id") or ""),
                "source_id": str(panel.get("source_id") or ""),
                "panel_name": str(panel.get("panel_name") or panel.get("panel_id") or ""),
                "type": issue_type,
                "height_ratio": height_ratio,
                "max_gt_height": reference_height,
                "gt_coverage": gt_coverage,
                "prediction_excess": prediction_excess,
                "oversized_by_excess": oversized_by_excess,
            })
    suggestions.sort(key=lambda item: item["height_ratio"], reverse=True)
    return {
        "issues": suggestions,
        "issue_ids": [item["issue_id"] for item in suggestions if item["issue_id"]],
        "height_ratio_threshold": OBVIOUS_ERROR_HEIGHT_RATIO,
        "gt_coverage_threshold": OBVIOUS_ERROR_GT_COVERAGE,
        "prediction_excess_threshold": OBVIOUS_ERROR_PREDICTION_EXCESS,
    }


def training_report_for_run(workspace: str | Path, run: dict[str, Any]) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    reviews = comparison_reviews(root)
    run_id = str(run.get("run_id") or "")
    run_reviews = reviews.get(run_id, {}) if isinstance(reviews, dict) else {}
    run_reviews = run_reviews if isinstance(run_reviews, dict) else {}
    decisions: dict[str, int] = {}
    issues = [
        issue
        for panel in (run.get("panels") or [])
        if isinstance(panel, dict)
        for issue in (panel.get("issues") or [])
        if isinstance(issue, dict)
    ]
    for issue in issues:
        review = _review_for_issue(issue, run_reviews) or {}
        decision = str(review.get("decision") or "")
        if decision and decision != "deferred":
            decisions[decision] = decisions.get(decision, 0) + 1
    direct_correct = int((run.get("metrics") or {}).get("direct_correct") or 0)
    functional_ok = int(decisions.get("functional_ok", 0))
    reviewed = sum(decisions.values())
    return {
        "run_id": run_id,
        "model_id": str(run.get("model_id") or ""),
        "correct": direct_correct,
        "functional_ok": functional_ok,
        "model_error": int(decisions.get("model_error", 0)),
        "gt_check": int(decisions.get("gt_check", 0)),
        "gt_correction": int(decisions.get("gt_added", 0)),
        "reviewed": reviewed,
        "open": max(0, len(issues) - reviewed),
        "issue_total": len(issues),
        "decision_counts": decisions,
    }


def review_comparison_issue(workspace: str | Path, run_id: str, issue_id: str, decision: str) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    allowed = {"model_error", "functional_ok", "gt_check", "gt_added", "deferred", "clear"}
    if decision not in allowed:
        raise ValueError("Onbekende vervolg-reviewbeslissing")
    runs = {str(item.get("run_id")): item for item in list_comparison_runs(root)}
    run = runs.get(run_id)
    if not run or run_id == BASELINE_RUN_ID:
        raise KeyError(run_id)
    current = capture_current_detection_run(root)
    if current is not None and str(current.get("run_id") or "") != run_id:
        raise ValueError("Historische detectieruns zijn alleen-lezen; beoordeel uitsluitend de nieuwste Stap-8-run")
    selected_panel: dict[str, Any] | None = None
    selected_issue: dict[str, Any] | None = None
    for panel in run.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        for issue in panel.get("issues") or []:
            if isinstance(issue, dict) and str(issue.get("issue_id") or "") == issue_id:
                selected_panel = panel
                selected_issue = issue
                break
        if selected_issue is not None:
            break
    if selected_issue is None:
        raise KeyError(issue_id)
    if decision == "functional_ok" and str(selected_issue.get("type") or "") != "geometry":
        raise ValueError("Functioneel correct is alleen geldig voor geometrie-afwijkingen")
    if decision == "gt_check":
        source_id = str(
            selected_issue.get("source_id")
            or (selected_panel or {}).get("source_id")
            or ""
        ).strip()
        if source_id:
            set_ground_truth_source_review_completed(root, source_id, False)
    payload = comparison_reviews(root)
    run_reviews = payload.setdefault(run_id, {})
    if decision == "clear":
        run_reviews.pop(issue_id, None)
    else:
        run_reviews[issue_id] = {"decision": decision, "reviewed_at": utc_now()}
    _write_json(_reviews_path(root), payload)
    return dict(run_reviews.get(issue_id) or {})


def review_comparison_issues_bulk(
    workspace: str | Path, run_id: str, issue_ids: list[str], decision: str
) -> list[str]:
    """Apply one review decision to many issues in a single reviews.json write.

    Mirrors review_comparison_issue's validation, but looks the run up once
    and reads/writes reviews.json once instead of once per issue. The bulk
    suggestion actions (apply_functional_suggestions, apply_obvious_error_suggestions)
    can select dozens of issues on a noisy run, and calling review_comparison_issue
    in a loop made that scale roughly quadratically on exactly the runs where
    it matters most, with no atomicity across the loop if a later call failed.
    """
    root = resolve_project_workspace(workspace)
    allowed = {"model_error", "functional_ok", "gt_check", "gt_added", "deferred", "clear"}
    if decision not in allowed:
        raise ValueError("Onbekende vervolg-reviewbeslissing")
    runs = {str(item.get("run_id")): item for item in list_comparison_runs(root)}
    run = runs.get(run_id)
    if not run or run_id == BASELINE_RUN_ID:
        raise KeyError(run_id)
    current = capture_current_detection_run(root)
    if current is not None and str(current.get("run_id") or "") != run_id:
        raise ValueError("Historische detectieruns zijn alleen-lezen; beoordeel uitsluitend de nieuwste Stap-8-run")

    issues_by_id: dict[str, dict[str, Any]] = {}
    for panel in run.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        for issue in panel.get("issues") or []:
            candidate_id = str((issue or {}).get("issue_id") or "")
            if candidate_id:
                issues_by_id[candidate_id] = issue

    payload = comparison_reviews(root)
    run_reviews = payload.setdefault(run_id, {})
    gt_check_source_ids: set[str] = set()
    applied: list[str] = []
    for issue_id in issue_ids:
        issue = issues_by_id.get(issue_id)
        if issue is None:
            continue
        if decision == "functional_ok" and str(issue.get("type") or "") != "geometry":
            continue
        if decision == "gt_check":
            source_id = str(issue.get("source_id") or "").strip()
            if source_id:
                gt_check_source_ids.add(source_id)
        if decision == "clear":
            run_reviews.pop(issue_id, None)
        else:
            run_reviews[issue_id] = {"decision": decision, "reviewed_at": utc_now()}
        applied.append(issue_id)
    if not applied:
        return applied
    _write_json(_reviews_path(root), payload)
    for source_id in gt_check_source_ids:
        set_ground_truth_source_review_completed(root, source_id, False)
    return applied


def add_comparison_fp_to_ground_truth(workspace: str | Path, run_id: str, issue_id: str) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    runs = {str(item.get("run_id")): item for item in list_comparison_runs(root)}
    run = runs.get(str(run_id or ""))
    if not run or str(run.get("run_id") or "") == BASELINE_RUN_ID:
        raise KeyError(run_id)
    current = capture_current_detection_run(root)
    if current is not None and str(current.get("run_id") or "") != str(run_id or ""):
        raise ValueError("Historische detectieruns zijn alleen-lezen; Ground Truth-promotie is alleen toegestaan vanuit de nieuwste Stap-8-run")

    selected_panel: dict[str, Any] | None = None
    selected_issue: dict[str, Any] | None = None
    for panel in run.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        for issue in panel.get("issues") or []:
            if isinstance(issue, dict) and str(issue.get("issue_id") or "") == str(issue_id or ""):
                selected_panel = panel
                selected_issue = issue
                break
        if selected_issue is not None:
            break
    if selected_panel is None or selected_issue is None:
        raise KeyError(issue_id)
    if str(selected_issue.get("type") or "") != "fp":
        raise ValueError("Alleen een extra detectie (FP) kan rechtstreeks als nieuwe GT-cel worden toegevoegd")

    local_box = _box(selected_issue.get("prediction_box"))
    panel_box = _box(selected_panel.get("panel_box"))
    if local_box is None or panel_box is None:
        raise ValueError("Prediction- of panelgeometrie ontbreekt")
    full_box = (
        panel_box[0] + local_box[0],
        panel_box[1] + local_box[1],
        panel_box[0] + local_box[2],
        panel_box[1] + local_box[3],
    )
    source_id = str(selected_panel.get("source_id") or selected_issue.get("source_id") or "").strip()
    if not source_id:
        raise ValueError("Bron-ID ontbreekt voor deze prediction")

    for existing in list_ground_truth_cells(root, source_id):
        existing_box = _box([existing.get("x1"), existing.get("y1"), existing.get("x2"), existing.get("y2")])
        if existing_box is not None and _iou(full_box, existing_box) >= 0.95:
            review_comparison_issue(root, run_id, issue_id, "gt_added")
            return {"cell": dict(existing), "already_present": True}

    rounded = tuple(int(round(value)) for value in full_box)
    cell = add_ground_truth_cell(
        root,
        source_id,
        rounded,
        panel_id=str(selected_panel.get("panel_id") or ""),
        panel_name=str(selected_panel.get("panel_name") or selected_panel.get("panel_id") or ""),
        provenance="step7_prediction_gt",
    )
    review_comparison_issue(root, run_id, issue_id, "gt_added")
    return {"cell": cell, "already_present": False}


def _metric_delta(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    left = reference.get("metrics") or {}
    right = candidate.get("metrics") or {}
    keys = ("precision", "recall", "f1", "tp", "fp", "fn", "direct_correct", "geometry_mismatch", "merged", "review_needed")
    result = {}
    for key in keys:
        try:
            result[key] = float(right.get(key) or 0) - float(left.get(key) or 0)
        except (TypeError, ValueError):
            result[key] = 0.0
    return result


def table_cell_comparison_state(
    workspace: str | Path, *, reference_run_id: str | None = None, candidate_run_id: str | None = None
) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    dataset = latest_table_cell_dataset(root)
    history = comparison_run_history(root)
    if not dataset:
        return {
            "ready": False,
            "reason": "Bouw eerst in Stap 8 een table-cell trainingsdataset uit de afgeronde Stap-7-ground-truth.",
            "history": history,
        }

    detection_context = current_detection_context(root)
    active = active_table_cell_model(root) or {}
    active_model_id = str(active.get("model_id") or "")
    detected_model_id = str(detection_context.get("model_id") or "") if detection_context.get("available") else ""
    if detection_context.get("available") and active_model_id and detected_model_id != active_model_id:
        return {
            "ready": False,
            "detection_stale": True,
            "reason": (
                f"Het actieve model is {active_model_id}, maar de laatste complete Stap-8-detectie is gemaakt met "
                f"{detected_model_id or 'een ouder/generiek model'}. Voer Stap 8 opnieuw uit; oude reviewdata blijft alleen historie."
            ),
            "dataset": dataset,
            "active_model": active,
            "detection_context": detection_context,
            "history": history,
            "runs": list_comparison_runs(root),
        }
    runs = list_comparison_runs(root)
    migration_candidate = None
    if not detection_context.get("available") and candidate_run_id:
        migration_candidate = next((item for item in runs if str(item.get("run_id") or "") == str(candidate_run_id)), None)
    if not detection_context.get("available") and migration_candidate is None:
        return {
            "ready": False,
            "reason": "Er is nog geen complete Stap-8-detectierun voor de huidige bronnen. Voer Stap 8 opnieuw uit.",
            "dataset": dataset,
            "active_model": active,
            "detection_context": detection_context,
            "history": history,
            "runs": runs,
        }

    current_run = capture_current_detection_run(root) if detection_context.get("available") else migration_candidate
    if len(runs) < 2 or not current_run:
        return {
            "ready": False,
            "reason": "Er is wel Ground Truth, maar nog geen nieuwe Stap-8-detectierun om ermee te vergelijken.",
            "dataset": dataset,
            "runs": runs,
            "history": history,
            "active_model": active,
            "detection_context": detection_context,
        }

    by_id = {str(item.get("run_id")): item for item in runs}
    active_run_id = str(current_run.get("run_id") or "")
    candidate = by_id.get(str(candidate_run_id or "")) if candidate_run_id else by_id.get(active_run_id)
    if candidate is None or str(candidate.get("run_id") or "") == BASELINE_RUN_ID:
        candidate = by_id.get(active_run_id) or runs[-1]
    history_mode = str(candidate.get("run_id") or "") != active_run_id

    candidate_index = runs.index(candidate)
    default_reference = runs[candidate_index - 1] if candidate_index > 0 else runs[0]
    reference = by_id.get(str(reference_run_id or "")) if reference_run_id else default_reference
    if reference is None or reference is candidate:
        reference = default_reference

    reviews = comparison_reviews(root).get(str(candidate.get("run_id")), {})
    reviews = reviews if isinstance(reviews, dict) else {}
    functional_suggestions = functional_geometry_suggestions(candidate, reviews)
    error_suggestions = obvious_error_suggestions(candidate, reviews)
    issue_panels = []
    total_issues = reviewed_issues = 0
    decision_counts: dict[str, int] = {}
    for panel in candidate.get("panels") or []:
        issues = []
        for issue in panel.get("issues") or []:
            if not isinstance(issue, dict):
                continue
            review = _review_for_issue(issue, reviews)
            enriched = {**issue, "review": review or {}}
            if str(issue.get("type") or "") == "geometry":
                pred_box = _box(issue.get("prediction_box"))
                gt_boxes = issue.get("gt_boxes") or []
                gt_box = _box(gt_boxes[0]) if isinstance(gt_boxes, list) and gt_boxes else None
                if pred_box is not None and gt_box is not None:
                    enriched.update(_geometry_quality(pred_box, gt_box))
            issues.append(enriched)
            total_issues += 1
            decision = str((review or {}).get("decision") or "")
            if decision and decision != "deferred":
                reviewed_issues += 1
                decision_counts[decision] = decision_counts.get(decision, 0) + 1
        if issues:
            issue_panels.append({**panel, "issues": issues})

    open_issues = max(0, total_issues - reviewed_issues)
    report = training_report_for_run(root, candidate)
    return {
        "ready": True,
        "dataset": dataset,
        "runs": runs,
        "history": history,
        "reference": reference,
        "candidate": candidate,
        "active_run_id": active_run_id,
        "history_mode": history_mode,
        "review_writable": not history_mode,
        "active_model": active,
        "detection_context": detection_context,
        "delta": _metric_delta(reference, candidate),
        "issue_panels": issue_panels,
        "issue_count": total_issues,
        "reviewed_issue_count": reviewed_issues,
        "open_issue_count": open_issues,
        "review_complete": open_issues == 0,
        "decision_counts": decision_counts,
        "training_report": report,
        "gt_worklist": _gt_worklist_for_run(candidate, comparison_reviews(root)),
        "training_feedback": latest_completed_training_feedback(root),
        "functional_suggestions": functional_suggestions,
        "obvious_error_suggestions": error_suggestions,
    }
