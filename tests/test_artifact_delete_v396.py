from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
pytest.importorskip("flask")

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.webui import create_web_app


def _app(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True)
    (project_root / "VERSION").write_text("3.9.7", encoding="utf-8")
    base = tmp_path / "training" / "workspace"
    app = create_web_app(base, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project_root)
    workspace = base / "projects" / "cmr_testcase_01"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    for idx in (1, 2, 3):
        dataset_id = f"loc-test-{idx}"
        path = workspace / "localization_datasets" / dataset_id
        path.mkdir(parents=True, exist_ok=True)
        manifest = {
            "dataset_id": dataset_id,
            "path": f"localization_datasets/{dataset_id}",
            "image_count": 14,
            "annotation_count": 10,
            "negative_image_count": 0,
            "splits": {"train": {"images": 9}, "val": {"images": 2}, "test": {"images": 3}},
            "source_splits": {},
            "created_at": f"2026-08-11T0{idx}:00:00+00:00",
        }
        (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        db.save_localization_dataset(manifest)
    (workspace / "localization_datasets" / "latest.txt").write_text("loc-test-1", encoding="ascii")
    return app, base, workspace, db


def _run_delete_job(base: Path, job_file: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    runner = root / "automation" / "training_runtime" / "artifact_delete_runner.py"
    completed = subprocess.run(
        [sys.executable, str(runner), "--job-file", str(job_file), "--workspace-base", str(base)],
        text=True, capture_output=True, check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr


def _queued_file(base: Path, response) -> Path:
    job_id = response.get_json()["job_id"]
    return base / "webui" / "jobs" / "pending" / f"{job_id}.json"


def test_current_dataset_delete_is_queued_then_replaced_by_worker(tmp_path: Path) -> None:
    app, base, workspace, db = _app(tmp_path)
    client = app.test_client()

    response = client.post("/api/v2/localization/artifacts/delete", json={
        "kind": "dataset", "id": "loc-test-1", "replacement_dataset_id": "loc-test-2"
    })
    assert response.status_code == 202, response.get_json()
    assert response.get_json()["queued"] is True
    assert (workspace / "localization_datasets" / "latest.txt").read_text(encoding="ascii").strip() == "loc-test-1"
    assert (workspace / "localization_datasets" / "loc-test-1").exists()

    job_file = _queued_file(base, response)
    _run_delete_job(base, job_file)
    assert (workspace / "localization_datasets" / "latest.txt").read_text(encoding="ascii").strip() == "loc-test-2"
    assert not (workspace / "localization_datasets" / "loc-test-1").exists()
    assert {row["dataset_id"] for row in db.list_localization_datasets()} == {"loc-test-2", "loc-test-3"}


def test_dependency_conflict_is_confirmed_before_queued_cascade(tmp_path: Path) -> None:
    app, base, workspace, db = _app(tmp_path)
    run = workspace / "localization_runs" / "run-1"
    model_dir = run / "inference"
    model_dir.mkdir(parents=True)
    db.register_localization_model({
        "model_id": "field-1", "model_name": "PicoDet-S", "path": str(model_dir),
        "device": "gpu", "dataset_id": "loc-test-1", "metrics": {}, "status": "registered",
    })
    db.save_localization_evaluation({
        "evaluation_id": "eval-1", "model_id": "field-1", "dataset_id": "loc-test-1",
        "kind": "trained", "split": "test", "metrics": {}, "predictions_path": "",
        "created_at": "2026-08-11T03:00:00+00:00",
    })
    client = app.test_client()

    blocked = client.post("/api/v2/localization/artifacts/delete", json={
        "kind": "dataset", "id": "loc-test-1", "replacement_dataset_id": "loc-test-2", "cascade": False
    })
    assert blocked.status_code == 409
    assert "afhankelijke" in blocked.get_json()["error"]
    assert (workspace / "localization_datasets" / "latest.txt").read_text(encoding="ascii").strip() == "loc-test-1"

    queued = client.post("/api/v2/localization/artifacts/delete", json={
        "kind": "dataset", "id": "loc-test-1", "replacement_dataset_id": "loc-test-2", "cascade": True
    })
    assert queued.status_code == 202, queued.get_json()
    _run_delete_job(base, _queued_file(base, queued))
    assert (workspace / "localization_datasets" / "latest.txt").read_text(encoding="ascii").strip() == "loc-test-2"
    assert db.get_localization_model("field-1") is None
    assert db.get_localization_evaluation("eval-1") is None


def test_artifact_frontend_exposes_queued_delete_state() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "frontend/src/localization-artifacts.ts").read_text(encoding="utf-8")
    assert ".catch(() => null)" not in source
    assert "replacement_dataset_id" in source
    assert "Verwijderen in wachtrij" in source
    assert "delete_jobs" in source
    assert "WORDT VERWIJDERD" in source
    assert "allowWhileBusy = false" in source
    assert "cascade`, true" in source
