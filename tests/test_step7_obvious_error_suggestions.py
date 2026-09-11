from isala_ocr.training.table_model_comparison import (
    OBVIOUS_ERROR_HEIGHT_RATIO,
    obvious_error_suggestions,
)


def test_geometry_mismatch_flagged_by_excess_even_below_height_ratio_floor():
    # A prediction can be obviously oversized sideways instead of vertically:
    # same height as its matched 50px-wide row GT (height_ratio 1.0, nowhere
    # near the height floor), but twice as wide, reaching into a neighbour
    # column. gt_coverage is still 100% but 50% of the prediction's area
    # sits outside the GT, well past what functional_geometry_suggestions
    # would call harmless (45%) — the height-ratio check alone can never see
    # this, since it only looks at height.
    candidate = _candidate(
        ground_truth=[{"box": [0, 0, 50, 20]}],
        issues=[{
            "issue_id": "wide-but-not-tall",
            "type": "geometry",
            "prediction_box": [0, 0, 100, 20],
            "gt_boxes": [[0, 0, 50, 20]],
        }],
    )

    suggestions = obvious_error_suggestions(candidate, {})

    assert suggestions["issue_ids"] == ["wide-but-not-tall"]
    issue = suggestions["issues"][0]
    assert issue["height_ratio"] < OBVIOUS_ERROR_HEIGHT_RATIO
    assert issue["oversized_by_excess"] is True


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
    # matched one-to-one to the short 20px row GT is 32px tall: only 0.4x
    # the header's 80px, but 1.6x its own matched row. Comparing against
    # the panel's tallest cell would hide this, so it must be judged against
    # its own match instead — past the 1.5x ratio floor.
    candidate = _candidate(
        ground_truth=[{"box": [0, 0, 200, 80]}, {"box": [0, 90, 100, 110]}],
        issues=[{
            "issue_id": "row-vs-tall-header",
            "type": "geometry",
            "prediction_box": [0, 90, 100, 122],
            "gt_boxes": [[0, 90, 100, 110]],
        }],
    )

    suggestions = obvious_error_suggestions(candidate, {})

    assert suggestions["issue_ids"] == ["row-vs-tall-header"]


def test_moderately_oversized_geometry_mismatch_stays_for_review():
    # 1.2x the matched GT cell's height (and ~17% excess area) is oversized
    # but below both the 1.5x height floor and the 45% excess floor, so a
    # human still decides instead of it being auto-suggested.
    candidate = _candidate(
        ground_truth=[{"box": [0, 0, 100, 20]}],
        issues=[{
            "issue_id": "moderately-tall",
            "type": "geometry",
            "prediction_box": [0, 0, 100, 24],
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


def test_merged_cell_issue_far_taller_than_panel_gt_is_also_suggested():
    # "merged" is a description of the issue (it spans multiple GT cells),
    # not a review decision -- the reviewer still has to click something for
    # it, same as a plain oversized fp/geometry issue. A merge spanning two
    # stacked GT cells is, by construction, at least as tall as either one of
    # them, so it's an even more certain error signal than the plain case.
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

    assert suggestions["issue_ids"] == ["merged-span"]
