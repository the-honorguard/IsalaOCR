from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "application/src/isala_ocr/training/templates/base.html"
FLOW = ROOT / "application/src/isala_ocr/training/static/step7-review-flow.js"
CSS = ROOT / "application/src/isala_ocr/training/static/step7-review.css"


def test_step7_review_assets_are_cache_busted_and_fullscreen_mode_is_wired():
    base = BASE.read_text(encoding="utf-8")
    flow = FLOW.read_text(encoding="utf-8")

    assert "step7-review.css',v=app_version,rev='20260817b'" in base
    assert "step7-review-flow.js',v=app_version,rev='20260817b'" in base
    assert "step7-review-focus-toggle" in flow
    assert "Review fullscreen" in flow
    assert "step7-review-focus-mode" in flow
    assert "event.key === 'Escape'" in flow


def test_step7_feedback_never_changes_document_flow():
    css = CSS.read_text(encoding="utf-8")

    assert "#comparison-inline-status" in css
    assert "position: fixed !important" in css
    assert "body:has(#comparison-issue-filter) .shell > .notice" in css
    assert "Modelmisser bevestigd" in css
