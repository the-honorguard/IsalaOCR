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
    """PROCESS_STEPS now splits the primary sequence across three groups:
    "detection" (indices 1-6), "tables" (table-compare/table-quality, index
    8 and an intentionally unindexed table-compare) and "value" (indices
    10-15). Within each of "detection" and "value" the indices are still one
    contiguous run - that per-group contiguity is what this test checks,
    rather than a single 1..16 sequence spanning every group.
    """
    steps = _process_steps()
    workflow = [step for step in steps if step["group"] in {"detection", "value"}]

    detection_indices = sorted(step["index"] for step in workflow if step["group"] == "detection")
    value_indices = sorted(step["index"] for step in workflow if step["group"] == "value" and step["index"] is not None)
    assert detection_indices == list(range(detection_indices[0], detection_indices[0] + len(detection_indices)))
    assert value_indices == list(range(value_indices[0], value_indices[0] + len(value_indices)))

    assert workflow[0]["key"] == "detection-models"
    assert workflow[0]["index"] == 1
    assert workflow[0]["title"] == "Voorbereiding"
    assert next(step for step in steps if step["key"] == "localization-dataset")["index"] is None
    assert next(step for step in steps if step["key"] == "localization-dataset")["group"] == "fallback"
    assert next(step for step in steps if step["key"] == "localization-evaluate")["title"] == "Box-detector evalueren"
    assert next(step for step in steps if step["key"] == "localization-evaluate")["action_ids"] == ["9", "10"]
    assert next(step for step in workflow if step["key"] == "panel-setup")["index"] == 2
    assert next(step for step in workflow if step["key"] == "table-model")["index"] == 6
    # table-compare now belongs to the "tables" group with no numbered index -
    # it is intentionally excluded from the detection/value workflow count.
    table_compare = next(step for step in steps if step["key"] == "table-compare")
    assert table_compare["group"] == "tables"
    assert table_compare["index"] is None
    table_quality = next(step for step in steps if step["key"] == "table-quality")
    assert table_quality["group"] == "tables"
    assert table_quality["index"] == 8
    assert next(step for step in workflow if step["key"] == "mapping")["index"] == 13
    assert all(step["index"] is None for step in steps if step["group"] == "system")


def test_worker_logs_task_name_without_internal_action_number() -> None:
    worker = (ROOT / "automation" / "powershell" / "webui-worker.ps1").read_text(encoding="utf-8")
    assert 'Start taak: $($data.action_name)' in worker
    assert 'Start actie $($data.action_id)' not in worker
    assert 'PowerShell-taak wordt gestart' in worker


def test_interactive_menu_uses_workflow_steps_not_internal_action_numbers() -> None:
    menu = (ROOT / "automation" / "powershell" / "training-menu.ps1").read_text(encoding="utf-8")
    assert '"1"  = @{ Name = "Voorbereiding"; ActionId = "1" }' in menu
    assert '"2"  = @{ Name = "Tabelregio’s selecteren"; Url = "http://127.0.0.1:8088/process/panel-setup" }' in menu
    assert '"6"  = @{ Name = "Celdetector verbeteren"; Url = "http://127.0.0.1:8088/process/table-model" }' in menu
    assert '"8"  = @{ Name = "Tabelstudio"; Url = "http://127.0.0.1:8088/process/table-quality" }' in menu
    assert '"13" = @{ Name = "Application Mapping Studio"; ActionId = "20" }' in menu
    assert '"16" = @{ Name = "Application output beoordelen"; Url = "http://127.0.0.1:8088/review" }' in menu
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
        # The real app config pins localization.strategy to "table_first"
        # (application/config/app.yaml); use it so the workflow gate below
        # exercises the same primary sequence/topbar behavior production
        # actually runs, instead of the "/app/config/app.yaml"-not-found
        # fallback ("fusion" strategy).
        config_path=ROOT / "application" / "config" / "app.yaml",
    )
    client = app.test_client()

    prep = client.get("/process/detection-models").get_data(as_text=True)
    assert "Stap 1 · Voorbereiding" in prep
    assert "<strong>17.</strong>" not in prep

    # /process/mapping is gated behind enforce_primary_workflow_gate: a
    # hand-typed URL is bounced back to the first incomplete step unless the
    # step immediately before "mapping" in the table-first workflow sequence
    # ("recognition-output-review") is already ready. Satisfy that readiness
    # first so the gate actually lets the request through.
    from isala_ocr.training.projects import ProjectManager

    client.get("/")  # ensure the default project workspace exists on disk
    pm = ProjectManager(tmp_path / "training" / "workspace")
    runs_dir = pm.active_workspace() / "runs"
    (runs_dir / "evaluation-baseline-1").mkdir(parents=True)
    (runs_dir / "evaluation-baseline-1" / "evaluation.json").write_text("{}", encoding="utf-8")
    (runs_dir / "evaluation-custom-1").mkdir(parents=True)
    (runs_dir / "evaluation-custom-1" / "evaluation.json").write_text("{}", encoding="utf-8")

    mapping = client.get("/process/mapping").get_data(as_text=True)
    assert "Redirecting" not in mapping
    # The table-first topbar script (base.html) overrides the heading to this
    # text client-side; it is what a user actually sees on /process/mapping.
    assert "Stap 14 · Mapping Studio" in mapping
    assert "Stap 20 · Mapping Studio" not in mapping

    system = client.get("/process/system-checks").get_data(as_text=True)
    assert "Systeemcontroles" in system
    assert "Stap None" not in system

    queue = client.get("/jobs/manage").get_data(as_text=True)
    assert "Actie " not in queue
