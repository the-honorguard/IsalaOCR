from pathlib import Path

from isala_ocr.training.table_model_evaluation_policy import (
    AUTO_FUNCTIONAL_GT_COVERAGE,
    AUTO_FUNCTIONAL_PREDICTION_EXCESS,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "application/src/isala_ocr/training/templates/table_model_comparison.html"
WEBUI = ROOT / "application/src/isala_ocr/training/webui.py"
COMPARISON = ROOT / "application/src/isala_ocr/training/table_model_comparison.py"


def test_step7_geometry_review_has_functionally_correct_decision():
    template = TEMPLATE.read_text(encoding="utf-8")
    webui = WEBUI.read_text(encoding="utf-8")
    comparison = COMPARISON.read_text(encoding="utf-8")
    assert 'name="decision" value="functional_ok"' in template
    assert "Functioneel correct ✓" in template
    assert "Functioneel correct" in template
    assert '"functional_ok": "Geometrie functioneel correct bevonden"' in webui
    assert '"functional_ok"' in comparison


def test_step7_geometry_review_shows_coverage_and_excess_metrics():
    template = TEMPLATE.read_text(encoding="utf-8")
    comparison = COMPARISON.read_text(encoding="utf-8")
    assert "GT gedekt" in template
    assert "extra prediction" in template
    assert "waarschijnlijk bruikbaar" in template
    assert AUTO_FUNCTIONAL_GT_COVERAGE == 0.92
    assert AUTO_FUNCTIONAL_PREDICTION_EXCESS == 0.30
    assert "FUNCTIONAL_GT_COVERAGE = 0.95" in comparison
    assert "FUNCTIONAL_PREDICTION_EXCESS = 0.30" in comparison
    assert '"gt_coverage"' in comparison
    assert '"prediction_excess"' in comparison
