from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "application" / "src" / "isala_ocr" / "training" / "webui.py"


def _process_steps() -> list[dict]:
    tree = ast.parse(WEBUI.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PROCESS_STEPS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("PROCESS_STEPS assignment not found")


def test_user_workflow_uses_one_contiguous_step_sequence() -> None:
    steps = _process_steps()
    workflow = [step for step in steps if step["group"] in {"detection", "value"}]
    assert [step["index"] for step in workflow] == list(range(1, 17))
    assert workflow[0]["key"] == "detection-models"
    assert workflow[0]["title"] == "Voorbereiding"
    assert next(step for step in steps if step["key"] == "localization-dataset")["index"] is None
    assert next(step for step in steps if step["key"] == "localization-dataset")["group"] == "fallback"
    assert next(step for step in steps if step["key"] == "localization-evaluate")["title"] == "Box-detector evalueren"
    assert next(step for step in steps if step["key"] == "localization-evaluate")["action_ids"] == ["9", "10"]
    assert next(step for step in workflow if step["key"] == "panel-setup")["index"] == 2
    assert next(step for step in workflow if step["key"] == "table-model")["index"] == 6
    assert next(step for step in workflow if step["key"] == "table-compare")["index"] == 7
    assert next(step for step in workflow if step["key"] == "mapping")["index"] == 8
    assert all(step["index"] is None for step in steps if step["group"] == "system")


def test_worker_logs_task_name_without_internal_action_number() -> None:
    worker = (ROOT / "automation" / "powershell" / "webui-worker.ps1").read_text(encoding="utf-8")
    assert 'Start taak: $($data.action_name)' in worker
    assert 'Start actie $($data.action_id)' not in worker
    assert 'PowerShell-taak wordt gestart' in worker


def test_interactive_menu_uses_workflow_steps_not_internal_action_numbers() -> None:
    menu = (ROOT / "automation" / "powershell" / "training-menu.ps1").read_text(encoding="utf-8")
    assert '"1"  = @{ Name = "Voorbereiding"' in menu
    assert '"2"  = @{ Name = "Panelen instellen"; Url = "http://127.0.0.1:8088/process/panel-setup" }' in menu
    assert '"5"  = @{ Name = "Tabeldekking beoordelen"; Url = "http://127.0.0.1:8088/process/table-quality" }' in menu
    assert '"6"  = @{ Name = "Tabelmodel verbeteren/trainen"; Url = "http://127.0.0.1:8088/process/table-model" }' in menu
    assert '"7"  = @{ Name = "Modelvergelijking & vervolg-review"; Url = "http://127.0.0.1:8088/process/table-compare" }' in menu
    assert '"8"  = @{ Name = "Mapping Studio"; ActionId = "20" }' in menu
    assert '"16" = @{ Name = "Recognition-model activeren"; ActionId = "28" }' in menu
    assert '"F1" = @{ Name = "Fallback · losse box-detector dataset/trainen"' in menu
    assert 'Write-Host "Stap 1 · Voorbereiding"' in menu
    assert 'foreach ($id in @("14","15","16","17","18","19"))' not in menu


def test_internal_action_ids_are_not_rendered_in_primary_ui(tmp_path: Path) -> None:
    pytest.importorskip("flask")
    import sys

    sys.path.insert(0, str(ROOT / "application" / "src"))
    from isala_ocr.training.webui import create_web_app

    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.8.8", encoding="utf-8")
    app = create_web_app(
        tmp_path / "training" / "workspace",
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project,
    )
    client = app.test_client()

    prep = client.get("/process/detection-models").get_data(as_text=True)
    assert "Stap 1 · Voorbereiding" in prep
    assert "<strong>17.</strong>" not in prep

    mapping = client.get("/process/mapping").get_data(as_text=True)
    assert "Stap 8 · Mapping Studio" in mapping
    assert "Stap 20 · Mapping Studio" not in mapping

    system = client.get("/process/system-checks").get_data(as_text=True)
    assert "Systeemcontroles" in system
    assert "Stap None" not in system

    queue = client.get("/jobs/manage").get_data(as_text=True)
    assert "Actie " not in queue
