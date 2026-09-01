from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_table_first_preparation_is_scoped_to_inference_component() -> None:
    webui = read("application/src/isala_ocr/training/webui.py")
    assert "def preparation_for_current_strategy()" in webui
    assert 'if item.get("key") == "inference"' in webui
    assert '"scope": "table_first"' in webui
    assert 'return jsonify({"ok": True, "preparation": preparation_for_current_strategy()})' in webui
    assert 'state["preparation"] = preparation_for_current_strategy()' in webui


def test_step_one_prioritizes_readiness_and_next_step() -> None:
    template = read("application/src/isala_ocr/training/templates/process_step.html")
    assert 'data-prep-main-status' in template
    assert "GEREED" in template
    assert "NIET GEREED" in template
    assert "Stap 2 · Tabelregio’s selecteren" in template
    assert "Onderhoud / opnieuw installeren" in template
    assert "Je hoeft hier niets meer te installeren" in template
    # Training-stack metrics are deliberately not part of the normal table-first view.
    detection_block = template.split("{% if step.key == 'detection-models' %}", 2)[-1].split("{% elif step.key == 'detect-candidates' %}", 1)[0]
    assert "Training-image versie" not in detection_block
    assert "Trainingbestanden" not in detection_block


def test_step_one_client_selects_single_repair_action() -> None:
    client = read("application/src/isala_ocr/training/static/preparation-page.js")
    assert "ONE_CLICK_PREPARATION" in client
    assert "actionId: '1'" in client
    assert "Alles voorbereiden" in client
    assert "enforceOneClickAction" in client
    assert "readyAction.hidden = !allReady" in client
    assert "repairAction.hidden = allReady" in client
