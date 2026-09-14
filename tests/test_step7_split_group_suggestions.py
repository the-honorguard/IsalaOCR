from isala_ocr.training.table_model_comparison import _evaluate_panel, split_group_suggestions


def _panel(*gt_boxes):
    return {
        "source_id": "source-a",
        "panel_id": "rv",
        "panel_name": "Right ventricle Volume Result",
        "split": "train",
        "file_name": "source-a__rv.png",
        "panel_box": [0, 0, 320, 140],
        "width": 320,
        "height": 140,
        "ground_truth": [
            {"gt_id": f"gt-{index}", "box": box}
            for index, box in enumerate(gt_boxes, start=1)
        ],
    }


def _fn(issue_id, gt_box):
    return {"type": "fn", "issue_id": issue_id, "gt_boxes": [list(gt_box)]}


def _fp(issue_id, prediction_box):
    return {"type": "fp", "issue_id": issue_id, "prediction_box": list(prediction_box)}


def test_low_coverage_split_pair_is_suggested_as_one_group_end_to_end():
    # Two non-overlapping predictions that uniquely row-align with one GT cell,
    # but together cover only 25% of it -- too little for the auto-recovery
    # pass's 85% floor, so it stays open as 2 FP + 1 FN. It is still always a
    # model mistake (the model never produced one correct box for this cell),
    # so it belongs in the manual bulk-suggestion bucket. Exercised through the
    # real evaluator (not hand-built issues) to prove the two functions agree
    # on what "still open" looks like.
    panel = _panel([0, 0, 200, 20])
    predictions = [
        {"prediction_id": "left", "box": [0, 0, 50, 20], "confidence": 0.9},
        {"prediction_id": "right", "box": [150, 0, 200, 20], "confidence": 0.9},
    ]
    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)
    assert result.get("split_recovered", 0) == 0
    assert sorted(issue["type"] for issue in result["issues"]) == ["fn", "fp", "fp"]

    candidate = {"panels": [{**panel, "issues": result["issues"]}]}
    suggestions = split_group_suggestions(candidate, {})

    assert len(suggestions["issues"]) == 1
    group = suggestions["issues"][0]
    assert group["group_size"] == 3
    assert len(group["fp_issue_ids"]) == 2
    assert sorted(suggestions["issue_ids"]) == sorted(group["issue_ids"])


def test_mutually_overlapping_duplicate_predictions_are_still_grouped():
    # Whether the two FPs also overlap *each other* is irrelevant to this
    # bucket (that mutual-overlap check only decides whether the separate
    # auto-recovery pass may silently declare them a single clean TP): two
    # detections landing on one GT cell is a model mistake either way.
    panel = {"panels": [{
        **_panel([0, 0, 200, 20]),
        "issues": [
            _fn("fn-1", [0, 0, 200, 20]),
            _fp("fp-a", [0, 0, 150, 20]),
            _fp("fp-b", [30, 0, 200, 20]),
        ],
    }]}

    suggestions = split_group_suggestions(panel, {})

    assert len(suggestions["issues"]) == 1
    group = suggestions["issues"][0]
    assert group["issue_id"] == "fn-1"
    assert sorted(group["fp_issue_ids"]) == ["fp-a", "fp-b"]
    assert group["group_size"] == 3


def test_ambiguous_prediction_across_two_gt_cells_is_not_suggested():
    # "middle" row-aligns with both GT cells well enough to be a candidate for
    # either -- same ambiguity the auto-recovery pass declines on. With only
    # one FP total there is nothing to group anyway (a group needs 2+), so
    # this should produce no suggestions.
    panel = _panel([20, 40, 120, 80], [100, 40, 200, 80])
    predictions = [{"prediction_id": "ambiguous-middle", "box": [60, 40, 160, 80], "confidence": 0.91}]
    result = _evaluate_panel(panel, predictions, iou_threshold=0.50, geometry_iou=0.75)
    assert sorted(issue["type"] for issue in result["issues"]) == ["fn", "fn", "fp"]

    candidate = {"panels": [{**panel, "issues": result["issues"]}]}
    suggestions = split_group_suggestions(candidate, {})

    assert suggestions["issues"] == []
    assert suggestions["issue_ids"] == []


def test_fp_that_row_aligns_with_two_open_fns_blocks_both_groups():
    # "middle" plausibly belongs to either FN cell (unique-in-both-directions
    # rule): grouping it with one would be a guess, so neither group forms,
    # even though each FN otherwise has 2+ row-aligned FPs.
    panel = {"panels": [{
        **_panel([0, 0, 90, 20], [110, 0, 200, 20]),
        "issues": [
            _fn("fn-left", [0, 0, 90, 20]),
            _fn("fn-right", [110, 0, 200, 20]),
            _fp("fp-left-only", [0, 0, 40, 20]),
            _fp("fp-right-only", [150, 0, 200, 20]),
            _fp("fp-middle", [40, 0, 150, 20]),
        ],
    }]}

    suggestions = split_group_suggestions(panel, {})

    assert suggestions["issues"] == []


def test_already_reviewed_split_issue_is_excluded():
    panel = {"panels": [{
        **_panel([0, 0, 200, 20]),
        "issues": [
            _fn("fn-1", [0, 0, 200, 20]),
            _fp("fp-a", [0, 0, 50, 20]),
            _fp("fp-b", [150, 0, 200, 20]),
        ],
    }]}

    reviews = {"fn-1": {"decision": "model_error"}}
    suggestions = split_group_suggestions(panel, reviews)

    assert suggestions["issues"] == []
    assert suggestions["issue_ids"] == []


def test_group_size_over_cap_is_not_suggested():
    from isala_ocr.training.table_model_evaluation_policy import SPLIT_RECOVERY_MAX_GROUP_SIZE

    fp_count = SPLIT_RECOVERY_MAX_GROUP_SIZE + 1
    width = 400
    slice_width = width // fp_count
    issues = [_fn("fn-1", [0, 0, width, 20])] + [
        _fp(f"fp-{index}", [index * slice_width, 0, (index + 1) * slice_width, 20])
        for index in range(fp_count)
    ]
    panel = {"panels": [{**_panel([0, 0, width, 20]), "issues": issues}]}

    suggestions = split_group_suggestions(panel, {})

    assert suggestions["issues"] == []
