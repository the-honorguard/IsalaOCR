from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _template() -> str:
    return (ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html").read_text(encoding="utf-8")


def _css() -> str:
    return (ROOT / "application/src/isala_ocr/training/static/app.css").read_text(encoding="utf-8")


def test_detection_review_has_zoom_pan_and_fullscreen_controls() -> None:
    template = _template()
    css = _css()
    for control in ("review-viewport", "zoom-fit", "zoom-out", "zoom-level", "zoom-in", "zoom-one", "zoom-selection", "zoom-fullscreen"):
        assert f'id="{control}"' in template
    assert "function applyZoom" in template
    assert "function naturalZoom" in template
    assert "function focusSelection" in template
    assert "viewport.addEventListener('wheel'" in template
    assert "spaceDown" in template and "IsalaViewportPan.createDragPan" in template
    assert ".detection-review-viewport" in css
    assert ":fullscreen" in css


def test_zoom_keeps_source_coordinate_mapping_stage_relative() -> None:
    template = _template()
    assert "stage.getBoundingClientRect()" in template
    assert "(e.clientX-r.left)/r.width*W" in template
    assert "stage.style.width=(zoom*100)+'%'" in template


def test_review_mutations_use_nonblocking_per_roi_queue() -> None:
    template = _template()
    css = _css()
    assert 'id="review-queue-status"' in template
    assert "queueConcurrency=3" in template
    assert "function enqueueReviewTask" in template
    assert "kind:'candidate'" in template
    assert "candidate_id:id" in template
    assert "keepalive:true" in template
    assert "function pumpReviewQueue" in template
    assert ".review-queue-status" in css
    assert ".review-queued" in css
