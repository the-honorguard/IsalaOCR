from __future__ import annotations

from typing import Any

# Step 7 is a functional crop review, not a pixel-perfect box reproduction test.
# These bounds intentionally apply only after the existing evaluator has made a
# one-to-one prediction/GT match. Containment recovery itself keeps its stricter
# 95% threshold in table_model_comparison.py, and merged-cell classification is
# evaluated before this policy can accept anything.
AUTO_FUNCTIONAL_GT_COVERAGE = 0.92
AUTO_FUNCTIONAL_PREDICTION_EXCESS = 0.30

# A second, conservative recovery pass joins an otherwise separate FP + FN when
# both boxes clearly describe the same row/cell region but missed the stricter
# IoU/containment rules. Recovery is only allowed for a unique one-to-one pair;
# ambiguous predictions that overlap multiple GT cells remain FP/FN for review.
SPATIAL_RECOVERY_MIN_VERTICAL_OVERLAP = 0.82
SPATIAL_RECOVERY_MIN_HORIZONTAL_OVERLAP = 0.45
SPATIAL_RECOVERY_MIN_AREA_RATIO = 0.10

# A third pass covers the case the 1:1 pass explicitly declines: the model
# split one GT cell's content into several separate detections (e.g. a
# multi-word label detected as two boxes) instead of one whole match. Each
# of those predictions is individually an FP and the GT cell an FN, so this
# used to surface as N+1 separate open issues -- and N+1 separate manual
# "Model fout" clicks -- for what is really one mistake. Recovery requires
# every FP in the group to row-align with exactly one FN (an FP that
# plausibly belongs to two different FNs makes the grouping ambiguous, so
# neither FN is touched), caps the group size, AND requires the group to be
# genuinely complementary: the individual predictions must not
# substantially overlap each other (two redundant, mostly-overlapping wide
# guesses at the same region are not "split pieces" of one cell, and must
# stay open for review, not get silently combined), and together must cover
# most of the GT cell -- not just span its width with gaps in between. Both
# conditions are needed: coverage alone can't tell two complementary
# non-overlapping pieces apart from two overlapping near-duplicates that
# both happen to reach across the same GT box (their union bbox would
# "cover" it too, without either fact meaning the group is safe to merge).
SPLIT_RECOVERY_MAX_GROUP_SIZE = 3
SPLIT_RECOVERY_MAX_MUTUAL_OVERLAP = 0.05
SPLIT_RECOVERY_MIN_COMBINED_GT_COVERAGE = 0.85

POLICY_SCHEMA_VERSION = 8


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

    def recover_spatial_fp_fn_pairs(
        panel: dict[str, Any],
        predictions: list[dict[str, Any]],
        result: dict[str, Any],
    ) -> int:
        """Turn unique same-cell FP+FN pairs into one geometry issue.

        The base matcher intentionally stays strict. This pass only addresses the
        review-noise case where a prediction and GT cell have strong row overlap
        and meaningful horizontal overlap, yet IoU/containment did not match.
        Requiring uniqueness in both directions prevents broad predictions or
        multiple partial predictions from being silently paired.
        """
        issues = [item for item in (result.get("issues") or []) if isinstance(item, dict)]
        fp_issues = [item for item in issues if str(item.get("type") or "") == "fp"]
        fn_issues = [item for item in issues if str(item.get("type") or "") == "fn"]
        if not fp_issues or not fn_issues:
            return 0

        truth = panel.get("ground_truth") or []
        candidates: list[dict[str, Any]] = []

        for fp_issue in fp_issues:
            pred_box = comparison._box(fp_issue.get("prediction_box"))
            if pred_box is None:
                continue
            prediction_indexes = [
                index
                for index, prediction in enumerate(predictions)
                if isinstance(prediction, dict)
                and comparison._box(prediction.get("box")) == pred_box
            ]
            if len(prediction_indexes) != 1:
                continue
            pred_index = prediction_indexes[0]

            for fn_issue in fn_issues:
                gt_boxes = fn_issue.get("gt_boxes") or []
                gt_box = (
                    comparison._box(gt_boxes[0])
                    if isinstance(gt_boxes, list) and len(gt_boxes) == 1
                    else None
                )
                if gt_box is None:
                    continue
                gt_indexes = [
                    index
                    for index, gt in enumerate(truth)
                    if isinstance(gt, dict) and comparison._box(gt.get("box")) == gt_box
                ]
                if len(gt_indexes) != 1:
                    continue
                gt_index = gt_indexes[0]

                vertical = comparison._axis_overlap_fraction_of_smaller(pred_box, gt_box, axis="y")
                horizontal = comparison._axis_overlap_fraction_of_smaller(pred_box, gt_box, axis="x")
                area_ratio = min(comparison._box_area(pred_box), comparison._box_area(gt_box)) / max(
                    comparison._box_area(pred_box), comparison._box_area(gt_box)
                )
                if vertical < SPATIAL_RECOVERY_MIN_VERTICAL_OVERLAP:
                    continue
                if horizontal < SPATIAL_RECOVERY_MIN_HORIZONTAL_OVERLAP:
                    continue
                if area_ratio < SPATIAL_RECOVERY_MIN_AREA_RATIO:
                    continue

                candidates.append({
                    "fp": fp_issue,
                    "fn": fn_issue,
                    "prediction_index": pred_index,
                    "gt_index": gt_index,
                    "prediction_box": pred_box,
                    "gt_box": gt_box,
                    "vertical": vertical,
                    "horizontal": horizontal,
                    "area_ratio": area_ratio,
                })

        if not candidates:
            return 0

        fp_counts: dict[str, int] = {}
        fn_counts: dict[str, int] = {}
        for candidate in candidates:
            fp_id = str(candidate["fp"].get("issue_id") or "")
            fn_id = str(candidate["fn"].get("issue_id") or "")
            fp_counts[fp_id] = fp_counts.get(fp_id, 0) + 1
            fn_counts[fn_id] = fn_counts.get(fn_id, 0) + 1

        recovered: list[dict[str, Any]] = []
        consumed_issue_ids: set[str] = set()
        panel_key = f"{panel.get('source_id')}::{panel.get('panel_id')}"

        for candidate in candidates:
            fp_issue = candidate["fp"]
            fn_issue = candidate["fn"]
            fp_id = str(fp_issue.get("issue_id") or "")
            fn_id = str(fn_issue.get("issue_id") or "")
            if not fp_id or not fn_id:
                continue
            if fp_counts.get(fp_id) != 1 or fn_counts.get(fn_id) != 1:
                continue
            if fp_id in consumed_issue_ids or fn_id in consumed_issue_ids:
                continue

            pred_box = candidate["prediction_box"]
            gt_box = candidate["gt_box"]
            gt_raw = (fn_issue.get("gt_boxes") or [None])[0]
            quality = geometry_quality(pred_box, gt_box)
            new_issue: dict[str, Any] = {
                "type": "geometry",
                "label": "Geometrie afwijkend",
                "prediction_box": fp_issue.get("prediction_box"),
                "gt_boxes": [gt_raw],
                "confidence": fp_issue.get("confidence", 0.0),
                "iou": comparison._iou(pred_box, gt_box),
                "match_reason": "spatial_recovery",
                "spatial_recovered": True,
                "legacy_issue_ids": [fp_id, fn_id],
                "source_id": panel.get("source_id"),
                "panel_id": panel.get("panel_id"),
                "panel_name": panel.get("panel_name"),
                "file_name": panel.get("file_name"),
                "width": panel.get("width"),
                "height": panel.get("height"),
                "split": panel.get("split"),
                **quality,
            }
            new_issue["issue_id"] = comparison._issue_identifier(panel_key, new_issue)
            recovered.append(new_issue)
            consumed_issue_ids.update({fp_id, fn_id})

            result.setdefault("matches", []).append({
                "prediction_index": candidate["prediction_index"],
                "gt_index": candidate["gt_index"],
                "iou": new_issue["iou"],
                "match_reason": "spatial_recovery",
                "spatial_recovered": True,
                "match_vertical_overlap": candidate["vertical"],
                "match_horizontal_overlap": candidate["horizontal"],
                "match_area_ratio": candidate["area_ratio"],
            })

        if not recovered:
            return 0

        result["issues"] = [
            issue
            for issue in issues
            if str(issue.get("issue_id") or "") not in consumed_issue_ids
        ] + recovered
        count = len(recovered)
        result["tp"] = int(result.get("tp") or 0) + count
        result["fp"] = max(0, int(result.get("fp") or 0) - count)
        result["fn"] = max(0, int(result.get("fn") or 0) - count)
        result["geometry_mismatch"] = int(result.get("geometry_mismatch") or 0) + count
        result["spatial_recovered"] = count
        return count

    def recover_split_prediction_fn_groups(
        panel: dict[str, Any],
        predictions: list[dict[str, Any]],
        result: dict[str, Any],
    ) -> int:
        """Turn a uniquely-matched group of split predictions + one FN into one geometry issue.

        Runs after recover_spatial_fp_fn_pairs, on whatever fp/fn issues that
        pass left open (the 1:1 pass already claims the cases it can). This
        pass only fires when *every* candidate FP row-aligns with exactly
        one FN and no other -- an FP that plausibly belongs to two FNs
        leaves the whole ambiguous group alone, same spirit as the 1:1
        pass's "unique in both directions" rule, just generalised to a
        many-to-one match.
        """
        issues = [item for item in (result.get("issues") or []) if isinstance(item, dict)]
        fp_issues = [item for item in issues if str(item.get("type") or "") == "fp"]
        fn_issues = [item for item in issues if str(item.get("type") or "") == "fn"]
        if len(fp_issues) < 2 or not fn_issues:
            return 0

        truth = panel.get("ground_truth") or []

        def _resolve_fp(fp_issue: dict[str, Any]) -> tuple[int, tuple[float, ...]] | None:
            pred_box = comparison._box(fp_issue.get("prediction_box"))
            if pred_box is None:
                return None
            prediction_indexes = [
                index
                for index, prediction in enumerate(predictions)
                if isinstance(prediction, dict) and comparison._box(prediction.get("box")) == pred_box
            ]
            if len(prediction_indexes) != 1:
                return None
            return prediction_indexes[0], pred_box

        def _resolve_fn(fn_issue: dict[str, Any]) -> tuple[int, tuple[float, ...]] | None:
            gt_boxes = fn_issue.get("gt_boxes") or []
            gt_box = (
                comparison._box(gt_boxes[0])
                if isinstance(gt_boxes, list) and len(gt_boxes) == 1
                else None
            )
            if gt_box is None:
                return None
            gt_indexes = [
                index
                for index, gt in enumerate(truth)
                if isinstance(gt, dict) and comparison._box(gt.get("box")) == gt_box
            ]
            if len(gt_indexes) != 1:
                return None
            return gt_indexes[0], gt_box

        fp_resolved: dict[str, tuple[dict[str, Any], int, tuple[float, ...]]] = {}
        for fp_issue in fp_issues:
            resolved = _resolve_fp(fp_issue)
            if resolved is not None:
                fp_id = str(fp_issue.get("issue_id") or "")
                if fp_id:
                    fp_resolved[fp_id] = (fp_issue, resolved[0], resolved[1])

        fn_resolved: dict[str, tuple[dict[str, Any], int, tuple[float, ...]]] = {}
        for fn_issue in fn_issues:
            resolved = _resolve_fn(fn_issue)
            if resolved is not None:
                fn_id = str(fn_issue.get("issue_id") or "")
                if fn_id:
                    fn_resolved[fn_id] = (fn_issue, resolved[0], resolved[1])

        if len(fp_resolved) < 2 or not fn_resolved:
            return 0

        # Loose per-FP gate: strong row overlap plus *some* horizontal
        # relation to the FN's cell. The real gate is the group-level check
        # below, done on the union of the group's boxes.
        fp_candidates_per_fn: dict[str, list[str]] = {}
        for fn_id, (_fn_issue, _gt_index, gt_box) in fn_resolved.items():
            matching_fp_ids = []
            for fp_id, (_fp_issue, _pred_index, pred_box) in fp_resolved.items():
                vertical = comparison._axis_overlap_fraction_of_smaller(pred_box, gt_box, axis="y")
                if vertical < SPATIAL_RECOVERY_MIN_VERTICAL_OVERLAP:
                    continue
                horizontal = comparison._axis_overlap_fraction_of_smaller(pred_box, gt_box, axis="x")
                if horizontal <= 0:
                    continue
                matching_fp_ids.append(fp_id)
            if 2 <= len(matching_fp_ids) <= SPLIT_RECOVERY_MAX_GROUP_SIZE:
                fp_candidates_per_fn[fn_id] = matching_fp_ids

        if not fp_candidates_per_fn:
            return 0

        # An FP that row-aligns with more than one FN makes every group it
        # appears in ambiguous; drop those groups rather than guess.
        fp_to_fns: dict[str, set[str]] = {}
        for fn_id, fp_ids in fp_candidates_per_fn.items():
            for fp_id in fp_ids:
                fp_to_fns.setdefault(fp_id, set()).add(fn_id)

        recovered: list[dict[str, Any]] = []
        consumed_issue_ids: set[str] = set()
        panel_key = f"{panel.get('source_id')}::{panel.get('panel_id')}"

        for fn_id, fp_ids in fp_candidates_per_fn.items():
            if fn_id in consumed_issue_ids or any(fp_id in consumed_issue_ids for fp_id in fp_ids):
                continue
            if any(len(fp_to_fns.get(fp_id, ())) != 1 for fp_id in fp_ids):
                continue

            fn_issue, _gt_index, gt_box = fn_resolved[fn_id]
            group_boxes = [fp_resolved[fp_id][2] for fp_id in fp_ids]

            # Reject two redundant, mostly-overlapping guesses at the same
            # region -- those are not complementary "split" pieces of one
            # cell, whatever their union happens to cover.
            too_overlapping = False
            for i in range(len(group_boxes)):
                for j in range(i + 1, len(group_boxes)):
                    left, right = group_boxes[i], group_boxes[j]
                    ix1, iy1 = max(left[0], right[0]), max(left[1], right[1])
                    ix2, iy2 = min(left[2], right[2]), min(left[3], right[3])
                    overlap_area = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
                    smaller_area = min(comparison._box_area(left), comparison._box_area(right))
                    if overlap_area / smaller_area > SPLIT_RECOVERY_MAX_MUTUAL_OVERLAP:
                        too_overlapping = True
                        break
                if too_overlapping:
                    break
            if too_overlapping:
                continue

            union_box = (
                min(box[0] for box in group_boxes),
                min(box[1] for box in group_boxes),
                max(box[2] for box in group_boxes),
                max(box[3] for box in group_boxes),
            )
            # Exact GT coverage: since the group's boxes don't (meaningfully)
            # overlap each other, summing each one's area clipped to the GT
            # box double-counts nothing, unlike measuring the union
            # *bounding box*'s extent, which would silently count any gap
            # between the pieces as "covered" just because it sits inside
            # the box that bounds all of them.
            gt_area = comparison._box_area(gt_box)
            covered_area = 0.0
            for box in group_boxes:
                ix1, iy1 = max(box[0], gt_box[0]), max(box[1], gt_box[1])
                ix2, iy2 = min(box[2], gt_box[2]), min(box[3], gt_box[3])
                covered_area += max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
            gt_coverage_of_group = covered_area / gt_area
            if gt_coverage_of_group < SPLIT_RECOVERY_MIN_COMBINED_GT_COVERAGE:
                continue

            quality = geometry_quality(union_box, gt_box)
            gt_raw = (fn_issue.get("gt_boxes") or [None])[0]
            confidences = [float(fp_resolved[fp_id][0].get("confidence") or 0.0) for fp_id in fp_ids]
            new_issue: dict[str, Any] = {
                "type": "geometry",
                "label": "Geometrie afwijkend",
                "prediction_box": list(union_box),
                "gt_boxes": [gt_raw],
                "confidence": min(confidences) if confidences else 0.0,
                "iou": comparison._iou(union_box, gt_box),
                "match_reason": "spatial_recovery_split",
                "spatial_recovered": True,
                "legacy_issue_ids": [*fp_ids, fn_id],
                "source_id": panel.get("source_id"),
                "panel_id": panel.get("panel_id"),
                "panel_name": panel.get("panel_name"),
                "file_name": panel.get("file_name"),
                "width": panel.get("width"),
                "height": panel.get("height"),
                "split": panel.get("split"),
                **quality,
            }
            new_issue["issue_id"] = comparison._issue_identifier(panel_key, new_issue)
            recovered.append({**new_issue, "_group_size": len(fp_ids)})
            consumed_issue_ids.update(fp_ids)
            consumed_issue_ids.add(fn_id)

        if not recovered:
            return 0

        removed_fp_count = sum(int(item.pop("_group_size")) for item in recovered)
        result["issues"] = [
            issue
            for issue in issues
            if str(issue.get("issue_id") or "") not in consumed_issue_ids
        ] + recovered
        count = len(recovered)
        result["tp"] = int(result.get("tp") or 0) + count
        result["fp"] = max(0, int(result.get("fp") or 0) - removed_fp_count)
        result["fn"] = max(0, int(result.get("fn") or 0) - count)
        result["geometry_mismatch"] = int(result.get("geometry_mismatch") or 0) + count
        result["split_recovered"] = count
        return count

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

        recover_spatial_fp_fn_pairs(panel, predictions, result)
        recover_split_prediction_fn_groups(panel, predictions, result)

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

        # The base evaluator never turns a high-IoU match (>= geometry_iou) into
        # a "geometry" issue at all, so the neighbour-centre safeguard below
        # never gets a chance to see it. A wide crop can clear the IoU bar and
        # still reach into a neighbouring logical cell; demote those matches to
        # a reviewable geometry issue before the accept/reject pass below runs.
        panel_key = f"{panel.get('source_id')}::{panel.get('panel_id')}"
        demoted = 0
        for match in result.get("matches") or []:
            if float(match.get("iou") or 0.0) < geometry_iou:
                continue  # already handled as an issue by the base evaluator
            try:
                pred_index = int(match.get("prediction_index"))
                gt_index = int(match.get("gt_index"))
            except (TypeError, ValueError):
                continue
            if not (0 <= pred_index < len(predictions)) or not (0 <= gt_index < len(truth)):
                continue
            pred = predictions[pred_index]
            gt = truth[gt_index]
            if tuple(pred.get("box") or []) in merged_prediction_boxes:
                continue
            prediction_box = comparison._box(pred.get("box"))
            gt_box = comparison._box(gt.get("box"))
            if prediction_box is None or gt_box is None:
                continue
            reaches_other_cell = False
            for other_index, other_gt in enumerate(truth):
                if other_index == gt_index or not isinstance(other_gt, dict):
                    continue
                other_box = comparison._box(other_gt.get("box"))
                if other_box is None:
                    continue
                if not comparison._gt_boxes_are_spatially_distinct(gt_box, other_box):
                    continue
                if comparison._box_center_inside(other_box, prediction_box):
                    reaches_other_cell = True
                    break
            if not reaches_other_cell:
                continue
            quality = geometry_quality(prediction_box, gt_box)
            issue = {
                "type": "geometry",
                "label": "Geometrie afwijkend",
                "prediction_box": pred.get("box"),
                "gt_boxes": [gt.get("box")],
                "confidence": pred.get("confidence", 0.0),
                "iou": float(match.get("iou") or 0.0),
                "match_reason": match.get("match_reason") or "iou",
                **quality,
            }
            issue["issue_id"] = comparison._issue_identifier(panel_key, issue)
            issue["source_id"] = panel.get("source_id")
            issue["panel_id"] = panel.get("panel_id")
            issue["panel_name"] = panel.get("panel_name")
            issue["file_name"] = panel.get("file_name")
            issue["width"] = panel.get("width")
            issue["height"] = panel.get("height")
            issue["split"] = panel.get("split")
            result.setdefault("issues", [])
            result["issues"].append(issue)
            demoted += 1
        if demoted:
            result["direct_correct"] = max(0, int(result.get("direct_correct") or 0) - demoted)
            result["geometry_mismatch"] = int(result.get("geometry_mismatch") or 0) + demoted

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

            # Geometry issues are only auto-accepted when they can be traced back
            # to exactly one evaluator match record.
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
                    if matched_pair is not None:
                        matched_pair = None
                        matched_record = None
                        break
                    matched_pair = (pred_index, gt_index)
                    matched_record = match

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
            "spatial_recovery_vertical": SPATIAL_RECOVERY_MIN_VERTICAL_OVERLAP,
            "spatial_recovery_horizontal": SPATIAL_RECOVERY_MIN_HORIZONTAL_OVERLAP,
            "spatial_recovery_area_ratio": SPATIAL_RECOVERY_MIN_AREA_RATIO,
            "accepted_pairs": len(accepted_pairs),
        }
        return result

    def summarize(panels: list[dict[str, Any]]) -> dict[str, Any]:
        result = dict(original_summarize(panels))
        result["functional_correct"] = sum(int(item.get("functional_correct") or 0) for item in panels)
        result["spatial_recovered"] = sum(int(item.get("spatial_recovered") or 0) for item in panels)
        result["split_recovered"] = sum(int(item.get("split_recovered") or 0) for item in panels)
        return result

    def metric_delta(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        result = dict(original_metric_delta(reference, candidate))
        left = reference.get("metrics") or {}
        right = candidate.get("metrics") or {}
        for key in ("functional_correct", "spatial_recovered", "split_recovered"):
            try:
                result[key] = float(right.get(key) or 0) - float(left.get(key) or 0)
            except (TypeError, ValueError):
                result[key] = 0.0
        return result

    comparison._geometry_quality = geometry_quality
    comparison._evaluate_panel = evaluate_panel
    comparison._summarize = summarize
    comparison._metric_delta = metric_delta
    comparison.EVALUATION_SCHEMA_VERSION = POLICY_SCHEMA_VERSION
    comparison.AUTO_FUNCTIONAL_GT_COVERAGE = AUTO_FUNCTIONAL_GT_COVERAGE
    comparison.AUTO_FUNCTIONAL_PREDICTION_EXCESS = AUTO_FUNCTIONAL_PREDICTION_EXCESS
    comparison.SPATIAL_RECOVERY_MIN_VERTICAL_OVERLAP = SPATIAL_RECOVERY_MIN_VERTICAL_OVERLAP
    comparison.SPATIAL_RECOVERY_MIN_HORIZONTAL_OVERLAP = SPATIAL_RECOVERY_MIN_HORIZONTAL_OVERLAP
    comparison.SPATIAL_RECOVERY_MIN_AREA_RATIO = SPATIAL_RECOVERY_MIN_AREA_RATIO
    comparison._auto_functional_policy_installed = True
