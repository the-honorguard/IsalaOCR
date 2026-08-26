from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "src"))

from isala_ocr.training.webui import create_web_app


def make_app(tmp_path: Path):
    workspace = tmp_path / "training" / "workspace"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.5.6", encoding="utf-8")
    return create_web_app(
        workspace,
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project,
    ), workspace


def test_activity_dock_is_rendered_on_every_page(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    response = app.test_client().get("/activation")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'id="activity-dock"' in text
    assert 'id="activity-terminal"' in text
    assert 'id="activity-progress-bar"' in text
    assert 'id="activity-copy-all"' in text
    assert 'id="activity-refresh"' not in text
    assert 'id="activity-collapse"' not in text


def test_job_statuses_are_ordered_by_creation_not_status_update(tmp_path: Path) -> None:
    app, workspace = make_app(tmp_path)
    status_root = workspace / "webui" / "jobs" / "status"
    status_root.mkdir(parents=True, exist_ok=True)
    old_job = {
        "job_id": "job-20260826T100000-old",
        "action_id": "23",
        "action_name": "Oude taak",
        "status": "completed",
        "created_at": "2026-08-26T10:00:00+00:00",
        "updated_at": "2026-08-26T11:00:00+00:00",
    }
    new_job = {
        "job_id": "job-20260826T105000-new",
        "action_id": "23",
        "action_name": "Nieuwe taak",
        "status": "failed",
        "created_at": "2026-08-26T10:50:00+00:00",
        "updated_at": "2026-08-26T10:51:00+00:00",
    }
    (status_root / f"{old_job['job_id']}.json").write_text(json.dumps(old_job), encoding="utf-8")
    (status_root / f"{new_job['job_id']}.json").write_text(json.dumps(new_job), encoding="utf-8")

    jobs = app.test_client().get("/api/status").get_json()["jobs"]
    assert [job["job_id"] for job in jobs[:2]] == [new_job["job_id"], old_job["job_id"]]


def test_ajax_job_is_immediately_visible_before_worker_poll(tmp_path: Path) -> None:
    app, workspace = make_app(tmp_path)
    client = app.test_client()
    response = client.post(
        "/jobs",
        data={"action_id": "16", "model_id": "isala-rec-test"},
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 202
    payload = response.get_json()
    job_id = payload["job_id"]
    assert (workspace / "webui" / "jobs" / "pending" / f"{job_id}.json").is_file()
    assert (workspace / "webui" / "jobs" / "status" / f"{job_id}.json").is_file()

    state = client.get("/api/status").get_json()
    matching = [job for job in state["jobs"] if job["job_id"] == job_id]
    assert len(matching) == 1
    assert matching[0]["status"] == "pending"
    assert matching[0]["progress_percent"] == 0.0
    assert matching[0]["progress_mode"] == "indeterminate"


def test_job_log_combines_stdout_and_stderr(tmp_path: Path) -> None:
    app, workspace = make_app(tmp_path)
    logs = workspace / "webui" / "jobs" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    job_id = "job-20260806T120000-abcdef12"
    (logs / f"{job_id}.log").write_text("normal output\n", encoding="utf-8")
    (logs / f"{job_id}.log.err").write_text("problem output\n", encoding="utf-8")
    text = app.test_client().get(f"/api/jobs/{job_id}/log").get_data(as_text=True)
    assert "normal output" in text
    assert "--- STDERR ---" in text
    assert "problem output" in text


def test_activation_progress_is_derived_from_terminal_stage(tmp_path: Path) -> None:
    app, workspace = make_app(tmp_path)
    jobs = workspace / "webui" / "jobs"
    job_id = "job-20260806T120001-abcdef13"
    payload = {
        "job_id": job_id,
        "action_id": "16",
        "action_name": "Geregistreerd model activeren",
        "status": "running",
        "created_at": "2026-08-06T10:00:00+00:00",
        "updated_at": "2026-08-06T10:00:01+00:00",
    }
    (jobs / "status").mkdir(parents=True, exist_ok=True)
    (jobs / "logs").mkdir(parents=True, exist_ok=True)
    (jobs / "status" / f"{job_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    (jobs / "logs" / f"{job_id}.log").write_text("[1/4] start\n[2/4] prepare\n[3/4] activate\n", encoding="utf-8")
    state = app.test_client().get("/api/status").get_json()
    job = next(item for item in state["jobs"] if item["job_id"] == job_id)
    assert job["progress_percent"] == 75.0
    assert job["progress_label"] == "Model activeren"


def test_worker_script_writes_heartbeat_and_current_job() -> None:
    text = (ROOT / "automation" / "powershell" / "webui-worker.ps1").read_text(encoding="utf-8")
    assert "heartbeat_at" in text
    assert "current_job_id" in text
    assert "while(-not $proc.HasExited)" in text
    assert "CreatedAt = [string]$queued.created_at" in text
    assert "Sort-Object @{Expression={ if ([string]::IsNullOrWhiteSpace($_.CreatedAt))" in text


def test_webui_start_replaces_an_obsolete_worker_process_tree() -> None:
    text = (ROOT / "automation" / "powershell" / "label-training-data.ps1").read_text(encoding="utf-8")
    assert "$expectedWorkerVersion" in text
    assert "$State.worker_version -ne $expectedWorkerVersion" in text
    assert "function Stop-ObsoleteIsalaWorker" in text
    assert "taskkill.exe /PID $pidValue /T /F" in text
    assert "-NonInteractive" in text


def test_webui_start_recreates_an_outdated_labeler_container() -> None:
    text = (ROOT / "automation" / "powershell" / "label-training-data.ps1").read_text(encoding="utf-8")
    assert '$expectedLabelerImage = "isalaocr-labeler:$expectedWorkerVersion"' in text
    assert "$existingInfo.Config.Image" in text
    assert "$labelerImageIsCurrent" in text
    assert "Webinterface update detected" in text


def test_worker_adds_missing_json_properties_safely_for_windows_powershell_51() -> None:
    text = (ROOT / "automation" / "powershell" / "webui-worker.ps1").read_text(encoding="utf-8")
    assert "function Set-JobProperty" in text
    assert "Add-Member -MemberType NoteProperty" in text
    assert 'Set-JobProperty $data "started_at"' in text
    assert '$data.started_at=' not in text
    assert '$data.finished_at=' not in text


def test_activity_terminal_stays_compact_when_jobs_start() -> None:
    script = (ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "app.js").read_text(encoding="utf-8")
    submit = script.split("async function submitJob(form)", 1)[1].split("document.querySelectorAll('form[action=\"/jobs\"]')", 1)[0]
    assert "setExpanded(true)" not in submit
    assert "setActiveJob(payload.job_id, false)" in submit
    assert "isala-activity-terminal-expanded-v2" in script
    assert "params.has('job_id')" not in script.split("const initiallyExpanded", 1)[1].split(";", 1)[0]

    css = (ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "app.css").read_text(encoding="utf-8")
    assert ".activity-dock.collapsed{height:44px}" in css
    assert ".activity-dock.collapsed .activity-worker{display:none}" in css
