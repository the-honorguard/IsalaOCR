from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "src"))

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.webui import create_web_app


def make_app(tmp_path: Path):
    workspace = tmp_path / "training" / "workspace"
    database = TrainingDatabase(workspace / "samples.sqlite3")
    database.upsert_field_definition(
        "custom.measurement",
        "Custom measurement",
        group_name="Custom",
        data_type="decimal",
        preferred_unit="ml",
        aliases=["Custom value"],
    )
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.6.4", encoding="utf-8")
    app = create_web_app(
        workspace,
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project,
        config_path=ROOT / "application" / "config" / "app.yaml",
    )
    return app, database


def test_field_schema_replaces_hardcoded_header_normalization(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    response = app.test_client().get("/field-schema")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Veldschema" in text
    assert "Functionele outputvelden beheren" in text
    assert "Custom measurement" in text
    assert "custom.measurement" in text
    assert "Aliassen" in text
    assert "Datatype" in text


def test_new_field_can_be_added_without_detector_code_change(tmp_path: Path) -> None:
    app, database = make_app(tmp_path)
    response = app.test_client().post(
        "/field-schema",
        data={
            "schema_action": "save",
            "field_key": "generic.new_value",
            "display_name": "New value",
            "group_name": "Generic",
            "data_type": "decimal",
            "preferred_unit": "mm",
            "aliases": "Nieuwe waarde; New value",
            "minimum_value": "0",
            "maximum_value": "999",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    project_database = TrainingDatabase(
        tmp_path / "training" / "workspace" / "projects" / "cmr_testcase_01" / "samples.sqlite3"
    )
    stored = project_database.get_field_definition("generic.new_value")
    assert stored is not None
    assert stored["preferred_unit"] == "mm"
    assert stored["aliases"] == ["Nieuwe waarde", "New value"]
