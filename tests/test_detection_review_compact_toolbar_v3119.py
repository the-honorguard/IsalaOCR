from pathlib import Path


def test_fullscreen_review_toolbar_is_collapsible_and_dockable() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "application/src/isala_ocr/training/templates/detection_review_studio.html").read_text(encoding="utf-8")
    css = (root / "application/src/isala_ocr/training/static/app.css").read_text(encoding="utf-8")
    assert 'id="review-tools-toggle"' in template
    assert 'id="review-toolbar-dock"' in template
    assert 'review-focus-tool-detail' in template
    assert "storagePrefix+'focus-tools'" in template
    assert "storagePrefix+'focus-toolbar-dock'" in template
    assert "body.review-focus-mode .review-focus-tool-detail{display:none!important}" in css
    assert "body.review-focus-mode.review-focus-tools-open .review-focus-tool-detail{display:flex!important" in css
    assert "body.review-focus-mode.review-focus-toolbar-bottom .review-studio-toolbar{top:auto;bottom:12px}" in css
