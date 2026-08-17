from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _template() -> str:
    return (ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html").read_text(encoding="utf-8")


def _css() -> str:
    return (ROOT / "application/src/isala_ocr/training/static/app.css").read_text(encoding="utf-8")


def test_selection_is_separate_from_geometry_editing() -> None:
    template = _template()
    assert 'id="select-tool"' in template
    assert 'id="edit-tool"' in template
    assert "function setEditMode" in template
    assert "if(!editMode)" in template
    assert "dblclick" in template
    assert "selectionSize()===1" in template


def test_marquee_is_direct_live_and_supports_add_subtract() -> None:
    template = _template()
    assert "mode=e.altKey?'subtract'" in template
    assert "?'add':'replace'" in template
    assert "function previewMarquee" in template
    assert "function marqueeMatches" in template
    assert "overlapRatio(area,b)>=0.18" in template
    assert "selection-preview" in template


def test_candidate_list_has_explicit_multi_select_and_hover_linking() -> None:
    template = _template()
    css = _css()
    assert 'class="candidate-select-indicator"' in template
    assert "function linkHover" in template
    assert "mouseenter" in template and "mouseleave" in template
    assert ".candidate-select-indicator.checked" in css
    assert ".review-box.hover-linked" in css


def test_multi_selection_gets_exception_first_command_toolbar() -> None:
    template = _template()
    css = _css()
    assert 'id="selection-dock"' in template
    for control in ("dock-include", "dock-irrelevant", "dock-reject", "dock-edit", "dock-clear"):
        assert f'id="{control}"' in template
    assert 'id="source-done"' in template
    assert "selectionDock.classList.remove('hidden')" in template
    assert ".review-command-dock" in css


def test_ctrl_a_selects_current_visible_filter() -> None:
    template = _template()
    assert 'id="select-visible"' in template
    assert "function selectVisible" in template
    assert "e.key.toLowerCase()==='a'" in template
    assert "visibleRows()" in template
