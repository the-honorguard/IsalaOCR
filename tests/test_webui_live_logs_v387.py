from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_worker_keeps_stdout_and_stderr_separate_and_uses_truthful_progress() -> None:
    worker = (ROOT / "automation/powershell/webui-worker.ps1").read_text(encoding="utf-8")
    assert "-RedirectStandardOutput $logFile" in worker
    assert "-RedirectStandardError $errorFile" in worker
    assert "2>&1" not in worker
    assert 'Set-JobProperty $data "progress_percent" 45' not in worker
    assert 'Set-JobProperty $data "progress_mode" "indeterminate"' in worker
    assert "Get-LiveProgressLabel -StdoutPath $logFile -StderrPath $errorFile" in worker
    assert "Docker/Compose uses both stdout and stderr" in worker


def test_activity_dock_exposes_separate_stream_tabs_and_live_follow() -> None:
    base = (ROOT / "application/src/isala_ocr/training/templates/base.html").read_text(encoding="utf-8")
    js = (ROOT / "application/src/isala_ocr/training/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "application/src/isala_ocr/training/static/app.css").read_text(encoding="utf-8")

    for stream in ("stdout", "stderr", "worker", "overview"):
        assert f'data-activity-log-stream="{stream}"' in base
    assert "Live / STDOUT" in base
    assert 'id="activity-stderr-badge"' in base
    assert "Naar live output ↓" in base
    assert "activeLogStream" in js
    assert "isala-log-stream" in js
    assert "isala-stderr-seen:" in js
    assert "stream=${encodeURIComponent(activeLogStream)}" in js
    assert "logStates = new Map()" in js
    assert ".activity-log-tabs" in css
    assert ".activity-log-tab.active" in css


def test_web_api_has_independent_log_streams() -> None:
    # job_log() lives in routes_jobs.py (split out of webui.py); job_statuses(),
    # which builds the stderr_bytes counter, stays in webui.py.
    webui = (ROOT / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    routes_jobs = (ROOT / "application/src/isala_ocr/training/routes_jobs.py").read_text(encoding="utf-8")
    assert 'stream=str(request.args.get("stream") or "overview")' in routes_jobs
    assert '{"overview","stdout","stderr","worker"}' in routes_jobs
    assert 'response.headers["X-Isala-Log-Stream"]=stream' in routes_jobs
    assert 'item["stderr_bytes"]' in webui


try:
    import flask  # noqa: F401
except ModuleNotFoundError:
    FLASK_AVAILABLE = False
else:
    FLASK_AVAILABLE = True
    sys.path.insert(0, str(ROOT / "application" / "src"))
    from isala_ocr.training.webui import create_web_app


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask is not installed in the test runtime")
def test_stream_endpoints_do_not_mix_stdout_stderr_and_worker(tmp_path: Path) -> None:
    workspace = tmp_path / "training" / "workspace"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.8.8", encoding="utf-8")
    app = create_web_app(
        workspace,
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project,
    )
    jobs = workspace / "webui" / "jobs"
    logs = jobs / "logs"
    status = jobs / "status"
    logs.mkdir(parents=True, exist_ok=True)
    status.mkdir(parents=True, exist_ok=True)
    job_id = "job-20260810T115800-abcdef12"
    payload = {
        "job_id": job_id,
        "action_id": "17",
        "action_name": "GPU PaddleDetection / PicoDet-S stack installeren",
        "status": "running",
        "created_at": "2026-08-10T09:58:00+00:00",
        "updated_at": "2026-08-10T09:58:01+00:00",
    }
    (status / f"{job_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    (logs / f"{job_id}.log").write_text("stdout-only\n", encoding="utf-8")
    (logs / f"{job_id}.log.err").write_text("stderr-only\n", encoding="utf-8")
    (logs / f"{job_id}.worker.log").write_text("worker-only\n", encoding="utf-8")

    client = app.test_client()
    stdout = client.get(f"/api/jobs/{job_id}/log?stream=stdout").get_data(as_text=True)
    stderr = client.get(f"/api/jobs/{job_id}/log?stream=stderr").get_data(as_text=True)
    worker = client.get(f"/api/jobs/{job_id}/log?stream=worker").get_data(as_text=True)
    overview = client.get(f"/api/jobs/{job_id}/log?stream=overview").get_data(as_text=True)

    assert "stdout-only" in stdout and "stderr-only" not in stdout and "worker-only" not in stdout
    assert "stderr-only" in stderr and "stdout-only" not in stderr and "worker-only" not in stderr
    assert "worker-only" in worker and "stdout-only" not in worker and "stderr-only" not in worker
    assert "--- STDOUT ---" in overview and "--- STDERR ---" in overview and "--- WORKER ---" in overview
