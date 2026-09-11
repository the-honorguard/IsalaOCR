from isala_ocr.training.table_model_comparison import (
    INCOMPLETE_DETECTION_GT_COVERAGE_MAX,
    INCOMPLETE_DETECTION_PREDICTION_EXCESS_MAX,
    incomplete_detection_suggestions,
)


def _candidate(ground_truth, issues):
    return {
        "panels": [{
            "source_id": "source-a",
            "panel_id": "rv",
            "panel_name": "Right ventricle",
            "ground_truth": ground_truth,
            "issues": issues,
        }],
    }


def test_prediction_fully_inside_gt_covering_little_is_suggested():
    # Prediction [40,40,60,60] (400 area) sits fully inside GT [0,0,100,100]
    # (10000 area): zero excess, only 4% coverage.
    candidate = _candidate(
        ground_truth=[{"box": [0, 0, 100, 100]}],
        issues=[{
            "issue_id": "under-covered",
            "type": "geometry",
            "prediction_box": [40, 40, 60, 60],
            "gt_boxes": [[0, 0, 100, 100]],
        }],
    )

    suggestions = incomplete_detection_suggestions(candidate, {})

    assert suggestions["issue_ids"] == ["under-covered"]
    assert suggestions["gt_coverage_threshold"] == INCOMPLETE_DETECTION_GT_COVERAGE_MAX
    assert suggestions["prediction_excess_threshold"] == INCOMPLETE_DETECTION_PREDICTION_EXCESS_MAX


def test_fp_fn_recovered_pair_with_zero_excess_is_still_suggested():
    # Same shape as above, but marked as a recovered fp+fn pair. Zero excess
    # is a fact about the matched geometry itself, independent of how the
    # pair was recovered, so this must still surface.
    candidate = _candidate(
        ground_truth=[{"box": [0, 0, 100, 100]}],
        issues=[{
            "issue_id": "recovered-under-covered",
            "type": "geometry",
            "match_reason": "gt_coverage",
            "spatial_recovered": True,
            "prediction_box": [40, 40, 60, 60],
            "gt_boxes": [[0, 0, 100, 100]],
        }],
    )

    suggestions = incomplete_detection_suggestions(candidate, {})

    assert suggestions["issue_ids"] == ["recovered-under-covered"]


def test_prediction_with_real_excess_area_is_not_suggested():
    # Prediction overflows the GT box on one side: real excess area, so this
    # is not the clean "fully contained, just too small" case.
    candidate = _candidate(
        ground_truth=[{"box": [0, 0, 100, 100]}],
        issues=[{
            "issue_id": "spills-over",
            "type": "geometry",
            "prediction_box": [40, 40, 60, 120],
            "gt_boxes": [[0, 0, 100, 100]],
        }],
    )

    suggestions = incomplete_detection_suggestions(candidate, {})

    assert suggestions["issue_ids"] == []


def test_prediction_covering_most_of_gt_is_not_suggested():
    # 90% coverage with zero excess is a fine, mostly-complete crop, not an
    # obvious under-detection.
    candidate = _candidate(
        ground_truth=[{"box": [0, 0, 100, 100]}],
        issues=[{
            "issue_id": "mostly-covered",
            "type": "geometry",
            "prediction_box": [5, 5, 95, 95],
            "gt_boxes": [[0, 0, 100, 100]],
        }],
    )

    suggestions = incomplete_detection_suggestions(candidate, {})

    assert suggestions["issue_ids"] == []


def test_fp_and_merged_issues_are_ignored():
    # This bucket only reasons about a matched prediction/GT pair
    # (type=="geometry"); fp/fn/merged issues have no single gt_box to
    # compute coverage against.
    candidate = _candidate(
        ground_truth=[{"box": [0, 0, 100, 100]}],
        issues=[
            {"issue_id": "an-fp", "type": "fp", "prediction_box": [40, 40, 60, 60], "gt_boxes": []},
            {
                "issue_id": "a-merge", "type": "merged",
                "prediction_box": [0, 0, 100, 100],
                "gt_boxes": [[0, 0, 100, 40], [0, 60, 100, 100]],
            },
        ],
    )

    suggestions = incomplete_detection_suggestions(candidate, {})

    assert suggestions["issue_ids"] == []


def test_already_reviewed_issue_is_not_resuggested():
    candidate = _candidate(
        ground_truth=[{"box": [0, 0, 100, 100]}],
        issues=[{
            "issue_id": "already-handled",
            "type": "geometry",
            "prediction_box": [40, 40, 60, 60],
            "gt_boxes": [[0, 0, 100, 100]],
        }],
    )

    suggestions = incomplete_detection_suggestions(
        candidate, {"already-handled": {"decision": "model_error"}}
    )

    assert suggestions["issue_ids"] == []
