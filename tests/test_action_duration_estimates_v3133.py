import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "application/src/isala_ocr/training/webui.py"


def _literal_assignment(name: str):
    tree = ast.parse(WEBUI.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"Assignment {name} not found")


def test_every_worker_action_has_a_duration_estimate():
    actions = _literal_assignment("ACTIONS")
    estimates = _literal_assignment("ACTION_DURATION_ESTIMATES")
    assert set(actions) <= set(estimates)
    for action_id, estimate in estimates.items():
        assert estimate["label"].startswith("± "), action_id
        assert estimate["detail"].strip(), action_id


def test_primary_table_first_actions_have_useful_estimates():
    estimates = _literal_assignment("ACTION_DURATION_ESTIMATES")
    assert estimates["2"]["label"] == "± 2–10 min"
    assert estimates["48"]["label"] == "± 10–60 sec"
    assert estimates["50"]["label"] == "± 8–20 min"
    assert estimates["51"]["label"] == "± 1–4 uur"
    assert estimates["52"]["label"] == "± 10–30 sec"


def test_base_exposes_estimates_and_app_js_annotates_job_buttons():
    base = (ROOT / "application/src/isala_ocr/training/templates/base.html").read_text(encoding="utf-8")
    js = (ROOT / "application/src/isala_ocr/training/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "application/src/isala_ocr/training/static/app.css").read_text(encoding="utf-8")

    assert "window.ISALA_ACTION_DURATION_ESTIMATES" in base
    assert "annotateActionDurations" in js
    assert 'form[action="/jobs"]' in js
    assert "Geschatte duur" in js
    assert "action-duration-estimate" in css
    assert "v3.13.3: visible approximate duration" in css
