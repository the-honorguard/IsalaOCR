from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_sidebar_contains_all_process_tabs_and_versioned_assets() -> None:
    base = (ROOT / "application/src/isala_ocr/training/templates/base.html").read_text(encoding="utf-8")
    webui = (ROOT / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    assert "PROCESS_STEPS = [" in webui
    assert 'href="/process/{{ step.key }}"' in base
    assert "filename='app.js',v=app_version" in base
    assert "filename='app.css',v=app_version" in base
    for key in (
        "detection-models", "detect-candidates", "detection-review",
        "localization-dataset",
        "localization-evaluate", "localization-register", "redetect",
        "detection-report", "mapping", "apply-mapping", "value-extract", "value-review",
        "recognition-dataset", "recognition-train",
        "recognition-evaluate", "recognition-models", "artifacts", "system-checks", "maintenance",
    ):
        assert f'"key": "{key}"' in webui
    assert '"key": "recognition-validate"' not in webui


def test_worker_writes_separate_lifecycle_log() -> None:
    worker = (ROOT / "automation/powershell/webui-worker.ps1").read_text(encoding="utf-8")
    assert "function Add-WorkerLog" in worker
    assert '($data.job_id+".worker.log")' in worker
    assert "Worker heeft taak" in worker
    assert "Onderliggend proces gestart" in worker
    assert "Taak voltooid met exitcode 0" in worker


try:
    import flask  # noqa: F401
except ModuleNotFoundError:
    FLASK_AVAILABLE = False
    PROCESS_STEPS = []
    create_web_app = None
else:
    FLASK_AVAILABLE = True
    sys.path.insert(0, str(ROOT / "application" / "src"))
    from isala_ocr.training.webui import PROCESS_STEPS, create_web_app


def make_app(tmp_path: Path):
    workspace = tmp_path / "training" / "workspace"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.5.14", encoding="utf-8")
    return create_web_app(
        workspace,
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project,
    ), workspace


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask is not installed in the test runtime")
def test_every_process_tab_renders_without_data(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    client = app.test_client()
    for step in PROCESS_STEPS:
        response = client.get(f"/process/{step['key']}")
        assert response.status_code == 200, step["key"]
        text = response.get_data(as_text=True)
        if step["index"] is not None:
            assert f"Stap {step['index']}" in text
        else:
            assert "Stap None" not in text
        assert step["title"] in text


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask is not installed in the test runtime")
def test_pending_job_terminal_is_never_blank(tmp_path: Path) -> None:
    app, workspace = make_app(tmp_path)
    client = app.test_client()
    response = client.post(
        "/jobs",
        data={"action_id": "5"},
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    job_id = response.get_json()["job_id"]
    log = client.get(f"/api/jobs/{job_id}/log")
    assert log.status_code == 200
    text = log.get_data(as_text=True)
    assert "Taak aangemaakt: Localization-dataset bouwen (COCO)" in text
    assert "Status: in wachtrij" in text
    assert "Nog geen scriptuitvoer ontvangen" in text
    assert log.headers["Cache-Control"].startswith("no-store")



@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask is not installed in the test runtime")
def test_value_pipeline_job_is_blocked_while_detection_gate_is_closed(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    response = app.test_client().post(
        "/jobs",
        data={"action_id": "20"},
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 423
    assert "Detection gate" in response.get_json()["error"]

@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask is not installed in the test runtime")
def test_utf16_windows_output_is_rendered_as_visible_text(tmp_path: Path) -> None:
    app, workspace = make_app(tmp_path)
    jobs = workspace / "webui" / "jobs"
    job_id = "job-20260806T140000-abcd1234"
    payload = {
        "job_id": job_id,
        "action_id": "5",
        "action_name": "Localization-dataset bouwen (COCO)",
        "status": "running",
        "created_at": "2026-08-06T12:00:00+00:00",
        "started_at": "2026-08-06T12:00:01+00:00",
        "updated_at": "2026-08-06T12:00:01+00:00",
    }
    (jobs / "status").mkdir(parents=True, exist_ok=True)
    (jobs / "logs").mkdir(parents=True, exist_ok=True)
    (jobs / "status" / f"{job_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    (jobs / "logs" / f"{job_id}.log").write_bytes("Docker dataset bouwen\r\n32 samples\r\n".encode("utf-16-le"))
    text = app.test_client().get(f"/api/jobs/{job_id}/log").get_data(as_text=True)
    assert "Docker dataset bouwen" in text
    assert "32 samples" in text
    assert "\x00" not in text
