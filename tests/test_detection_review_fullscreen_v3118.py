from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "application" / "src" / "isala_ocr" / "training" / "templates" / "detection_review_studio.html"
CSS = ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "app.css"


def test_reviewer_has_fullscreen_and_bidirectional_source_navigation() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert 'id="review-focus-toggle"' in text
    assert 'id="prev-source"' in text
    assert 'id="next-source"' in text
    assert "function setReviewFocusMode" in text
    assert "function adjacentSource" in text
    assert "toggleReviewFocus()" in text
    assert "e.altKey&&e.key==='ArrowRight'" in text
    assert "e.altKey&&e.key==='ArrowLeft'" in text


def test_reviewer_focus_mode_uses_floating_toolboxes_and_full_viewport() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert "v3.11.8: viewport-vullende Table Cell Review" in css
    assert "body.review-focus-mode .detection-review-layout{position:fixed;inset:0" in css
    assert "body.review-focus-mode .review-studio-toolbar{display:flex!important;position:fixed" in css
    assert "body.review-focus-mode .review-canvas-help{position:fixed" in css
    assert "body.review-focus-mode .review-selection-dock{position:fixed!important" in css
    assert "body.review-focus-mode .detection-review-side{display:flex!important;position:fixed" in css
    assert "body.review-focus-mode.review-focus-inspector-hidden .detection-review-side{display:none!important}" in css
