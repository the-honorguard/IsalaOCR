from __future__ import annotations

import statistics
from typing import Any, Sequence

from ..models import Box



def intersection_over_union(left: Box, right: Box) -> float:
    """Dependency-light IoU used by evaluation and the WebUI diagnostics."""
    ix1, iy1 = max(left.x1, right.x1), max(left.y1, right.y1)
    ix2, iy2 = min(left.x2, right.x2), min(left.y2, right.y2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    intersection = iw * ih
    if intersection <= 0:
        return 0.0
    union = left.width * left.height + right.width * right.height - intersection
    return intersection / max(1, union)


def greedy_detection_metrics(
    predictions: Sequence[Box],
    ground_truth: Sequence[Box],
    *,
    iou_threshold: float = 0.75,
) -> dict[str, Any]:
    """Greedy one-to-one detection matching without heavy ML dependencies."""
    pairs: list[tuple[float, int, int]] = []
    for p_index, prediction in enumerate(predictions):
        for g_index, truth in enumerate(ground_truth):
            iou = intersection_over_union(prediction, truth)
            if iou >= iou_threshold:
                pairs.append((iou, p_index, g_index))
    pairs.sort(reverse=True)
    used_p: set[int] = set()
    used_g: set[int] = set()
    matched_ious: list[float] = []
    for iou, p_index, g_index in pairs:
        if p_index in used_p or g_index in used_g:
            continue
        used_p.add(p_index)
        used_g.add(g_index)
        matched_ious.append(iou)
    tp = len(matched_ious)
    fp = max(0, len(predictions) - tp)
    fn = max(0, len(ground_truth) - tp)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
        "mean_iou": statistics.fmean(matched_ious) if matched_ious else 0.0,
        "median_iou": statistics.median(matched_ious) if matched_ious else 0.0,
        "matched_ious": matched_ious,
    }

def passes_detection_gate(
    metrics: dict[str, Any], thresholds: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Evaluate geometry-only detector metrics against configured gate thresholds.

    Kept in a dependency-light module so the WebUI/labeler container can derive
    Detection Gate state without importing OpenCV, NumPy or OCR/table modules.
    """
    checks = [
        (
            "evaluated_images",
            float(metrics.get("evaluated_images") or 0),
            float(thresholds.get("minimum_test_images", 3)),
            ">=",
        ),
        (
            "ground_truth_rois",
            float(metrics.get("ground_truth_rois") or 0),
            float(thresholds.get("minimum_test_rois", 10)),
            ">=",
        ),
        (
            "recall",
            float(metrics.get("recall") or 0),
            float(thresholds.get("minimum_recall", 0.95)),
            ">=",
        ),
        (
            "precision",
            float(metrics.get("precision") or 0),
            float(thresholds.get("minimum_precision", 0.90)),
            ">=",
        ),
        (
            "auto_accept_rate",
            float(metrics.get("auto_accept_rate") or 0),
            float(thresholds.get("minimum_auto_accept_rate", 0.85)),
            ">=",
        ),
        (
            "false_positives_per_image",
            float(
                metrics.get("false_positives_per_image")
                if metrics.get("false_positives_per_image") is not None
                else 999
            ),
            float(thresholds.get("maximum_false_positives_per_image", 1.0)),
            "<=",
        ),
    ]
    failures: list[str] = []
    for name, value, target, operator in checks:
        ok = value >= target if operator == ">=" else value <= target
        if not ok:
            failures.append(f"{name} {value:.3f} {operator} {target:.3f} niet gehaald")
    return not failures, failures
