from pathlib import Path

from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "application" / "src" / "isala_ocr" / "training" / "templates"


def test_labeler_templates_parse_and_offer_uncertain_queue() -> None:
    environment = Environment(loader=FileSystemLoader(TEMPLATES))
    environment.get_template("base.html")
    environment.get_template("dashboard.html")
    environment.get_template("sample.html")

    dashboard = (TEMPLATES / "dashboard.html").read_text(encoding="utf-8")
    assert "max_confidence=0.8&ocr_content=text" in dashboard
    assert "blank_or_missing" in dashboard
    assert "Onzekere waarden &lt;80%" in dashboard
    assert "fixed_fallback" not in dashboard
    assert "extraction_method" not in dashboard


def test_review_page_has_presence_buttons_and_preserves_filters() -> None:
    sample = (TEMPLATES / "sample.html").read_text(encoding="utf-8")
    assert 'value="value_correct"' in sample
    assert 'value="value_save"' in sample
    assert 'value="placeholder"' in sample
    assert 'value="no_value"' in sample
    assert 'value="roi_error"' not in sample
    assert "locator" not in sample.lower()
    assert "Alt+L" in sample
    assert 'name="max_confidence_filter"' in sample
    assert 'name="ocr_content_filter"' in sample
    assert 'name="extraction_method_filter"' not in sample


def test_default_queue_is_pending_nonempty_below_eighty_percent() -> None:
    labeler = (ROOT / "application" / "src" / "isala_ocr" / "training" / "labeler.py").read_text(encoding="utf-8")
    assert '"status": "pending"' in labeler
    assert '"max_confidence": "0.8"' in labeler
    assert '"ocr_content": "text"' in labeler
    assert "exclude_sample_id=sample_id" in labeler
