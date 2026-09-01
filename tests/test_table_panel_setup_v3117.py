from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_panel_setup_has_fullscreen_focus_editor_and_source_navigation():
    template = (ROOT / "application/src/isala_ocr/training/templates/table_panel_setup.html").read_text(encoding="utf-8")
    assert 'id="panel-focus"' in template
    assert 'body.panel-focus-mode .panel-setup-layout' in template
    assert 'panel-focus-list-hidden' in template
    assert 'id="panel-list-toggle"' in template
    assert 'id="panel-prev-source"' in template
    assert 'id="panel-next-source"' in template
    assert 'layoutFocusStage' in template
    assert 'requestFullscreen' in template
    assert 'fullscreenchange' in template
    assert 'Er zijn niet-opgeslagen wijzigingen aan deze lezing' in template
    assert 'async function loadSource' in template
    assert '/api/table-panel-review-source/' in template
    assert 'history.replaceState' in template
    assert 'window.location.href' not in template
    assert '<button type="button" class="source-row' in template
