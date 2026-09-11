from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_detection_review_supports_shift_click_and_direct_marquee_selection() -> None:
    template = (ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html").read_text(encoding="utf-8")
    assert 'id="select-tool"' in template
    assert 'id="edit-tool"' in template
    assert 'id="selection-box"' in template
    assert "selectedIds=new Set()" in template
    assert "selectRange(row.dataset.id)" in template
    assert "e.shiftKey" in template
    assert "marquee={start:p,mode" in template
    assert "overlapRatio(area,b)>=0.18" in template
    assert "e.shiftKey||e.ctrlKey||e.metaKey" in template
    assert "e.altKey?'subtract'" in template


def test_detection_review_decisions_are_queued_per_roi_without_blocking() -> None:
    template = (ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html").read_text(encoding="utf-8")
    # These routes now live in routes_detection_review.py (split out of webui.py).
    webui = (ROOT / "application/src/isala_ocr/training/routes_detection_review.py").read_text(encoding="utf-8")
    assert "queueConcurrency=3" in template
    assert "function enqueueReviewTask" in template
    assert "function enqueueDecision" in template
    assert "candidate_id:id" in template
    assert "keepalive:true" in template
    assert '@app.post("/api/detection-review/<source_id>/<candidate_id>")' in webui
    assert '@app.post("/api/detection-review/<source_id>/complete")' in webui

def test_multi_selection_disables_geometry_editing_but_keeps_batch_review() -> None:
    template = (ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html").read_text(encoding="utf-8")
    assert 'id="dock-edit"' in template
    assert 'id="dock-save-adjusted"' in template
    assert 'id="dock-cancel-edit"' in template
    assert "selectionSize()===1" in template


def test_selection_mode_does_not_reintroduce_document_scroll_bug() -> None:
    template = (ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html").read_text(encoding="utf-8")
    assert "scrollIntoView" not in template
    assert "keepRowVisibleInCandidateList" in template
