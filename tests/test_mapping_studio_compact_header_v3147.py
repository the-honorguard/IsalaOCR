from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "step7-single-panel.css"
TEMPLATE = ROOT / "application" / "src" / "isala_ocr" / "training" / "templates" / "mapping_studio.html"


def test_mapping_studio_hides_internal_header_clutter_but_keeps_card_workflow():
    css = CSS.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")

    assert ".mapping-feedback-learning," in css
    assert ".mapping-summary ~ section.card:has(.mapping-suggestion-list)" in css
    assert ".mapping-summary + .notice," in css
    assert "display: none !important;" in css

    # The underlying feedback/suggestion machinery stays available to the
    # backend and to relation-card state; only the duplicate top-level UI is
    # removed from the normal workflow.
    assert 'class="notice mapping-feedback-learning"' in template
    assert 'class="mapping-suggestion-list"' in template
    assert 'class="mapping-field-select"' in template
    assert 'value="save"' in template
    assert 'value="save_apply"' in template
