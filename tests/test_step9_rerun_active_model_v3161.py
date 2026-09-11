from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "application/src/isala_ocr/training/templates/table_model_comparison.html"


def test_step9_offers_a_rerun_button_for_the_active_model() -> None:
    """Stap 9 lets you get a fresh detection run without leaving the page.

    Previously the only way to feed Stap 9 a new detection run was to go
    back to Stap 8 and either retrain, or use one of its standalone
    "Dataset bouwen"/"Model activeren" actions. Rerunning detection with
    the model that is already active needs neither: it's the same
    action_id="2" job (Celdetectie uitvoeren) the rest of the app already
    posts to /jobs, scoped to the active model via table_model_id.
    """
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "{% if active_model.model_id %}" in template
    assert "Actief model opnieuw draaien" in template
    assert 'name="action_id" value="2"' in template
    assert 'name="table_model_id" value="active"' in template
    # It's a plain form[action="/jobs"], so app.js's generic job handler
    # picks it up without any extra data-custom-job-submit wiring.
    assert '<form method="post" action="/jobs">' in template
