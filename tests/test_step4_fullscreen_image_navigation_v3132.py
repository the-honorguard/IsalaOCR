from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html"
CSS = ROOT / "application/src/isala_ocr/training/static/app.css"


def test_step4_fullscreen_has_explicit_previous_and_next_image_buttons() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert 'id="prev-source"' in text
    assert '← Vorige afbeelding' in text
    assert 'id="next-source-top"' in text
    assert 'Volgende afbeelding →' in text
    assert "nextSourceTopButton=document.getElementById('next-source-top')" in text
    assert "nextSourceTopButton.onclick=()=>navigateSource(nextSource())" in text
    assert "e.altKey&&e.key==='ArrowRight'" in text
    assert "e.altKey&&e.key==='ArrowLeft'" in text


def test_fullscreen_navigation_buttons_remain_visible_when_tools_are_collapsed() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert "v3.13.2: explicit previous/next image navigation" in css
    assert "body.review-focus-mode .review-image-nav{display:inline-flex" in css
