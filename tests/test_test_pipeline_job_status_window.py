"""A proefpagina rerun's live status must not depend on how many *other* jobs
exist in the system.

``job_statuses(limit)`` (webui.py) truncates to the N *most recently created*
jobs system-wide before returning them. "Alles testen" can queue dozens of
reruns in one click, and any unrelated job traffic on top of that easily
pushes an earlier job 61 out of a small, unscoped window -- its row would
then show "Testen" again even though a rerun is genuinely still queued,
because neither ``has_output`` nor a job entry would be found for it. The fix
scopes the ``test_pipeline()``/``test_pipeline_rerun_all()`` lookups to
``action_ids={"61"}`` before the limit ever applies.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.routes_jobs import write_job_payload
from isala_ocr.training.webui import create_web_app

ORIGIN_ID = "aaaaaaaaaaaaaaaaaaaaaaaa"
RERUN_ID = "bbbbbbbbbbbbbbbbbbbbbbbb"
PROJECT_ID = "cmr_testcase_01"


def _app(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True)
    (project_root / "VERSION").write_text("3.9.7", encoding="utf-8")
    base = tmp_path / "training" / "workspace"
    app = create_web_app(base, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project_root)
    workspace = base / "projects" / PROJECT_ID
    jobs_root = base / "webui" / "jobs"
    return app, workspace, jobs_root


def _seed_trained_origin(workspace: Path) -> None:
    database = TrainingDatabase(workspace / "samples.sqlite3")
    database.upsert_sample({
        "sample_id": f"sample-{ORIGIN_ID}", "source_id": ORIGIN_ID, "profile": "cmr",
        "field_key": "field_a", "field_label": "Field A", "crop_path": "crops/x.png",
        "image_width": 8, "image_height": 8, "roi_x1": 0, "roi_y1": 0, "roi_x2": 4, "roi_y2": 4,
        "raw_ocr": "12", "raw_confidence": 0.9, "raw_variant": "original",
        "extraction_method": "dynamic_ocr", "status": "pending",
    })
    root = workspace / "extracted_output"
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{ORIGIN_ID}.json").write_text(json.dumps({
        "generated_at": "2026-01-01T00:00:00Z",
        "measurements": {"field_a": {"display_name": "Field A", "parsed_value": "12", "raw_text": "12"}},
    }), encoding="utf-8")


def _write_job(jobs_root: Path, *, job_id: str, action_id: str, status: str, created_at: str) -> None:
    write_job_payload(jobs_root, {
        "job_id": job_id, "action_id": action_id, "action_name": "test",
        "project_id": PROJECT_ID, "project_name": "CMR testcase 01",
        "options": {}, "status": status,
        "progress_percent": 0, "progress_mode": "indeterminate", "progress_label": "",
        "created_at": created_at, "updated_at": created_at,
    })


def test_running_rerun_survives_a_flood_of_newer_unrelated_jobs(tmp_path: Path) -> None:
    app, workspace, jobs_root = _app(tmp_path)
    from isala_ocr.training.test_pipeline_sources import record_test_pipeline_source

    _seed_trained_origin(workspace)
    _write_job(jobs_root, job_id="job-real-1", action_id="61", status="running", created_at="2026-01-01T00:00:00Z")
    record_test_pipeline_source(workspace, RERUN_ID, origin_source_id=ORIGIN_ID, job_id="job-real-1")

    # 25 newer, unrelated jobs -- more than enough to push job-real-1 out of
    # an unscoped job_statuses(20) window if the lookup weren't scoped to
    # action 61 first.
    for index in range(25):
        _write_job(
            jobs_root, job_id=f"job-noise-{index}", action_id="2", status="pending",
            created_at=f"2026-01-02T00:00:{index:02d}Z",
        )

    body = app.test_client().get("/test-pipeline").get_data(as_text=True)
    assert "Bezig" in body, "a genuinely running rerun must not revert to 'Testen' just because other jobs exist"
    assert "Testen</button>" not in body, "the row must not offer 'Testen' again while its rerun is still running"


def test_alles_testen_does_not_double_queue_a_rerun_hidden_by_job_noise(tmp_path: Path) -> None:
    app, workspace, jobs_root = _app(tmp_path)
    from isala_ocr.training.test_pipeline_sources import job_of_test_pipeline_source, record_test_pipeline_source

    _seed_trained_origin(workspace)
    _write_job(jobs_root, job_id="job-real-1", action_id="61", status="running", created_at="2026-01-01T00:00:00Z")
    record_test_pipeline_source(workspace, RERUN_ID, origin_source_id=ORIGIN_ID, job_id="job-real-1")
    for index in range(25):
        _write_job(
            jobs_root, job_id=f"job-noise-{index}", action_id="2", status="pending",
            created_at=f"2026-01-02T00:00:{index:02d}Z",
        )

    # "Alles testen" must recognize the in-flight rerun and skip it, not
    # start a second one on top of it (it would fail to find /input anyway
    # on this host, but the point under test is the *skip decision* itself).
    response = app.test_client().post("/test-pipeline/alles-testen", follow_redirects=True)
    assert response.status_code == 200
    assert job_of_test_pipeline_source(workspace, RERUN_ID) == "job-real-1", (
        "the original in-flight job must still be the tracked one; a second rerun must not have been queued"
    )
