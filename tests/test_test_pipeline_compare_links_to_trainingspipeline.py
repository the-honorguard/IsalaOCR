"""The proefpagina compare screen only ever showed the training pipeline's
own stage data inline -- there was no way to jump to that source's own
single-source pages (``/output-review/...``) to dig into why, say, a cell's
text is missing there. Each "Trainingspipeline (bekend)" column now links to
the matching single-source page for the origin source_id.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.webui import create_web_app

ORIGIN_ID = "aaaaaaaaaaaaaaaaaaaaaaaa"
RERUN_ID = "bbbbbbbbbbbbbbbbbbbbbbbb"


def _app(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True)
    (project_root / "VERSION").write_text("3.9.7", encoding="utf-8")
    base = tmp_path / "training" / "workspace"
    app = create_web_app(base, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project_root)
    workspace = base / "projects" / "cmr_testcase_01"
    return app, workspace


def _write_output(workspace: Path, source_id: str, value: str) -> None:
    database = TrainingDatabase(workspace / "samples.sqlite3")
    database.upsert_sample({
        "sample_id": f"sample-{source_id}", "source_id": source_id, "profile": "cmr",
        "field_key": "field_a", "field_label": "Field A", "crop_path": "crops/x.png",
        "image_width": 8, "image_height": 8, "roi_x1": 0, "roi_y1": 0, "roi_x2": 4, "roi_y2": 4,
        "raw_ocr": value, "raw_confidence": 0.9, "raw_variant": "original",
        "extraction_method": "dynamic_ocr", "status": "pending",
    })
    root = workspace / "extracted_output"
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{source_id}.json").write_text(json.dumps({
        "generated_at": "2026-01-01T00:00:00Z",
        "measurements": {"field_a": {"display_name": "Field A", "parsed_value": value, "raw_text": value}},
    }), encoding="utf-8")


def test_compare_screen_links_each_known_column_to_its_source_page(tmp_path: Path) -> None:
    app, workspace = _app(tmp_path)
    from isala_ocr.training.test_pipeline_sources import record_test_pipeline_source

    _write_output(workspace, ORIGIN_ID, "12")
    _write_output(workspace, RERUN_ID, "12")
    record_test_pipeline_source(workspace, RERUN_ID, origin_source_id=ORIGIN_ID, job_id="job-1")

    response = app.test_client().get(f"/test-pipeline/vergelijk/{RERUN_ID}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    assert f"/output-review/{ORIGIN_ID}/tabellen" in body
    assert f"/output-review/{ORIGIN_ID}/cellen" in body
    assert f"/output-review/{ORIGIN_ID}" in body
    # The link goes to the origin (known) source, never the rerun itself.
    assert f"/output-review/{RERUN_ID}/cellen" not in body
