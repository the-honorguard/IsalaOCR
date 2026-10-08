"""job_log() (routes_jobs.py) used to read all three log files in full on
every single poll, regardless of which stream was requested - the activity
dock polls this every ~2s while a job is running. These tests cover the fix:
only the file(s) the requested stream actually needs are read, and each read
is tailed instead of reading the whole (potentially multi-megabyte) file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

try:
    import flask  # noqa: F401
except ModuleNotFoundError:
    FLASK_AVAILABLE = False
else:
    FLASK_AVAILABLE = True
    sys.path.insert(0, str(ROOT / "application" / "src"))
    from isala_ocr.training.webui import create_web_app


def _seed_job(tmp_path: Path):
    workspace = tmp_path / "training" / "workspace"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.14.0", encoding="utf-8")
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
        "job_id": job_id, "action_id": "17", "action_name": "Test action",
        "status": "running",
        "created_at": "2026-08-10T09:58:00+00:00", "updated_at": "2026-08-10T09:58:01+00:00",
    }
    (status / f"{job_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    return app, logs, job_id


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask is not installed in the test runtime")
def test_large_log_is_tailed_not_fully_reread(tmp_path: Path) -> None:
    app, logs, job_id = _seed_job(tmp_path)
    # Larger than the 200000-byte tail window job_log() now reads.
    old_content = "OLD-START-MARKER\n" + "x" * 300_000
    (logs / f"{job_id}.log").write_text(old_content + "\nRECENT-MARKER\n", encoding="utf-8")

    client = app.test_client()
    stdout = client.get(f"/api/jobs/{job_id}/log?stream=stdout").get_data(as_text=True)

    assert "RECENT-MARKER" in stdout
    # A tailed read must not pull in content from near the start of a file
    # this much larger than the tail window.
    assert "OLD-START-MARKER" not in stdout


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask is not installed in the test runtime")
def test_stream_specific_request_does_not_read_other_streams_log_files(tmp_path: Path, monkeypatch) -> None:
    app, logs, job_id = _seed_job(tmp_path)
    (logs / f"{job_id}.log").write_text("stdout-only\n", encoding="utf-8")
    (logs / f"{job_id}.log.err").write_text("stderr-only\n", encoding="utf-8")
    (logs / f"{job_id}.worker.log").write_text("worker-only\n", encoding="utf-8")

    read_paths: list[str] = []
    import isala_ocr.training.routes_jobs as routes_jobs_module

    original = routes_jobs_module._read_log_text

    def tracking_read(path, **kwargs):
        read_paths.append(path.name)
        return original(path, **kwargs)

    monkeypatch.setattr(routes_jobs_module, "_read_log_text", tracking_read)

    client = app.test_client()
    client.get(f"/api/jobs/{job_id}/log?stream=stdout")
    assert read_paths == [f"{job_id}.log"], f"stream=stdout should only read the stdout log, got {read_paths}"

    read_paths.clear()
    client.get(f"/api/jobs/{job_id}/log?stream=overview")
    assert set(read_paths) == {f"{job_id}.worker.log", f"{job_id}.log", f"{job_id}.log.err"}
