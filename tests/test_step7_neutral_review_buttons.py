from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "application/src/isala_ocr/training/templates/base.html"
CSS = ROOT / "application/src/isala_ocr/training/static/step7-review.css"


def test_step7_review_styles_are_loaded():
    base = BASE.read_text(encoding="utf-8")
    assert "step7-review.css" in base


def test_step7_review_options_are_neutral_until_selected():
    css = CSS.read_text(encoding="utf-8")
    assert ".comparison-issue-actions button" in css
    assert "background: transparent !important" in css
    assert 'data-issue-decision="functional_ok"' in css
    assert 'data-issue-decision="model_error"' in css
    assert 'data-issue-decision="gt_check"' in css
    assert 'content: " ✓"' in css


def test_old_unconditional_checks_are_visually_replaced():
    css = CSS.read_text(encoding="utf-8")
    assert 'input[name="decision"][value="functional_ok"]' in css
    assert 'content: "Functioneel correct"' in css
    assert 'input[name="decision"][value="model_error"]' in css
    assert 'content: "Model fout"' in css
