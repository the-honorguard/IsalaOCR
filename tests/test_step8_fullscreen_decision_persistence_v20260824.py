from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_step8_review_restores_overlay_after_decision_navigation() -> None:
    script = (
        ROOT
        / "application"
        / "src"
        / "isala_ocr"
        / "training"
        / "static"
        / "mapping-review-studio.js"
    ).read_text(encoding="utf-8")
    base = (
        ROOT
        / "application"
        / "src"
        / "isala_ocr"
        / "training"
        / "templates"
        / "base.html"
    ).read_text(encoding="utf-8")

    assert "sessionStorage" in script
    assert "rememberStudioState(true)" in script
    assert "window.setTimeout(openStudio, 0)" in script
    assert "mapping-review-studio.js',v=app_version,rev='20260824a'" in base
