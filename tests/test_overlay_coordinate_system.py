from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_detection_and_roi_overlays_use_image_sized_positioning_stage() -> None:
    for name in ("document.html", "roi_review_document.html"):
        template = (
            ROOT / "application/src/isala_ocr/training/templates" / name
        ).read_text(encoding="utf-8")
        assert 'class="image-overlay-stage"' in template
        assert 'width="{{ image_width }}" height="{{ image_height }}"' in template
        image_index = template.index('<img src="/source-render/')
        overlay_index = template.index('class="overlay-box', image_index)
        stage_index = template.rindex('class="image-overlay-stage"', 0, image_index)
        stage_end = template.index('</div>', overlay_index)
        assert stage_index < image_index < overlay_index < stage_end


def test_overlay_stage_is_not_stretched_by_the_side_panel_or_scroll_viewer() -> None:
    css = (
        ROOT / "application/src/isala_ocr/training/static/app.css"
    ).read_text(encoding="utf-8")
    assert '.document-view{align-items:start}' in css
    assert '.image-viewer{align-self:start}' in css
    assert '.image-overlay-stage{position:relative;width:100%;height:auto;' in css
    assert '.image-overlay-stage>img{display:block;width:100%;height:auto;' in css
