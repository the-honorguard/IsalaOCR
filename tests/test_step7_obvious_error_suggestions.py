from isala_ocr.training.table_model_comparison import (
    OBVIOUS_ERROR_HEIGHT_RATIO,
    obvious_error_suggestions,
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


def test_extra_detection_far_taller_than_panel_gt_is_suggested():
    # Tallest GT cell in the panel is 20px high; the stray detection is 45px,
    # well past the 2x ratio, so it should surface as an obvious error.
    candidate = _candidate(
        ground_truth=[{"box": [0, 0, 100, 20]}, {"box": [0, 30, 100, 50]}],
        issues=[{
            "issue_id": "too-tall-fp",
            "type": "fp",
            "prediction_box": [0, 60, 100, 105],
            "gt_boxes": [],
        }],
    )

    suggestions = obvious_error_suggestions(candidate, {})

    assert suggestions["issue_ids"] == ["too-tall-fp"]
    assert suggestions["height_ratio_threshold"] == OBVIOUS_ERROR_HEIGHT_RATIO


def test_geometry_mismatch_compared_to_its_own_matched_gt_not_panel_max():
    # The panel also has a tall merged header cell (80px). A row prediction
    # matched one-to-one to the short 20px row GT is 45px tall: only 0.56x
    # the header's 80px, but 2.25x its own matched row. Comparing against
    # the panel's tallest cell would hide this, so it must be judged against
    # its own match instead — well past the ratio floor.
    candidate = _candidate(
        ground_truth=[{"box": [0, 0, 200, 80]}, {"box": [0, 90, 100, 110]}],
        issues=[{
            "issue_id": "row-vs-tall-header",
            "type": "geometry",
            "prediction_box": [0, 90, 100, 135],
            "gt_boxes": [[0, 90, 100, 110]],
        }],
    )

    suggestions = obvious_error_suggestions(candidate, {})

    assert suggestions["issue_ids"] == ["row-vs-tall-header"]


def test_moderately_oversized_geometry_mismatch_stays_for_review():
    # 1.5x the tallest GT cell is oversized but below the 2x floor, so a
    # human still decides instead of it being auto-suggested.
    candidate = _candidate(
        ground_truth=[{"box": [0, 0, 100, 20]}],
        issues=[{
            "issue_id": "moderately-tall",
            "type": "geometry",
            "prediction_box": [0, 0, 100, 30],
            "gt_boxes": [[0, 0, 100, 20]],
        }],
    )

    suggestions = obvious_error_suggestions(candidate, {})

    assert suggestions["issue_ids"] == []


def test_already_reviewed_issue_is_not_resuggested():
    candidate = _candidate(
        ground_truth=[{"box": [0, 0, 100, 20]}],
        issues=[{
            "issue_id": "already-handled",
            "type": "fp",
            "prediction_box": [0, 0, 100, 50],
            "gt_boxes": [],
        }],
    )

    suggestions = obvious_error_suggestions(
        candidate, {"already-handled": {"decision": "model_error"}}
    )

    assert suggestions["issue_ids"] == []


def test_merged_cell_issues_are_never_flagged():
    # A prediction spanning two real GT cells is legitimate merge territory,
    # already classified separately upstream; it must not double up here.
    candidate = _candidate(
        ground_truth=[{"box": [0, 0, 100, 20]}, {"box": [0, 30, 100, 50]}],
        issues=[{
            "issue_id": "merged-span",
            "type": "merged",
            "prediction_box": [0, 0, 100, 50],
            "gt_boxes": [[0, 0, 100, 20], [0, 30, 100, 50]],
        }],
    )

    suggestions = obvious_error_suggestions(candidate, {})

    assert suggestions["issue_ids"] == []
