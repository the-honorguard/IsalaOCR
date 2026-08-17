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


def test_step7_reverse_selection_opens_hidden_issue_without_breaking_open_filter_semantics():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "const matchesFilter=" in template
    assert "!rows.some(row=>matchesFilter(row,filter.value))" in template
    assert "filter.value='all'" in template
    assert ".comparison-issue-row.is-filtered,.comparison-panel-card.is-filtered{display:none}" in template


def test_step7_reverse_selection_supports_keyboard_and_pressed_state():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert 'aria-pressed="false"' in template
    assert "box.setAttribute('aria-pressed','true')" in template
    assert "event.key==='Enter'||event.key===' '" in template
    assert "event.key==='Escape'" in template
    assert "Klik om de gekoppelde afwijking rechts te markeren" in template
