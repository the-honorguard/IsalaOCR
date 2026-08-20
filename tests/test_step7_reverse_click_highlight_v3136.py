from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "application/src/isala_ocr/training/templates/table_model_comparison.html"


def test_step7_issue_boxes_click_back_to_linked_issue_row():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "comparison-clickable-box" in template
    assert 'role="button" tabindex="0"' in template
    assert "box.addEventListener('click',activate)" in template
    assert "selectIssue(box.dataset.compareIssueId||'')" in template
    assert "row.classList.add('is-selected')" in template
    assert "box.classList.add('is-selected')" in template
    assert "row.scrollIntoView({behavior:'smooth',block:'nearest'})" in template


def test_step7_normal_iteration_has_no_filter_or_nested_review_mode():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert 'id="comparison-issue-filter"' not in template
    assert "compare-run-selector" not in template
    assert "Review fullscreen" not in template
    assert "+ Toevoegen aan GT" not in template
    assert "data-optimistic-hidden" in template


def test_step7_reverse_selection_supports_keyboard_and_pressed_state():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert 'aria-pressed="false"' in template
    assert "box.setAttribute('aria-pressed','true')" in template
    assert "event.key==='Enter'||event.key===' '" in template
    assert "event.key==='Escape'" in template
    assert "Klik om de gekoppelde afwijking rechts te markeren" in template
