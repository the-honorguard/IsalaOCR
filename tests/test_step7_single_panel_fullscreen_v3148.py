from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_step7_single_panel_assets_are_loaded() -> None:
    base = (ROOT / "application" / "src" / "isala_ocr" / "training" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "step7-single-panel.css" in base
    assert "step7-single-panel.js" in base


def test_step7_fullscreen_is_single_panel_studio() -> None:
    static = ROOT / "application" / "src" / "isala_ocr" / "training" / "static"
    script = (static / "step7-single-panel.js").read_text(encoding="utf-8")
    style = (static / "step7-single-panel.css").read_text(encoding="utf-8")

    assert "step7-single-panel-active" in script
    assert "movePanel" in script
    assert "autoAdvance" in script
    assert "ArrowRight" in script and "ArrowLeft" in script
    assert "step7-single-panel-active" in style
    assert "display: none !important" in style
    assert "grid-template-columns" in style
    assert "comparison-issue-list" in style


def test_step7_server_flash_is_overlay_in_fullscreen() -> None:
    style = (
        ROOT
        / "application"
        / "src"
        / "isala_ocr"
        / "training"
        / "static"
        / "step7-single-panel.css"
    ).read_text(encoding="utf-8")
    assert "body.step7-review-focus-mode > .shell > .notice" in style
    assert "position: fixed !important" in style
