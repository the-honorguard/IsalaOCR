from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html"


def test_missing_cell_action_enters_draw_mode_without_modal():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert 'id="draw-dialog"' not in source
    assert 'id="manual-reason"' not in source
    assert 'id="manual-notes"' not in source
    assert "document.getElementById('draw-missing').onclick" in source
    assert "drawMode=true" in source
    assert "reason_code:'other',notes:''" in source
    assert "Tekenmodus actief" in source


def test_escape_cancels_direct_draw_mode_before_closing_fullscreen():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "if(drawMode){drawMode=false;drawStart=null" in source
    assert "Tekenmodus geannuleerd." in source

def test_draw_mode_can_start_over_canvas_overlays():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "if(drawMode&&!e.target.closest('.review-selection-dock'))" in source
