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
    (project / "VERSION").write_text("3.10.1", encoding="utf-8")
    return create_web_app(
        workspace,
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project,
    ), workspace


def test_legacy_jobs_route_pins_job_to_origin_project(tmp_path: Path) -> None:
    app, workspace = make_app(tmp_path)
    client = app.test_client()

    response = client.post(
        "/jobs",
        data={"action_id": "19"},
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 202
    payload = response.get_json()
    assert payload["project_id"] == "cmr_testcase_01"
    assert payload["project_name"] == "CMR testcase 01"

    create_response = client.post(
        "/projects/create",
        data={"name": "Second project", "project_id": "second_project"},
    )
    assert create_response.status_code == 302

    queued = json.loads(
        (workspace / "webui" / "jobs" / "pending" / f"{payload['job_id']}.json").read_text(encoding="utf-8")
    )
    assert queued["project_id"] == "cmr_testcase_01"
    assert queued["project_name"] == "CMR testcase 01"


def test_legacy_models_page_redirects_to_canonical_management(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    response = app.test_client().get("/models")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/manage?tab=models")
