from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "step7-review-flow.js"


def test_step7_review_flow_preserves_viewport_during_optimistic_removal():
    source = FLOW.read_text(encoding="utf-8")

    assert "overflow-anchor:none" in source
    assert "captureViewportAnchor" in source
    assert "restoreViewportAnchor" in source
    assert "const viewportSnapshot = captureViewportAnchor(row);" in source
    assert "hideOptimistically(row, optimisticDecision);" in source
    assert "restoreViewportAnchor(viewportSnapshot);" in source
    assert "window.scrollBy(0, delta);" in source


def test_step7_status_feedback_cannot_shift_review_layout():
    source = FLOW.read_text(encoding="utf-8")

    assert "#comparison-inline-status{position:fixed" in source
    assert "#comparison-inline-status:empty{display:none}" in source
