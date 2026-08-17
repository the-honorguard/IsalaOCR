from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_single_panel_reviewer_anchors_overlays_to_rendered_image_canvas() -> None:
    js = (ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "step7-single-panel.js").read_text(encoding="utf-8")
    css = (ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "step7-single-panel.css").read_text(encoding="utf-8")

    assert "step7-single-panel-image-canvas" in js
    assert "ensureImageCanvas" in js
    assert "fitImageCanvas" in js
    assert "stageAspectRatio" in js
    assert "imageStage.clientWidth" in js
    assert "imageStage.clientHeight" in js
    assert "unwrapImageCanvas" in js

    assert ".step7-single-panel-image-canvas" in css
    assert ".step7-single-panel-image-canvas > img" in css
    assert ".step7-single-panel-image-canvas > .compare-box" in css
    assert "position: relative" in css
    assert "object-fit: fill" in css
