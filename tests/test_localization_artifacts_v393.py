from __future__ import annotations

from pathlib import Path

import pytest
pytest.importorskip("flask")

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.webui import create_web_app


def _app_with_artifacts(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True)
    (project_root / "VERSION").write_text("3.9.5", encoding="utf-8")
    base = tmp_path / "training" / "workspace"
    app = create_web_app(base, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project_root)
    workspace = base / "projects" / "cmr_testcase_01"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    for idx in (1, 2):
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
            "source_splits": {f"s{i}": "train" if i < 9 else "val" if i < 11 else "test" for i in range(14)},
            "created_at": f"2026-08-11T0{idx}:00:00+00:00",
        }
        (path / "manifest.json").write_text(__import__("json").dumps(manifest), encoding="utf-8")
        db.save_localization_dataset(manifest)
    pointer = workspace / "localization_datasets" / "latest.txt"
    pointer.write_text("loc-test-1", encoding="ascii")

    run = workspace / "localization_runs" / "run-1"
    model_dir = run / "inference"
    model_dir.mkdir(parents=True)
    db.register_localization_model({
        "model_id": "field-1", "model_name": "PicoDet-S", "path": str(model_dir),
        "device": "gpu", "dataset_id": "loc-test-1", "metrics": {}, "status": "registered",
    })
    db.save_localization_evaluation({
        "evaluation_id": "eval-1", "model_id": "field-1", "dataset_id": "loc-test-1",
        "kind": "trained", "split": "test", "metrics": {"recall": 0.5, "precision": 0.6},
        "predictions_path": "", "created_at": "2026-08-11T03:00:00+00:00",
    })
    return app, workspace, db


def test_artifact_api_can_select_dataset_and_model_without_deleting_them(tmp_path: Path) -> None:
    app, workspace, _db = _app_with_artifacts(tmp_path)
    client = app.test_client()
    payload = client.get("/api/v2/localization/artifacts").get_json()
    assert len(payload["datasets"]) == 2
    assert payload["selection"]["current_dataset_id"] == "loc-test-1"

    response = client.post("/api/v2/localization/selection", json={
        "evaluation_dataset_id": "loc-test-2", "evaluation_model_id": "field-1"
    })
    assert response.status_code == 200
    selection = response.get_json()["selection"]
    assert selection["evaluation_dataset_id"] == "loc-test-2"
    assert selection["evaluation_model_id"] == "field-1"
    selection_file = workspace / "localization_artifact_selection.json"
    assert selection_file.is_file()
    assert '"model_id": "field-1"' in selection_file.read_text(encoding="utf-8")


def test_artifact_delete_api_queues_work_and_keeps_dependency_safeguards(tmp_path: Path) -> None:
    app, workspace, db = _app_with_artifacts(tmp_path)
    client = app.test_client()

    current = client.post("/api/v2/localization/artifacts/delete", json={"kind": "dataset", "id": "loc-test-1"})
    assert current.status_code == 409
    assert "werkdataset" in current.get_json()["error"]

    queued = client.post("/api/v2/localization/artifacts/delete", json={"kind": "dataset", "id": "loc-test-2"})
    assert queued.status_code == 202
    assert queued.get_json()["queued"] is True
    # Queueing must not mutate artifacts in the Flask request.
    assert db.get_localization_model("field-1") is not None
    assert (workspace / "localization_datasets" / "loc-test-2").exists()

    blocked_model = client.post("/api/v2/localization/artifacts/delete", json={"kind": "model", "id": "field-1"})
    assert blocked_model.status_code == 409
    cascaded = client.post("/api/v2/localization/artifacts/delete", json={"kind": "model", "id": "field-1", "cascade": True})
    assert cascaded.status_code == 202

    payload = client.get("/api/v2/localization/artifacts").get_json()
    keys = {(item["kind"], item["id"]) for item in payload["delete_jobs"]}
    assert ("dataset", "loc-test-2") in keys
    assert ("model", "field-1") in keys


def test_artifact_page_and_quality_client_support_react16_runtime() -> None:
    root = Path(__file__).resolve().parents[1]
    quality = (root / "frontend/src/localization-quality.ts").read_text(encoding="utf-8")
    artifacts = (root / "frontend/src/localization-artifacts.ts").read_text(encoding="utf-8")
    template = (root / "application/src/isala_ocr/training/templates/react_localization_artifacts.html").read_text(encoding="utf-8")
    assert "ReactDOM.createRoot" not in quality
    assert "React.Fragment" not in quality
    assert "ReactDOM.render(element, qualityMount)" in quality
    assert "ReactDOM.createRoot" not in artifacts
    assert "React.Fragment" not in artifacts
    assert "ReactDOM.render(app, artifactMount)" in artifacts
    assert 'id="react-localization-artifacts"' in template
