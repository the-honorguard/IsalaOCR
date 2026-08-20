from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "application/src/isala_ocr/training/templates/table_model_comparison.html"
FLOW = ROOT / "application/src/isala_ocr/training/static/step7-review-flow.js"


def test_step7_is_one_clear_iteration_page():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "Stap 6 · Afwijkingen reviewen" in template
    assert "MODELITERATIE · GT BLIJFT LEIDEND" in template
    assert "Model fout" in template
    assert "Functioneel correct" in template
    assert "GT aanpassen" in template
    assert "Nog een modeliteratie" in template
    assert "Door naar Mapping" in template
    assert "Een volgende trainingsronde is optioneel" in template


def test_step7_normal_ui_has_no_second_level_review_navigation():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert 'id="comparison-issue-filter"' not in template
    assert "compare-run-selector" not in template
    assert "Review fullscreen" not in template
    assert "+ Toevoegen aan GT" not in template
    assert 'value="add_prediction_to_gt"' not in template


def test_legacy_fullscreen_code_cannot_activate_from_normal_step7_page():
    template = TEMPLATE.read_text(encoding="utf-8")
    flow = FLOW.read_text(encoding="utf-8")
    assert "const reviewSection = filter?.closest('section.card') || null;" in flow
    assert 'id="comparison-issue-filter"' not in template


def test_step7_makes_canonical_gt_the_exit_criterion():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "De modelscore bepaalt niet of je naar Mapping mag; de canonieke GT doet dat." in template
    assert "Niet wanneer het detector-model perfect is, maar wanneer de canonieke GT klopt." in template
    assert "Stap 5 ↔ Stap 6 is een optionele verbeterlus" in template
