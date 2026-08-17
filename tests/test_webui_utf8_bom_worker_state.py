import json
from pathlib import Path

import pytest
pytest.importorskip("flask")
from isala_ocr.training.webui import create_web_app


def test_webui_accepts_powershell_utf8_bom_worker_state(tmp_path: Path):
    workspace = tmp_path / "training" / "workspace"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.5.6", encoding="utf-8")
    jobs = workspace / "webui" / "jobs"
    jobs.mkdir(parents=True)
    payload = {
        "pid": 123,
        "worker_version": "3.5.6",
        "state": "idle",
        "current_job_id": "",
        "heartbeat_at": "2099-08-06T12:45:00+02:00",
    }
    (jobs / "worker.json").write_text(json.dumps(payload), encoding="utf-8-sig")
    app = create_web_app(workspace, project_root=project)
    client = app.test_client()
    response = client.get("/api/jobs")
    assert response.status_code == 200
    body = response.get_json()
    assert body["worker"]["worker_version"] == "3.5.6"
    assert body["worker"]["online"] is True


def test_worker_writes_json_without_bom():
    text = Path("automation/powershell/webui-worker.ps1").read_text(encoding="utf-8")
    assert "System.Text.UTF8Encoding($false)" in text
    assert "Write-JsonUtf8NoBom -Value $payload" in text
    assert "Write-JsonUtf8NoBom -Value $data" in text
