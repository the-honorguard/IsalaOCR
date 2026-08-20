from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "step7-single-panel.css"
TEMPLATE = ROOT / "application" / "src" / "isala_ocr" / "training" / "templates" / "mapping_studio.html"


def test_mapping_cards_are_relation_first_and_hide_technical_provenance() -> None:
    css = CSS.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")

    assert 'content: "Welk functioneel veld hoort hierbij?"' in css
    assert '.mapping-crop-pair > div > strong' in css
    assert 'content: "LABEL"' in css
    assert 'content: "WAARDE"' in css
    assert '.mapping-crop-pair small,' in css
    assert '.mapping-detected-side > small.muted' in css
    assert 'display: none !important;' in css

    # Existing form semantics and review actions must remain intact.
    assert 'class="mapping-field-select"' in template
    assert 'class="danger ghost mapping-reject-button"' in template
    assert 'name="mapping_action" value="save"' in template
    assert 'name="mapping_action" value="save_apply"' in template


def test_mapping_value_crop_is_presented_as_evidence_not_primary_text() -> None:
    css = CSS.read_text(encoding="utf-8")

    assert 'height: 76px !important;' in css
    assert 'background: #070d13 !important;' in css
    assert 'font-size: 20px;' in css
    assert 'order: -3;' in css
