from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html"


def test_missing_cell_action_lives_with_review_decisions() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    dock_start = source.index('id="selection-dock"')
    dock_end = source.index('</section>', dock_start)
    dock = source[dock_start:dock_end]
    assert 'id="dock-include"' in dock
    assert 'id="dock-reject"' in dock
    assert 'id="draw-missing"' in dock
    assert dock.index('id="dock-reject"') < dock.index('id="draw-missing"') < dock.index('id="dock-edit"')


def test_missing_cell_action_removed_from_general_canvas_toolbar() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    toolbar_start = source.index('class="actions review-selection-actions')
    toolbar_end = source.index('</div>\n</div>', toolbar_start)
    toolbar = source[toolbar_start:toolbar_end]
    assert 'id="draw-missing"' not in toolbar
