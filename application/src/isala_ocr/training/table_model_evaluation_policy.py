from __future__ import annotations

from typing import Any

# Step 7 is a functional crop review, not a pixel-perfect box reproduction test.
# These bounds intentionally apply only after the existing evaluator has made a
# one-to-one prediction/GT match. Containment recovery itself keeps its stricter
# 95% threshold in table_model_comparison.py, and merged-cell classification is
# evaluated before this policy can accept anything.
AUTO_FUNCTIONAL_GT_COVERAGE = 0.92
AUTO_FUNCTIONAL_PREDICTION_EXCESS = 0.30
POLICY_SCHEMA_VERSION = 7


def install_table_model_evaluation_policy() -> None:
    """Install the current functional geometry policy on the comparison module.

    This lives as a small policy layer so the acceptance rule is explicit and
    independently testable. The underlying evaluator remains responsible for
    matching, merge detection, FP/FN classification and immutable run storage.
    """
    from . import table_model_comparison as comparison

    if getattr(comparison, "_auto_functional_policy_installed", False):
        return

    original_geometry_quality = comparison._geometry_quality
    original_evaluate_panel = comparison._evaluate_panel
    original_summarize = comparison._summarize
    original_metric_delta = comparison._metric_delta

    def geometry_quality(
        prediction_box: tuple[float, float, float, float],
        gt_box: tuple[float, float, float, float],
    ) -> dict[str, Any]:
        quality = dict(original_geometry_quality(prediction_box, gt_box))
        quality["functional_candidate"] = (
            float(quality.get("gt_coverage") or 0.0) >= AUTO_FUNCTIONAL_GT_COVERAGE
            and float(quality.get("prediction_excess") or 1.0) <= AUTO_FUNCTIONAL_PREDICTION_EXCESS
        )
        quality["auto_functional_threshold"] = True
        return quality

    def evaluate_panel(
        panel: dict[str, Any],
        predictions: list[dict[str, Any]],
        *,
        iou_threshold: float,
        geometry_iou: float,
    ) -> dict[str, Any]:
        result = original_evaluate_panel(
            panel,
            predictions,
            iou_threshold=iou_threshold,
            geometry_iou=geometry_iou,
        )

        # Never let the convenience rule hide a prediction that the stricter
        # structural evaluator identified as spanning multiple logical GT cells.
        merged_prediction_boxes = {
            tuple(issue.get("prediction_box") or [])
            for issue in result.get("issues") or []
            if isinstance(issue, dict)
            and str(issue.get("type") or "") == "merged"
            and issue.get("prediction_box")
        }

        kept_issues: list[dict[str, Any]] = []
        auto_functional = 0
        accepted_pairs: set[tuple[int, int]] = set()
        truth = panel.get("ground_truth") or []

        for issue in result.get("issues") or []:
            if not isinstance(issue, dict) or str(issue.get("type") or "") != "geometry":
                kept_issues.append(issue)
                continue

            prediction_box = comparison._box(issue.get("prediction_box"))
            gt_boxes = issue.get("gt_boxes") or []
            gt_box = comparison._box(gt_boxes[0]) if isinstance(gt_boxes, list) and len(gt_boxes) == 1 else None
            if prediction_box is None or gt_box is None:
                kept_issues.append(issue)
                continue

            quality = geometry_quality(prediction_box, gt_box)
            prediction_key = tuple(issue.get("prediction_box") or [])
            if prediction_key in merged_prediction_boxes or not quality.get("functional_candidate"):
                kept_issues.append(issue)
                continue

            # The original evaluator only emits a geometry issue for an already
            # one-to-one matched pair. Trace it back before applying any automatic
            # acceptance so the result remains auditable.
            matched_pair: tuple[int, int] | None = None
            matched_record: dict[str, Any] | None = None
            for match in result.get("matches") or []:
                try:
                    pred_index = int(match.get("prediction_index"))
                    gt_index = int(match.get("gt_index"))
                    pred_raw = predictions[pred_index].get("box")
                    gt_raw = truth[gt_index].get("box")
                except (IndexError, TypeError, ValueError, AttributeError):
                    continue
                if tuple(pred_raw or []) == prediction_key and tuple(gt_raw or []) == tuple(gt_boxes[0] or []):
                    matched_pair = (pred_index, gt_index)
                    matched_record = match
                    break

            if matched_pair is None or matched_record is None:
                kept_issues.append(issue)
                continue

            # Extra area is only harmless while it does not reach the centre of
            # another spatially distinct GT cell. This catches partial neighbour
            # capture that can stay below the normal 70% merged-cell threshold.
            _, matched_gt_index = matched_pair
            reaches_other_cell = False
            for other_index, other_gt in enumerate(truth):
                if other_index == matched_gt_index or not isinstance(other_gt, dict):
                    continue
                other_box = comparison._box(other_gt.get("box"))
                if other_box is None:
                    continue
                if not comparison._gt_boxes_are_spatially_distinct(gt_box, other_box):
                    continue
                if comparison._box_center_inside(other_box, prediction_box):
                    reaches_other_cell = True
                    break
            if reaches_other_cell:
                kept_issues.append(issue)
                continue

            matched_record["functional_accepted"] = True
            matched_record["functional_gt_coverage"] = float(quality.get("gt_coverage") or 0.0)
            matched_record["functional_prediction_excess"] = float(quality.get("prediction_excess") or 0.0)
            accepted_pairs.add(matched_pair)
            auto_functional += 1

        result["issues"] = kept_issues
        result["functional_correct"] = auto_functional
        result["geometry_mismatch"] = max(0, int(result.get("geometry_mismatch") or 0) - auto_functional)
        result["functional_policy"] = {
            "gt_coverage": AUTO_FUNCTIONAL_GT_COVERAGE,
            "prediction_excess": AUTO_FUNCTIONAL_PREDICTION_EXCESS,
            "accepted_pairs": len(accepted_pairs),
        }
        return result

    def summarize(panels: list[dict[str, Any]]) -> dict[str, Any]:
        result = dict(original_summarize(panels))
        result["functional_correct"] = sum(int(item.get("functional_correct") or 0) for item in panels)
        return result

    def metric_delta(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        result = dict(original_metric_delta(reference, candidate))
        left = reference.get("metrics") or {}
        right = candidate.get("metrics") or {}
        try:
            result["functional_correct"] = float(right.get("functional_correct") or 0) - float(left.get("functional_correct") or 0)
        except (TypeError, ValueError):
            result["functional_correct"] = 0.0
        return result

    comparison._geometry_quality = geometry_quality
    comparison._evaluate_panel = evaluate_panel
    comparison._summarize = summarize
    comparison._metric_delta = metric_delta
    comparison.EVALUATION_SCHEMA_VERSION = POLICY_SCHEMA_VERSION
    comparison.AUTO_FUNCTIONAL_GT_COVERAGE = AUTO_FUNCTIONAL_GT_COVERAGE
    comparison.AUTO_FUNCTIONAL_PREDICTION_EXCESS = AUTO_FUNCTIONAL_PREDICTION_EXCESS
    comparison._auto_functional_policy_installed = True
