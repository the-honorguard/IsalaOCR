from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_step7_review_flow_is_loaded_globally():
    base = _read("application/src/isala_ocr/training/templates/base.html")
    assert "step7-review-flow.js" in base


def test_step7_reviews_hide_optimistically_and_queue_the_save():
    # No more rollback on the first network hiccup: the save is queued through
    # the shared IsalaReviewQueue (review-queue.js), which retries with backoff
    # and only surfaces a definitive failure + "Opnieuw" after 3 attempts --
    # see refactor-phase2-remaining-plan.md, punt 1.
    script = _read("application/src/isala_ocr/training/static/step7-review-flow.js")
    assert "event.stopImmediatePropagation()" in script
    assert "hideOptimistically(row, optimisticDecision)" in script
    assert "row.style.display = decision === 'clear' || decision === 'deferred' ? '' : 'none'" in script
    assert "IsalaReviewQueue.createTaskQueue" in script
    assert "issueQueue.enqueue(" in script
    assert "setStatusRetryable(" in script
    assert "applyServerCounts(payload)" in script


def test_gt_check_redirects_directly_to_source_studio():
    script = _read("application/src/isala_ocr/training/static/step7-review-flow.js")
    assert "savedDecision === 'gt_check'" in script
    assert "sourceHrefForRow(row)" in script
    assert "window.location.assign" in script
    assert "from_step7=1" in script


def test_gt_management_surfaces_step7_gt_checks():
    script = _read("application/src/isala_ocr/training/static/step7-review-flow.js")
    assert ".comparison-issue-row[data-issue-decision=\"gt_check\"]" in script
    assert "step7-gt-check-summary" in script
    assert "step7-gt-check-worklist" in script
    assert "GT controleren:" in script
    assert "GT openen · ${items.length} gemarkeerd" in script
